import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.auth import get_current_user

router = APIRouter(prefix="/api/version-control", tags=["version-control"])

# Version Control Database Connection
VC_DATABASE_URL = os.getenv(
    "VC_DATABASE_URL",
    "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp_version_control"
)

# Create engine and session maker for VC database
vc_engine = create_engine(VC_DATABASE_URL)
VCSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=vc_engine)


def get_vc_db():
    """Dependency to get version control database session"""
    db = VCSessionLocal()
    try:
        yield db
    finally:
        db.close()


class DeactivatedVersion(BaseModel):
    """Model for deactivated server version"""
    id: str = Field(..., description="Version ID")
    gateway_id: str = Field(..., description="Gateway ID")
    server_name: str = Field(..., description="Server name")
    server_version: str = Field(..., description="Server version")
    version_number: int = Field(..., description="Version number")
    tools_count: int = Field(..., description="Number of tools")
    status: str = Field(..., description="Version status")
    created_at: str = Field(..., description="Creation timestamp")
    created_by: str = Field(..., description="Creator")


class DeactivatedVersionsResponse(BaseModel):
    """Response model for listing deactivated versions"""
    total: int = Field(..., description="Total number of deactivated versions")
    versions: List[DeactivatedVersion] = Field(..., description="List of deactivated versions")


class DeleteVersionResponse(BaseModel):
    """Response model for delete operation"""
    success: bool = Field(..., description="Whether deletion was successful")
    deleted_count: int = Field(..., description="Number of versions deleted")
    deleted_ids: List[str] = Field(..., description="List of deleted version IDs")
    activated_count: int = Field(default=0, description="Number of pending versions activated")
    activated_ids: List[str] = Field(default_factory=list, description="List of activated version IDs")


@router.get(
    "/deactivated",
    response_model=DeactivatedVersionsResponse,
    summary="List all deactivated server versions",
    description="Returns all server versions with status='deactivated' from the version control database"
)
async def list_deactivated_versions(
    db: Session = Depends(get_vc_db),
    current_user = Depends(get_current_user)
):
    """
    List all deactivated server versions.
    
    Returns:
        DeactivatedVersionsResponse with list of deactivated versions
    """
    try:
        # Query deactivated versions from version control database
        query = text("""
            SELECT 
                id::text,
                gateway_id::text,
                server_name,
                server_version,
                version_number,
                tools_count,
                status,
                created_at::text,
                created_by
            FROM server_versions
            WHERE status = 'deactivated'
            ORDER BY created_at DESC
        """)
        
        result = db.execute(query)
        rows = result.fetchall()
        
        versions = [
            DeactivatedVersion(
                id=row[0],
                gateway_id=row[1],
                server_name=row[2],
                server_version=row[3],
                version_number=row[4],
                tools_count=row[5],
                status=row[6],
                created_at=row[7],
                created_by=row[8]
            )
            for row in rows
        ]
        
        return DeactivatedVersionsResponse(
            total=len(versions),
            versions=versions
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch deactivated versions: {str(e)}"
        )


@router.delete(
    "/versions",
    response_model=DeleteVersionResponse,
    summary="Delete server versions by IDs",
    description="Deletes one or more server versions from the version control database by their IDs"
)
async def delete_versions(
    ids: List[str] = Query(..., description="List of version IDs to delete"),
    db: Session = Depends(get_vc_db),
    current_user = Depends(get_current_user)
):
    """
    Delete server versions by their IDs.
    
    Args:
        ids: List of version IDs to delete
        
    Returns:
        DeleteVersionResponse with deletion results
    """
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="No IDs provided for deletion"
        )
    
    try:
        # First, get the versions to be deleted to track their gateway_id and server_name
        check_query = text("""
            SELECT id::text, gateway_id::text, server_name
            FROM server_versions
            WHERE id::text = ANY(:ids)
        """)
        
        result = db.execute(check_query, {"ids": ids})
        rows = result.fetchall()
        
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"None of the provided IDs were found: {ids}"
            )
        
        existing_ids = [row[0] for row in rows]
        
        # Track unique gateway_id + server_name combinations
        affected_servers = set()
        for row in rows:
            affected_servers.add((row[1], row[2]))  # (gateway_id, server_name)
        
        # Delete the versions
        delete_query = text("""
            DELETE FROM server_versions
            WHERE id::text = ANY(:ids)
        """)
        
        db.execute(delete_query, {"ids": existing_ids})
        
        # For each affected server, activate the most recent pending version
        activated_ids = []
        for gateway_id, server_name in affected_servers:
            # Find the most recent pending version for this server
            pending_query = text("""
                SELECT id::text
                FROM server_versions
                WHERE gateway_id::text = :gateway_id
                  AND server_name = :server_name
                  AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
            """)
            
            pending_result = db.execute(
                pending_query,
                {"gateway_id": gateway_id, "server_name": server_name}
            )
            pending_row = pending_result.fetchone()
            
            if pending_row:
                pending_id = pending_row[0]
                
                # First, set all versions for this server to is_current=False
                update_current_query = text("""
                    UPDATE server_versions
                    SET is_current = FALSE
                    WHERE gateway_id::text = :gateway_id
                      AND server_name = :server_name
                """)
                
                db.execute(
                    update_current_query,
                    {"gateway_id": gateway_id, "server_name": server_name}
                )
                
                # Then activate the pending version
                activate_query = text("""
                    UPDATE server_versions
                    SET status = 'active', is_current = TRUE
                    WHERE id::text = :id
                """)
                
                db.execute(activate_query, {"id": pending_id})
                activated_ids.append(pending_id)
        
        db.commit()
        
        return DeleteVersionResponse(
            success=True,
            deleted_count=len(existing_ids),
            deleted_ids=existing_ids,
            activated_count=len(activated_ids),
            activated_ids=activated_ids
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete versions: {str(e)}"
        )
