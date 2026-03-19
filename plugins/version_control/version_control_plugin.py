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
from typing import Any, Dict, Optional
from datetime import datetime

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig

# Import the core version control logic
from .core.version_control_core import VersionControlCore, VersionControlDB


class VersionControlPlugin(Plugin):
    """
    Plugin that tracks MCP server versions and tool changes.
    
    Features:
    - Automatic server discovery on startup
    - Background polling every 60 seconds
    - Hash-based change detection
    - Complete version history tracking
    """

    def __init__(self, config: PluginConfig):
        """Initialize the Version Control plugin"""
        super().__init__(config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Get configuration
        plugin_config = config.config or {}
        self.enabled = plugin_config.get("enabled", True)
        
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

    async def shutdown(self) -> None:
        """
        Called when the plugin shuts down.
        """
        self.logger.info("Shutting down Version Control plugin...")
        self.logger.info("Version Control plugin shutdown complete")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current plugin status (for admin UI).
        """
        return {
            "enabled": self.enabled,
            "database_connected": self.db_manager is not None,
            "description": "Performs one-time backfill of server versions on startup"
        }

# Made with Bob
