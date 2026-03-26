import os
import sys
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.auth import get_current_user

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'plugins', 'version_control'))
from core.version_control_core import VersionControlCore, VersionControlDB

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


class CheckChangesResponse(BaseModel):
    """Response model for check_for_changes endpoint"""
    gateway_id: str = Field(..., description="Gateway ID that was checked")
    has_changes: bool = Field(..., description="Whether changes were detected")
    message: str = Field(..., description="Human-readable message about the check result")


class CreatePendingVersionResponse(BaseModel):
    """Response model for create_pending_version endpoint"""
    success: bool = Field(..., description="Whether version creation was successful")
    version: Optional[dict] = Field(None, description="Created version details")
    message: str = Field(..., description="Human-readable message about the operation")


def get_vc_core():
    """Get VersionControlCore instance with database manager"""
    main_db_url = os.getenv("DATABASE_URL", "sqlite:///./mcp.db")
    vc_db_url = os.getenv(
        "VC_DATABASE_URL",
        "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp_version_control"
    )
    
    db_manager = VersionControlDB(
        main_db_url=main_db_url,
        vc_db_url=vc_db_url,
        echo=False
    )
    
    return VersionControlCore(db_manager=db_manager)


@router.post(
    "/check-changes/{gateway_id}",
    response_model=CheckChangesResponse,
    summary="Check if gateway tools have changed",
    description="Compares current server state with the latest version record to detect changes"
)
async def check_gateway_changes(
    gateway_id: str,
    current_user = Depends(get_current_user)
):
    """
    Check if a gateway's tools have changed since the last version.
    
    Args:
        gateway_id: Gateway UUID to check
        
    Returns:
        CheckChangesResponse with change detection results
    """
    try:
        vc_core = get_vc_core()
        has_changes = await vc_core.check_for_changes(gateway_id)
        
        if has_changes:
            message = f"Changes detected for gateway {gateway_id}"
        else:
            message = f"No changes detected for gateway {gateway_id}"
        
        return CheckChangesResponse(
            gateway_id=gateway_id,
            has_changes=has_changes,
            message=message
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check for changes: {str(e)}"
        )


@router.post(
    "/create-pending/{gateway_id}",
    response_model=CreatePendingVersionResponse,
    summary="Create a pending version for a gateway",
    description="Creates a new pending version record when changes are detected. The new version will block tool calls until approved."
)
async def create_pending_gateway_version(
    gateway_id: str,
    current_user = Depends(get_current_user)
):
    """
    Create a new pending version record for a gateway.
    
    This endpoint creates a pending version with status='pending' and is_current=True,
    which will block tool calls until an admin reviews and approves it.
    
    Args:
        gateway_id: Gateway UUID
        
    Returns:
        CreatePendingVersionResponse with creation results
    """
    try:
        # Get user email from current_user
        user_email = current_user.get("email") or current_user.get("username", "api_user")
        
        vc_core = get_vc_core()
        version = await vc_core.create_pending_version(
            gateway_id=gateway_id,
            created_by=user_email
        )
        
        if version:
            version_dict = {
                "id": version.id,
                "gateway_id": version.gateway_id,
                "server_name": version.server_name,
                "server_version": version.server_version,
                "version_number": version.version_number,
                "tools_hash": version.tools_hash,
                "version_hash": version.version_hash,
                "tools_count": version.tools_count,
                "is_current": version.is_current,
                "status": version.status,
                "created_at": str(version.created_at),
                "created_by": version.created_by
            }
            
            return CreatePendingVersionResponse(
                success=True,
                version=version_dict,
                message=f"Successfully created pending version {version.version_number} for gateway {gateway_id}"
            )
        else:
            return CreatePendingVersionResponse(
                success=False,
                version=None,
                message=f"Failed to create pending version for gateway {gateway_id}"
            )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create pending version: {str(e)}"
        )
