import os
import sys
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from mcpgateway.auth import get_current_user

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'plugins', 'version_control'))
from core.version_control_core import VersionControlCore, VersionControlDB, ServerVersion

router = APIRouter(prefix="/api/version-control", tags=["version-control"])


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


@router.get(
    "/pending",
    response_model=DeactivatedVersionsResponse,
    summary="List all pending server versions",
    description="Returns all server versions with status='pending' awaiting approval"
)
async def list_pending_versions(
    current_user = Depends(get_current_user)
):
    """
    List all pending server versions awaiting approval.
    
    Returns:
        DeactivatedVersionsResponse with list of pending versions
    """
    try:
        vc_core = get_vc_core()
        
        # Get all blocked versions and filter for pending only
        all_blocked, _ = vc_core.list_blocked_versions()
        pending_versions = [v for v in all_blocked if v.status == 'pending']
        
        versions = [
            DeactivatedVersion(
                id=str(v.id),
                gateway_id=str(v.gateway_id),
                server_name=v.server_name,
                server_version=v.server_version,
                version_number=v.version_number,
                tools_count=v.tools_count,
                status=v.status,
                created_at=str(v.created_at),
                created_by=v.created_by
            )
            for v in pending_versions
        ]
        
        return DeactivatedVersionsResponse(
            total=len(versions),
            versions=versions
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch pending versions: {str(e)}"
        )


@router.get(
    "/active",
    response_model=DeactivatedVersionsResponse,
    summary="List all active server versions",
    description="Returns all server versions with status='active' from the version control database"
)
async def list_active_versions(
    current_user = Depends(get_current_user)
):
    """
    List all active server versions.
    
    Returns:
        DeactivatedVersionsResponse with list of active versions
    """
    try:
        vc_core = get_vc_core()
        
        # Query for active versions
        with vc_core.db.get_vc_session() as session:
            from sqlalchemy import select
            query = select(ServerVersion).where(
                ServerVersion.status == 'active'
            ).order_by(
                ServerVersion.created_at.desc(),
                ServerVersion.version_number.desc()
            )
            result = session.execute(query)
            active_versions_list = result.scalars().all()
            
            # Detach from session
            for v in active_versions_list:
                session.expunge(v)
        
        versions = [
            DeactivatedVersion(
                id=str(v.id),
                gateway_id=str(v.gateway_id),
                server_name=v.server_name,
                server_version=v.server_version,
                version_number=v.version_number,
                tools_count=v.tools_count,
                status=v.status,
                created_at=str(v.created_at),
                created_by=v.created_by
            )
            for v in active_versions_list
        ]
        
        return DeactivatedVersionsResponse(
            total=len(versions),
            versions=versions
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active versions: {str(e)}"
        )


@router.get(
    "/deactivated",
    response_model=DeactivatedVersionsResponse,
    summary="List all deactivated server versions",
    description="Returns all server versions with status='deactivated' from the version control database"
)
async def list_deactivated_versions(
    current_user = Depends(get_current_user)
):
    """
    List all deactivated server versions.
    
    Returns:
        DeactivatedVersionsResponse with list of deactivated versions
    """
    try:
        vc_core = get_vc_core()
        
        # Get all blocked versions and filter for deactivated only
        all_blocked, _ = vc_core.list_blocked_versions()
        deactivated_versions = [v for v in all_blocked if v.status == 'deactivated']
        
        versions = [
            DeactivatedVersion(
                id=str(v.id),
                gateway_id=str(v.gateway_id),
                server_name=v.server_name,
                server_version=v.server_version,
                version_number=v.version_number,
                tools_count=v.tools_count,
                status=v.status,
                created_at=str(v.created_at),
                created_by=v.created_by
            )
            for v in deactivated_versions
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


class UpdateVersionStatusRequest(BaseModel):
    """Request model for updating version status"""
    new_status: str = Field(..., description="New status (active, pending, or deactivated)")


class UpdateVersionStatusResponse(BaseModel):
    """Response model for update version status operation"""
    success: bool = Field(..., description="Whether update was successful")
    version_id: str = Field(..., description="Version ID that was updated")
    old_status: str = Field(..., description="Previous status")
    new_status: str = Field(..., description="New status")
    message: str = Field(..., description="Human-readable message about the operation")


@router.put(
    "/versions/{version_id}/update-status",
    response_model=UpdateVersionStatusResponse,
    summary="Update version status",
    description="Update the status of a server version (approve/reject pending versions, deactivate active versions)"
)
async def update_version_status(
    version_id: str,
    request: UpdateVersionStatusRequest,
    current_user = Depends(get_current_user)
):
    """
    Update the status of a server version using VersionControlCore.
    
    This endpoint allows administrators to:
    - Approve pending versions (set status to 'active')
    - Reject pending versions (set status to 'deactivated')
    - Deactivate active versions (set status to 'deactivated')
    
    Args:
        version_id: Version UUID to update
        request: Request body with new_status
        
    Returns:
        UpdateVersionStatusResponse with update results
    """
    try:
        # Get user email from current_user (EmailUser object)
        user_email = getattr(current_user, "email", None) or getattr(current_user, "username", "api_user")
        
        vc_core = get_vc_core()
        
        # Get the version before update to track old status
        with vc_core.db.get_vc_session() as session:
            from sqlalchemy import select
            # Compare as string since id column is String(36), not UUID type
            query = select(ServerVersion).where(ServerVersion.id == version_id)
            old_version = session.execute(query).scalar_one_or_none()
            
            if not old_version:
                raise HTTPException(
                    status_code=404,
                    detail=f"Version {version_id} not found"
                )
            
            old_status = old_version.status
        
        # Update the version status
        updated_version = vc_core.update_version_status(
            version_id=version_id,
            new_status=request.new_status,
            updated_by=user_email
        )
        
        if updated_version:
            return UpdateVersionStatusResponse(
                success=True,
                version_id=str(updated_version.id),
                old_status=old_status,
                new_status=updated_version.status,
                message=f"Successfully updated version {version_id} status from '{old_status}' to '{updated_version.status}'"
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version_id} not found"
            )
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update version status: {str(e)}"
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
    
    # Initialize the VC database engine and session
    # This must be called before using get_vc_session()
    db_manager.create_database_if_not_exists()
    db_manager.create_tables()
    
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
        # Get user email from current_user (EmailUser object)
        user_email = getattr(current_user, "email", None) or getattr(current_user, "username", "api_user")
        
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
