"""
Version Control Plugin for ContextForge

This plugin automatically tracks MCP server versions and detects changes:
- Monitors all registered MCP servers
- Detects when tools are added, removed, or modified
- Maintains complete version history in separate database
- Polls servers every 60 seconds for changes

Architecture:
- Separate database: mcp_version_control (isolated from main mcp database)
- Hash-based change detection: SHA256 of tools list + server version
- Session management: Handles STREAMABLEHTTP session IDs correctly
- Async operations: All MCP calls are async to avoid blocking
"""

import logging
import asyncio
from typing import Any, Dict

from sqlalchemy import text

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig, PluginViolation, PluginContext
from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload, ToolPreInvokeResult

# Import the core version control logic
from .core.version_control_core import VersionControlCore, VersionControlDB


class VersionControlPlugin(Plugin):
    """
    Plugin that tracks MCP server versions and tool changes.
    
    Features:
    - Automatic server discovery on startup
    - Background polling every 60 seconds to detect new servers
    - Hash-based change detection
    - Complete version history tracking
    - Blocks tool calls to deactivated servers
    """

    def __init__(self, config: PluginConfig):
        """Initialize the Version Control plugin"""
        super().__init__(config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Get configuration
        plugin_config = config.config or {}
        self.enabled = plugin_config.get("enabled", True)
        self.polling_interval = plugin_config.get("polling_interval", 60)  # seconds
        
        # Database configuration
        main_db_url = plugin_config.get("main_db_url")
        vc_db_url = plugin_config.get("vc_db_url")
        
        if not main_db_url or not vc_db_url:
            self.logger.error("Missing database URLs in plugin config")
            self.enabled = False
            return
        
        # Initialize database manager
        try:
            self.db_manager = VersionControlDB(
                main_db_url=main_db_url,
                vc_db_url=vc_db_url
            )
            # Auto-create database if it doesn't exist
            self.db_manager.create_database_if_not_exists()
            # Create tables
            self.db_manager.create_tables()
            self.logger.info("Version control database initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            self.enabled = False
            return
        
        # Initialize core logic
        self.vc_core = VersionControlCore(self.db_manager)
        
        # Background polling task
        self._polling_task = None
        self._shutdown_event = asyncio.Event()
        
        self.logger.info("VersionControlPlugin initialized")

    async def initialize(self) -> None:
        """
        Called when the plugin initializes.
        Performs initial backfill and starts background polling.
        """
        if not self.enabled:
            self.logger.warning("Version Control plugin is disabled")
            return
        
        self.logger.info("Starting Version Control plugin...")
        
        # Step 1: Backfill existing servers (one-time on startup)
        try:
            self.logger.info("Performing initial server backfill...")
            backfilled = await self.vc_core.backfill_existing_servers(created_by="plugin")
            self.logger.info(f"✅ Initial backfill complete: {backfilled} servers")
        except Exception as e:
            self.logger.error(f"❌ Failed to backfill servers: {e}", exc_info=True)
        
        # Step 2: Start background polling task
        self._polling_task = asyncio.create_task(self._polling_loop())
        self.logger.info(f"✅ Background polling started (interval: {self.polling_interval}s)")

    async def _polling_loop(self) -> None:
        """
        Background task that polls for changes every N seconds.
        
        This task:
        1. Checks for new servers and backfills them (creates version 1)
        2. Checks existing servers for changes and creates pending versions
        """
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.polling_interval)
                
                # Step 1: Check for new servers and backfill them
                backfilled = await self.vc_core.backfill_existing_servers(created_by="polling")
                if backfilled > 0:
                    self.logger.info(f"🔄 Polling: Discovered and backfilled {backfilled} new server(s)")
                
                # Step 2: Check existing servers for changes
                gateways = self.vc_core.discover_existing_servers()
                changes_detected = 0
                
                for gateway in gateways:
                    gateway_id = gateway['id']
                    gateway_name = gateway['name']
                    
                    try:
                        # Check if this server has changes
                        has_changes = await self.vc_core.check_for_changes(gateway_id)
                        
                        if has_changes:
                            # Create pending version
                            pending_version = await self.vc_core.create_pending_version(
                                gateway_id,
                                created_by="polling"
                            )
                            
                            if pending_version:
                                self.logger.info(
                                    f"🔍 Polling: Changes detected in {gateway_name}, "
                                    f"created pending version {pending_version.version_number}"
                                )
                                changes_detected += 1
                            else:
                                self.logger.warning(
                                    f"⚠️ Polling: Changes detected in {gateway_name} but "
                                    f"failed to create pending version"
                                )
                    except Exception as e:
                        self.logger.error(
                            f"Error checking {gateway_name} for changes: {e}",
                            exc_info=True
                        )
                        # Continue with next gateway
                        continue
                
                if changes_detected > 0:
                    self.logger.info(
                        f"🔄 Polling: Detected changes in {changes_detected} server(s), "
                        f"created pending versions"
                    )
                    
            except asyncio.CancelledError:
                self.logger.info("Polling task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in polling loop: {e}", exc_info=True)
                # Continue polling despite errors

    async def shutdown(self) -> None:
        """
        Called when the plugin shuts down.
        Stops the background polling task.
        """
        self.logger.info("Shutting down Version Control plugin...")
        
        # Signal shutdown and wait for polling task to finish
        self._shutdown_event.set()
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Version Control plugin shutdown complete")

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """
        Hook called before tool invocation.
        Blocks tool calls if the server has pending changes or is deactivated.
        
        Args:
            payload: Tool invocation payload containing tool_name and arguments
            context: Plugin context with server information (includes server_id as gateway_id)
            
        Returns:
            Result indicating whether to allow or block the tool call
        """
        if not self.enabled:
            # Plugin disabled, allow all calls
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={"version_control_check": "disabled"}
            )
        
        # Extract gateway_id from context.global_context.server_id
        gateway_id = context.global_context.server_id
        if not gateway_id:
            self.logger.warning("No server_id in context, allowing call")
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={"version_control_check": "no_server_id"}
            )
        
        try:
            # Query version control database for current version status
            session = self.db_manager.get_vc_session()
            try:
                result = session.execute(
                    text("""
                        SELECT status, version_number, server_name
                        FROM server_versions
                        WHERE gateway_id = :gateway_id
                          AND is_current = TRUE
                        LIMIT 1
                    """),
                    {"gateway_id": gateway_id}
                )
                row = result.fetchone()
                
                if not row:
                    # No version tracking for this server yet, allow call
                    self.logger.info(f"No version tracking for gateway {gateway_id}, allowing call")
                    return ToolPreInvokeResult(
                        continue_processing=True,
                        metadata={"version_control_check": "not_tracked"}
                    )
                
                status, version_number, server_name = row
                
                # Check status and decide whether to block
                if status == 'active':
                    # Server is active, allow the call
                    return ToolPreInvokeResult(
                        continue_processing=True,
                        metadata={
                            "version_control_check": "passed",
                            "status": status,
                            "version": version_number,
                            "server_name": server_name
                        }
                    )
                
                elif status == 'pending':
                    # Changes detected but not approved, BLOCK the call
                    self.logger.warning(
                        f"Blocking tool call to {server_name}: "
                        f"pending changes detected (version {version_number})"
                    )
                    return ToolPreInvokeResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Pending changes detected",
                            description=(
                                f"Tool call blocked: Server '{server_name}' has pending changes "
                                f"that require approval (version {version_number}). "
                                f"Please review and approve the changes before using this tool."
                            ),
                            code="VERSION_CONTROL_PENDING",
                            details={
                                "gateway_id": gateway_id,
                                "server_name": server_name,
                                "status": status,
                                "version": version_number
                            }
                        )
                    )
                
                elif status == 'deactivated':
                    # Server explicitly deactivated, BLOCK the call
                    self.logger.warning(
                        f"Blocking tool call to {server_name}: "
                        f"server is deactivated (version {version_number})"
                    )
                    return ToolPreInvokeResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Server deactivated",
                            description=(
                                f"Tool call blocked: Server '{server_name}' has been deactivated "
                                f"(version {version_number}). Please contact your administrator."
                            ),
                            code="VERSION_CONTROL_DEACTIVATED",
                            details={
                                "gateway_id": gateway_id,
                                "server_name": server_name,
                                "status": status,
                                "version": version_number
                            }
                        )
                    )
                
                else:
                    # Unknown status, log warning and allow (fail open)
                    self.logger.warning(f"Unknown status '{status}' for gateway {gateway_id}, allowing call")
                    return ToolPreInvokeResult(
                        continue_processing=True,
                        metadata={
                            "version_control_check": "unknown_status",
                            "status": status
                        }
                    )
                    
            finally:
                session.close()
                
        except Exception as e:
            # Error checking version control, log and allow (fail open)
            self.logger.error(f"Error checking version control status: {e}", exc_info=True)
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={"version_control_check": "error", "error": str(e)}
            )

    def get_status(self) -> Dict[str, Any]:
        """
        Get current plugin status (for admin UI).
        """
        return {
            "enabled": self.enabled,
            "database_connected": self.db_manager is not None,
            "polling_active": self._polling_task is not None and not self._polling_task.done(),
            "polling_interval": self.polling_interval,
            "description": "Tracks server versions with continuous polling for new servers"
        }
