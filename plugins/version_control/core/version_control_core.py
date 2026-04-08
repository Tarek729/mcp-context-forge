# -*- coding: utf-8 -*-
"""
Version Control Core Module - Step 1: Initial Server Discovery

This module handles:
1. Discovery of all existing servers in the gateway
2. Hash computation for version tracking (tools only in MVP)
3. Initial version record creation in separate database

Author: Version Control Plugin Team
Date: 2026-03-19
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, select, Column, String, Integer, Boolean, DateTime, Text, text
from sqlalchemy.orm import declarative_base, Session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError

# For MCP initialize handshake
import httpx
import asyncio

# Configure logging
logger = logging.getLogger(__name__)

# SQLAlchemy Base for Version Control DB
Base = declarative_base()


# ============================================================================
# DATABASE MODELS
# ============================================================================

class ServerVersion(Base):
    """
    Server version tracking table in mcp_version_control database.

    Tracks version history for each gateway with hash-based change detection.
    """
    __tablename__ = "server_versions"

    # Primary Key
    id = Column(String(36), primary_key=True)

    # Gateway Reference (validated in code, not FK since cross-database)
    gateway_id = Column(String(36), nullable=False, index=True)

    # Server Identity
    server_name = Column(String(255), nullable=False)
    server_version = Column(String(50), nullable=False)

    # Version Tracking
    version_number = Column(Integer, nullable=False)

    # Hash Tracking (MVP: tools only)
    tools_hash = Column(String(64), nullable=False)
    version_hash = Column(String(64), nullable=False, index=True)

    # Metadata
    tools_count = Column(Integer, nullable=False)
    is_current = Column(Boolean, nullable=False, default=False, index=True)
    status = Column(String(20), nullable=False, default='active', index=True)

    # Audit Fields
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = Column(String(255), nullable=False)

    def __repr__(self):
        return (
            f"<ServerVersion(id={self.id}, gateway_id={self.gateway_id}, "
            f"version={self.version_number}, current={self.is_current})>"
        )


# ============================================================================
# HASH COMPUTATION
# ============================================================================

class HashComputer:
    """
    Computes cryptographic hashes for version tracking.

    Uses SHA256 for consistent, collision-resistant hashing.
    """

    @staticmethod
    def compute_tools_hash(tools: List[Dict[str, Any]]) -> str:
        """
        Compute SHA256 hash of tools list.

        Args:
            tools: List of tool dictionaries with 'name' and 'input_schema'

        Returns:
            64-character hex string (SHA256 hash)

        Example:
            >>> tools = [
            ...     {"name": "add", "input_schema": {"type": "object"}},
            ...     {"name": "multiply", "input_schema": {"type": "object"}}
            ... ]
            >>> hash_val = HashComputer.compute_tools_hash(tools)
            >>> len(hash_val)
            64
        """
        # Sort tools by name for consistent hashing
        sorted_tools = sorted(tools, key=lambda t: t.get('name', ''))

        # Create canonical JSON representation
        # Use sort_keys=True for deterministic output
        tools_json = json.dumps(sorted_tools, sort_keys=True, separators=(',', ':'))

        # Compute SHA256 hash
        hash_obj = hashlib.sha256(tools_json.encode('utf-8'))
        return hash_obj.hexdigest()

    @staticmethod
    def compute_version_hash(server_version: str, tools_hash: str) -> str:
        """
        Compute combined version hash.

        Combines server version string with tools hash for comprehensive
        change detection.

        Args:
            server_version: Server version string (e.g., "0.1.0")
            tools_hash: SHA256 hash of tools list

        Returns:
            64-character hex string (SHA256 hash)

        Example:
            >>> version_hash = HashComputer.compute_version_hash(
            ...     "0.1.0",
            ...     "a" * 64
            ... )
            >>> len(version_hash)
            64
        """
        combined = f"{server_version}:{tools_hash}"
        hash_obj = hashlib.sha256(combined.encode('utf-8'))
        return hash_obj.hexdigest()


# ============================================================================
# DATABASE MANAGER
# ============================================================================

class VersionControlDB:
    """
    Manages connections to the version control database.

    Handles both the main MCP database (read-only) and the version control
    database (read-write).
    """

    def __init__(
        self,
        main_db_url: str,
        vc_db_url: str,
        echo: bool = False
    ):
        """
        Initialize database connections.

        Args:
            main_db_url: Connection string for main MCP database
            vc_db_url: Connection string for version control database
            echo: Whether to echo SQL statements (for debugging)
        """
        # Store URLs for later use
        self.main_db_url = main_db_url
        self.vc_db_url = vc_db_url
        self.echo = echo

        # Main database connection (read-only for gateway/tool queries)
        self.main_engine = create_engine(main_db_url, echo=echo)
        self.MainSession = sessionmaker(bind=self.main_engine)

        # Version control database - will be created after ensuring DB exists
        self.vc_engine = None
        self.VCSession = None

        logger.info(f"Initialized VersionControlDB")
        logger.info(f"Main DB: {main_db_url}")
        logger.info(f"VC DB: {vc_db_url}")

    def create_database_if_not_exists(self):
        """
        Create the version control database if it doesn't exist.

        This connects to the 'postgres' database to create the target database.
        Requires the vc_db_url to be parseable to extract database name.
        """
        try:
            # Parse the vc_db_url to extract database name and connection params
            from urllib.parse import urlparse
            parsed = urlparse(self.vc_db_url)
            db_name = parsed.path.lstrip('/')

            # Create connection URL to 'postgres' database (without specific db)
            postgres_url = f"{parsed.scheme}://{parsed.netloc}/postgres"

            # Connect to postgres database to create our target database
            postgres_engine = create_engine(postgres_url)

            # Check if database exists
            with postgres_engine.connect() as conn:
                # Use isolation_level for CREATE DATABASE
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")

                # Check if database exists
                result = conn.execute(
                    text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
                )
                exists = result.fetchone() is not None

                if not exists:
                    logger.info(f"Creating database '{db_name}'...")
                    conn.execute(text(f"CREATE DATABASE {db_name}"))
                    logger.info(f"✅ Database '{db_name}' created successfully")
                else:
                    logger.info(f"Database '{db_name}' already exists")

            postgres_engine.dispose()

            # Now create the vc_engine connection since database exists
            if self.vc_engine is None:
                self.vc_engine = create_engine(self.vc_db_url, echo=self.echo)
                self.VCSession = sessionmaker(bind=self.vc_engine)
                logger.info("Version control database engine created")

        except Exception as e:
            logger.error(f"Could not auto-create database: {e}")
            raise

    def create_tables(self):
        """
        Create version control tables if they don't exist.

        This is idempotent - safe to call multiple times.
        """
        try:
            Base.metadata.create_all(self.vc_engine)
            logger.info("Version control tables created/verified")
        except SQLAlchemyError as e:
            logger.error(f"Failed to create tables: {e}")
            raise

    def get_main_session(self) -> Session:
        """Get a session for the main database."""
        return self.MainSession()

    def get_vc_session(self) -> Session:
        """Get a session for the version control database."""
        return self.VCSession()


# ============================================================================
# MCP INITIALIZE HANDSHAKE - STANDALONE IMPLEMENTATION
# ============================================================================
#
# This is a standalone implementation that doesn't depend on GatewayService
# or any MCP SDK modules. It implements the MCP protocol directly using httpx.
#

async def perform_mcp_initialize(
    url: str,
    transport: str = "STREAMABLEHTTP",
    authentication: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Perform MCP initialize handshake with a server to get serverInfo.

    Implements the MCP protocol directly without SDK dependencies.
    Handles both SSE and STREAMABLEHTTP transports.

    Args:
        url: Server URL (e.g., "http://localhost:9100/mcp" or "http://localhost:9001/sse")
        transport: Transport type (STREAMABLEHTTP, SSE, etc.)
        authentication: Optional authentication headers (dict)

    Returns:
        Dictionary with 'name', 'version', and optionally 'session_id' from serverInfo
    """
    try:
        # MCP initialize request (JSON-RPC 2.0 format)
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "version-control-plugin",
                    "version": "1.0.0"
                }
            }
        }

        logger.debug(f"Performing MCP initialize to {url} (transport: {transport})")

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Handle SSE transport differently
            if transport.upper() == "SSE":
                # SSE: Connect and keep the stream open to receive responses
                headers = {"Accept": "text/event-stream"}
                if authentication:
                    headers.update(authentication)

                result = None
                message_endpoint = None

                # Connect to SSE endpoint with streaming
                async with client.stream("GET", url, headers=headers, timeout=30.0) as response:
                    response.raise_for_status()

                    # Read SSE events to get the endpoint first
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:].strip()
                            # Look for endpoint in the data
                            if data.startswith("http") and not message_endpoint:
                                message_endpoint = data
                                logger.info(f"Got SSE message endpoint: {message_endpoint}")

                                # Now POST the initialize request to the message endpoint
                                headers_post = {"Content-Type": "application/json"}
                                if authentication:
                                    headers_post.update(authentication)

                                # POST returns 202 Accepted, response comes via this SSE stream
                                post_response = await client.post(message_endpoint, json=initialize_request, headers=headers_post)
                                post_response.raise_for_status()
                                logger.info(f"Posted initialize request, waiting for response on SSE stream...")
                                continue

                            # Try to parse as JSON response
                            if message_endpoint:  # Only after we've sent the request
                                try:
                                    json_data = json.loads(data)
                                    # Check if this is the initialize response
                                    if json_data.get('id') == 1 and 'result' in json_data:
                                        result = json_data
                                        logger.info(f"Got initialize response via SSE")
                                        break
                                except json.JSONDecodeError:
                                    continue

                if not result:
                    logger.warning(f"No response received from SSE endpoint {url}")
                    return None

            else:
                # STREAMABLEHTTP: Direct POST with both content types
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
                if authentication:
                    headers.update(authentication)

                response = await client.post(url, json=initialize_request, headers=headers)
                response.raise_for_status()

                # Capture session ID from response headers (for STREAMABLEHTTP)
                session_id = response.headers.get('mcp-session-id')
                if session_id:
                    logger.info(f"✓ Got session ID from initialize: {session_id}")
                else:
                    logger.warning(f"⚠️ No session ID in initialize response headers: {list(response.headers.keys())}")

                # Parse response (might be SSE format)
                response_text = response.text
                if "data: " in response_text:
                    # SSE format: "event: message\ndata: {json}\n\n"
                    json_start = response_text.find("data: ") + 6
                    json_end = response_text.find("\n", json_start)
                    if json_end == -1:
                        json_end = len(response_text)
                    json_str = response_text[json_start:json_end].strip()
                    result = json.loads(json_str)
                else:
                    result = response.json()

                # Extract serverInfo and add session_id if present
                if 'result' in result and 'serverInfo' in result['result']:
                    server_info = result['result']['serverInfo']
                    logger.debug(f"Got serverInfo: {server_info}")
                    server_data = {
                        'name': server_info.get('name', 'unknown'),
                        'version': server_info.get('version', 'unknown')
                    }
                    # Add session ID if present (for STREAMABLEHTTP)
                    if session_id:
                        server_data['session_id'] = session_id
                    return server_data
                else:
                    logger.warning(f"No serverInfo in initialize response from {url}")
                    return None

            # Extract serverInfo from JSON-RPC response (for SSE path)
            if 'result' in result and 'serverInfo' in result['result']:
                server_info = result['result']['serverInfo']
                logger.debug(f"Got serverInfo: {server_info}")
                server_data = {
                    'name': server_info.get('name', 'unknown'),
                    'version': server_info.get('version', 'unknown')
                }
                return server_data
            else:
                logger.warning(f"No serverInfo in initialize response from {url}")
                return None

    except Exception as e:
        logger.error(f"Failed to perform MCP initialize to {url}: {e}")
        return None


async def perform_mcp_tools_list(
    url: str,
    transport: str = "STREAMABLEHTTP",
    authentication: Optional[Dict[str, str]] = None,
    session_id: Optional[str] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    Call tools/list endpoint on MCP server to get current tools.

    Args:
        url: Server URL (e.g., "http://localhost:9100/mcp")
        transport: Transport type (STREAMABLEHTTP, SSE, etc.)
        authentication: Optional authentication headers
        session_id: Optional session ID (required for STREAMABLEHTTP)

    Returns:
        List of tool dictionaries from server, or None if failed
    """
    try:
        logger.debug(f"Calling tools/list on {url} (transport: {transport})")

        # MCP tools/list request (JSON-RPC 2.0 format)
        tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }

        async with httpx.AsyncClient(timeout=10.0) as client:

            # Handle SSE transport
            if transport.upper() == "SSE":
                headers = {"Accept": "text/event-stream"}
                if authentication:
                    headers.update(authentication)

                result = None
                message_endpoint = None

                # Connect to SSE endpoint
                async with client.stream("GET", url, headers=headers, timeout=30.0) as response:
                    response.raise_for_status()

                    # Get message endpoint and send request
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:].strip()

                            if data.startswith("http") and not message_endpoint:
                                message_endpoint = data
                                logger.debug(f"Got SSE message endpoint: {message_endpoint}")

                                # POST tools/list request
                                headers_post = {"Content-Type": "application/json"}
                                if authentication:
                                    headers_post.update(authentication)

                                post_response = await client.post(message_endpoint, json=tools_request, headers=headers_post)
                                post_response.raise_for_status()
                                logger.debug(f"Posted tools/list request, waiting for response...")
                                continue

                            # Parse JSON response
                            if message_endpoint:
                                try:
                                    json_data = json.loads(data)
                                    if json_data.get('id') == 2 and 'result' in json_data:
                                        result = json_data
                                        logger.debug(f"Got tools/list response via SSE")
                                        break
                                except json.JSONDecodeError:
                                    continue

                if not result:
                    logger.warning(f"No tools/list response from SSE endpoint {url}")
                    return None

            else:
                # STREAMABLEHTTP: Direct POST
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
                if authentication:
                    headers.update(authentication)

                # Add session ID if provided (required for STREAMABLEHTTP)
                if session_id:
                    headers['mcp-session-id'] = session_id
                    logger.info(f"✓ Using session ID for tools/list: {session_id}")
                else:
                    logger.warning(f"⚠️ No session ID provided for STREAMABLEHTTP tools/list request")

                response = await client.post(url, json=tools_request, headers=headers)
                response.raise_for_status()

                # Handle SSE-formatted response
                response_text = response.text
                logger.info(f"📝 tools/list response text (first 500 chars): {response_text[:500]}")
                logger.info(f"📋 tools/list Content-Type: {response.headers.get('content-type')}")

                if not response_text or response_text.strip() == "":
                    logger.error(f"❌ Empty response from tools/list endpoint")
                    return None

                # Parse SSE format: "event: message\ndata: {json}\n\n"
                if "event: message" in response_text and "data: " in response_text:
                    # Extract JSON from SSE format
                    lines = response_text.split('\n')
                    for line in lines:
                        if line.startswith("data: "):
                            json_str = line[6:].strip()
                            if json_str:
                                result = json.loads(json_str)
                                break
                    else:
                        logger.error(f"Could not find data line in SSE response")
                        return None
                elif response_text.startswith("data: "):
                    json_str = response_text[6:].strip()
                    result = json.loads(json_str)
                else:
                    result = response.json()

            # Extract tools from result
            if result and 'result' in result and 'tools' in result['result']:
                tools = result['result']['tools']
                logger.info(f"Got {len(tools)} tools from server")
                return tools
            else:
                logger.warning(f"Unexpected tools/list response format: {result}")
                return None

    except httpx.HTTPError as e:
        logger.error(f"Failed to call tools/list on {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error calling tools/list on {url}: {e}")
        return None


# ============================================================================
# CORE VERSION CONTROL LOGIC - STEP 1
# ============================================================================

class VersionControlCore:
    """
    Core version control functionality.

    Step 1: Initial server discovery and version tracking setup.
    """

    def __init__(self, db_manager: VersionControlDB):
        """
        Initialize version control core.

        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager
        self.hash_computer = HashComputer()
        logger.info("VersionControlCore initialized")

    def discover_existing_servers(self) -> List[Dict[str, Any]]:
        """
        Step 1.1: Discover all existing servers in the gateway.

        Queries the main database to find all registered gateways.

        Returns:
            List of gateway dictionaries with id, name, url, etc.
        """
        logger.info("Starting server discovery...")

        with self.db.get_main_session() as session:
            try:
                # Query all gateways from main database
                # Note: Using raw SQL since we don't have the main DB models imported
                result = session.execute(
                    text("""
                        SELECT id, name, url, enabled, transport,
                               auth_type, created_at
                        FROM gateways
                        ORDER BY created_at
                    """)
                )

                gateways = []
                for row in result:
                    gateway = {
                        'id': row[0],
                        'name': row[1],
                        'url': row[2],
                        'enabled': row[3],
                        'transport': row[4],
                        'auth_type': row[5],
                        'created_at': row[6]
                    }
                    gateways.append(gateway)

                logger.info(f"Discovered {len(gateways)} existing servers")
                return gateways

            except SQLAlchemyError as e:
                logger.error(f"Failed to discover servers: {e}")
                raise

    def get_gateway_tools(self, gateway_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all tools for a specific gateway.

        Args:
            gateway_id: Gateway UUID

        Returns:
            List of tool dictionaries with name and input_schema
        """
        with self.db.get_main_session() as session:
            try:
                result = session.execute(
                    text("""
                        SELECT id, name, original_name, input_schema, description
                        FROM tools
                        WHERE gateway_id = :gateway_id
                        ORDER BY name
                    """),
                    {'gateway_id': gateway_id}
                )

                tools = []
                for row in result:
                    tool = {
                        'id': row[0],
                        'name': row[1],
                        'original_name': row[2],
                        'input_schema': row[3],  # This is JSONB in PostgreSQL
                        'description': row[4]
                    }
                    tools.append(tool)

                logger.debug(f"Found {len(tools)} tools for gateway {gateway_id}")
                return tools

            except SQLAlchemyError as e:
                logger.error(f"Failed to fetch tools for gateway {gateway_id}: {e}")
                raise

    async def get_server_info(self, gateway_id: str) -> Optional[Dict[str, str]]:
        """
        Get server name and version by performing MCP initialize handshake.

        Args:
            gateway_id: Gateway UUID

        Returns:
            Dictionary with 'name' and 'version', or None if not found
        """
        with self.db.get_main_session() as session:
            try:
                result = session.execute(
                    text("""
                        SELECT name, url, transport, auth_value, auth_type,
                               oauth_config, ca_certificate
                        FROM gateways
                        WHERE id = :gateway_id
                    """),
                    {'gateway_id': gateway_id}
                )

                row = result.fetchone()
                if not row:
                    return None

                gateway_name = row[0]
                gateway_url = row[1]
                transport = row[2]
                auth_value = row[3]  # JSONB field (authentication headers/credentials)
                auth_type = row[4]
                oauth_config = row[5]  # JSONB field
                ca_certificate = row[6]  # TEXT field

                # Perform MCP initialize to get real serverInfo
                logger.info(f"Fetching server info from {gateway_url}...")

                # Use standalone MCP initialize (no SDK dependencies)
                server_info = await perform_mcp_initialize(
                    url=gateway_url,
                    transport=transport,
                    authentication=auth_value  # auth_value contains the headers/credentials
                )

                if server_info:
                    logger.info(f"Got server info: {server_info['name']} v{server_info['version']}")
                    return server_info
                else:
                    # Fallback to gateway name if initialize fails
                    logger.warning(f"Could not get server info, using gateway name as fallback")
                    return {
                        'name': gateway_name,
                        'version': 'unknown'
                    }

            except SQLAlchemyError as e:
                logger.error(f"Failed to get server info for gateway {gateway_id}: {e}")
                return None

    async def compute_hashes_for_gateway(
        self,
        gateway_id: str,
        server_info: Optional[Dict[str, str]] = None
    ) -> Tuple[str, str, int]:
        """
        Step 1.2: Compute hashes for a gateway by calling live MCP server.

        Args:
            gateway_id: Gateway UUID
            server_info: Optional pre-fetched server info (to avoid duplicate calls)

        Returns:
            Tuple of (tools_hash, version_hash, tools_count)
        """
        # Get gateway details from database
        with self.db.get_main_session() as session:
            result = session.execute(
                text("""
                    SELECT url, transport, auth_value
                    FROM gateways
                    WHERE id = :gateway_id
                """),
                {'gateway_id': gateway_id}
            )
            row = result.fetchone()
            if not row:
                raise ValueError(f"Gateway not found: {gateway_id}")

            url, transport, auth_value = row[0], row[1], row[2]

        # Get server info if not provided
        if not server_info:
            server_info = await perform_mcp_initialize(
                url=url,
                transport=transport,
                authentication=auth_value
            )
            if not server_info:
                raise ValueError(f"Could not get server info from {url}")

        # Get tools from live MCP server
        # Pass session_id if present (required for STREAMABLEHTTP)
        tools = await perform_mcp_tools_list(
            url=url,
            transport=transport,
            authentication=auth_value,
            session_id=server_info.get('session_id')
        )
        if tools is None:
            raise ValueError(f"Could not get tools list from {url}")

        # Compute tools hash
        tools_hash = self.hash_computer.compute_tools_hash(tools)

        # Compute version hash
        version_hash = self.hash_computer.compute_version_hash(
            server_info['version'],
            tools_hash
        )

        logger.debug(
            f"Computed hashes for gateway {gateway_id}: "
            f"tools_hash={tools_hash[:16]}..., "
            f"version_hash={version_hash[:16]}..."
        )

        return tools_hash, version_hash, len(tools)

    async def create_initial_version(
        self,
        gateway_id: str,
        created_by: str = "system"
    ) -> ServerVersion:
        """
        Create initial version record (version 1) for a gateway.

        Args:
            gateway_id: Gateway UUID
            created_by: Email of user creating the version

        Returns:
            Created ServerVersion instance
        """
        # Get server info
        server_info = await self.get_server_info(gateway_id)
        if not server_info:
            raise ValueError(f"Server info not found for gateway {gateway_id}")

        # Compute hashes from live MCP server (pass server_info to avoid duplicate call)
        tools_hash, version_hash, tools_count = await self.compute_hashes_for_gateway(
            gateway_id,
            server_info=server_info
        )

        # Create version record
        version = ServerVersion(
            id=str(uuid.uuid4()),
            gateway_id=gateway_id,
            server_name=server_info['name'],
            server_version=server_info['version'],
            version_number=1,
            tools_hash=tools_hash,
            version_hash=version_hash,
            tools_count=tools_count,
            is_current=True,
            status='active',
            created_by=created_by
        )

        # Save to database
        with self.db.get_vc_session() as session:
            try:
                session.add(version)
                session.commit()
                # Refresh to ensure all attributes are loaded
                session.refresh(version)
                logger.info(
                    f"Created initial version for gateway {gateway_id}: "
                    f"v1, {tools_count} tools"
                )
                # Make version object detached but with all attributes loaded
                session.expunge(version)
                return version
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"Failed to create initial version: {e}")
                raise

    async def check_for_changes(self, gateway_id: str) -> bool:
        """
        Check if a gateway's tools have changed since the last version.

        Compares current server state with the latest version record to detect changes.

        Args:
            gateway_id: Gateway UUID

        Returns:
            True if changes detected, False if unchanged
        """
        try:
            # Get the latest version record for this gateway
            with self.db.get_vc_session() as session:
                result = session.execute(
                    select(ServerVersion)
                    .where(ServerVersion.gateway_id == gateway_id)
                    .order_by(ServerVersion.version_number.desc())
                    .limit(1)
                )
                latest_version = result.scalar_one_or_none()

                if not latest_version:
                    # No version record exists - this shouldn't happen in normal flow
                    logger.warning(f"No version record found for gateway {gateway_id}")
                    return False

                # Store the latest hash for comparison
                latest_hash = latest_version.version_hash
                latest_version_number = latest_version.version_number

            # Get current server info and compute current hash
            server_info = await self.get_server_info(gateway_id)
            if not server_info:
                logger.warning(f"Could not get server info for gateway {gateway_id}")
                return False

            # Compute current hashes from live MCP server
            _current_tools_hash, current_version_hash, current_tools_count = await self.compute_hashes_for_gateway(
                gateway_id,
                server_info=server_info
            )

            # Compare hashes
            if current_version_hash != latest_hash:
                logger.info(
                    f"🔍 Changes detected for gateway {gateway_id}:\n"
                    f"  Latest version: {latest_version_number}\n"
                    f"  Latest hash: {latest_hash[:16]}...\n"
                    f"  Current hash: {current_version_hash[:16]}...\n"
                    f"  Tools count: {current_tools_count}"
                )
                return True
            else:
                logger.info(f"No changes detected for gateway {gateway_id} (version {latest_version_number})")
                logger.debug(f"No changes detected for gateway {gateway_id} (version {latest_version_number})")
                return False

        except Exception as e:
            logger.error(f"Error checking for changes in gateway {gateway_id}: {e}", exc_info=True)
            return False

    async def create_pending_version(
        self,
        gateway_id: str,
        created_by: str = "system"
    ) -> Optional[ServerVersion]:
        """
        Create a new pending version record when changes are detected.

        This is a helper method called by the polling loop when check_for_changes()
        returns True. The new version will have status='pending' and is_current=True,
        immediately blocking tool calls until an admin reviews and approves it.

        Args:
            gateway_id: Gateway UUID
            created_by: Email of user/system creating the version

        Returns:
            Created ServerVersion instance, or None if failed
        """
        try:
            # Get the latest version number
            with self.db.get_vc_session() as session:
                result = session.execute(
                    select(ServerVersion)
                    .where(ServerVersion.gateway_id == gateway_id)
                    .order_by(ServerVersion.version_number.desc())
                    .limit(1)
                )
                latest_version = result.scalar_one_or_none()

                if not latest_version:
                    logger.error(f"Cannot create pending version: no existing version found for gateway {gateway_id}")
                    return None

                next_version_number = latest_version.version_number + 1

            # Get current server info and compute hashes
            server_info = await self.get_server_info(gateway_id)
            if not server_info:
                logger.error(f"Cannot create pending version: could not get server info for gateway {gateway_id}")
                return None

            # Compute current hashes from live MCP server
            tools_hash, version_hash, tools_count = await self.compute_hashes_for_gateway(
                gateway_id,
                server_info=server_info
            )

            # Create pending version record
            version = ServerVersion(
                id=str(uuid.uuid4()),
                gateway_id=gateway_id,
                server_name=server_info['name'],
                server_version=server_info['version'],
                version_number=next_version_number,
                tools_hash=tools_hash,
                version_hash=version_hash,
                tools_count=tools_count,
                is_current=True,  # Make pending version current to block tool calls
                status='pending',  # Pending review
                created_by=created_by
            )

            # Save to database
            with self.db.get_vc_session() as session:
                try:
                    # First, mark old version as not current AND deactivate it
                    # When a new pending version is created, the old version should be deactivated
                    session.execute(
                        text("""
                            UPDATE server_versions
                            SET is_current = FALSE, status = 'deactivated'
                            WHERE gateway_id = :gw AND is_current = TRUE
                        """),
                        {"gw": gateway_id}
                    )

                    # Then add the new pending version as current
                    session.add(version)
                    session.commit()
                    session.refresh(version)

                    logger.info(
                        f"✅ Created pending version {next_version_number} for gateway {gateway_id}: "
                        f"{tools_count} tools, hash={version_hash[:16]}... (old version deactivated)"
                    )

                    # Make version object detached but with all attributes loaded
                    session.expunge(version)
                    return version

                except SQLAlchemyError as e:
                    session.rollback()
                    logger.error(f"Failed to create pending version: {e}")
                    return None

        except Exception as e:
            logger.error(f"Error creating pending version for gateway {gateway_id}: {e}", exc_info=True)
            return None

    async def backfill_existing_servers(self, created_by: str = "system") -> int:
        """
        Step 1: Backfill version records for all existing servers.

        This is the main entry point for Step 1. It discovers all existing
        servers and creates initial version records for them.

        Args:
            created_by: Email of user performing backfill

        Returns:
            Number of servers backfilled
        """
        logger.info("=" * 60)
        logger.info("STEP 1: BACKFILLING EXISTING SERVERS")
        logger.info("=" * 60)

        # Discover existing servers
        gateways = self.discover_existing_servers()

        if not gateways:
            logger.info("No existing servers found. Nothing to backfill.")
            return 0

        # Process each gateway
        backfilled_count = 0
        for gateway in gateways:
            gateway_id = gateway['id']
            gateway_name = gateway['name']

            try:
                # Check if version already exists
                with self.db.get_vc_session() as session:
                    existing = session.execute(
                        select(ServerVersion).where(
                            ServerVersion.gateway_id == gateway_id
                        )
                    ).first()

                    if existing:
                        logger.info(
                            f"Skipping {gateway_name} ({gateway_id}): "
                            f"version already exists"
                        )
                        continue

                # Create initial version
                logger.info(f"Processing {gateway_name} ({gateway_id})...")
                version = await self.create_initial_version(gateway_id, created_by)

                logger.info(
                    f"✓ Created version 1 for {gateway_name}: "
                    f"{version.tools_count} tools, "
                    f"hash={version.version_hash[:16]}..."
                )

                backfilled_count += 1

            except Exception as e:
                logger.error(
                    f"✗ Failed to backfill {gateway_name} ({gateway_id}): {e}"
                )
                # Continue with next gateway
                continue

        logger.info("=" * 60)
        logger.info(f"BACKFILL COMPLETE: {backfilled_count}/{len(gateways)} servers")
        logger.info("=" * 60)

        return backfilled_count

    def list_blocked_versions(self) -> Tuple[List[ServerVersion], int]:
        """
        List all blocked versions (pending or deactivated status).

        This is a convenience method that returns versions requiring
        administrator attention or approval.

        Returns:
            Tuple of (list of ServerVersion objects, total count)
        """
        with self.db.get_vc_session() as session:
            try:
                # Query for blocked versions
                query = select(ServerVersion).where(
                    ServerVersion.status.in_(['pending', 'deactivated'])
                ).order_by(
                    ServerVersion.created_at.desc(),
                    ServerVersion.version_number.desc()
                )

                # Execute query
                result = session.execute(query)
                versions = result.scalars().all()

                # Detach objects from session
                for version in versions:
                    session.expunge(version)

                total = len(versions)

                logger.info(f"Listed {total} blocked version(s)")

                return versions, total

            except SQLAlchemyError as e:
                logger.error(f"Failed to list blocked versions: {e}")
                raise

    def update_version_status(
        self,
        version_id: str,
        new_status: str,
        updated_by: str = "system"
    ) -> Optional[ServerVersion]:
        """
        Update the status of a server version.

        This method allows administrators to:
        - Approve pending versions (set status to 'active')
        - Reject pending versions (set status to 'deactivated')
        - Deactivate active versions (set status to 'deactivated')

        Args:
            version_id: Version UUID to update
            new_status: New status value (active, pending, or deactivated)
            updated_by: Email of user performing the update

        Returns:
            Updated ServerVersion object or None if not found

        Raises:
            ValueError: If new_status is invalid
        """
        # Validate status
        valid_statuses = ['active', 'pending', 'deactivated']
        if new_status not in valid_statuses:
            raise ValueError(
                f"Invalid status '{new_status}'. Must be one of: {', '.join(valid_statuses)}"
            )

        with self.db.get_vc_session() as session:
            try:
                # Get the version
                result = session.execute(
                    select(ServerVersion).where(ServerVersion.id == version_id)
                )
                version = result.scalar_one_or_none()

                if not version:
                    logger.warning(f"Version {version_id} not found for status update")
                    return None

                old_status = version.status
                server_name = version.server_name
                gateway_id = version.gateway_id
                version_number = version.version_number

                # Update status
                version.status = new_status

                # If approving a version (setting to 'active'), delete older deactivated versions
                # for the same server in the same transaction
                deleted_count = 0
                if new_status == 'active':
                    # Find and delete older deactivated versions for this server
                    delete_query = select(ServerVersion).where(
                        ServerVersion.gateway_id == gateway_id,
                        ServerVersion.status == 'deactivated',
                        ServerVersion.version_number < version_number
                    )
                    old_versions = session.execute(delete_query).scalars().all()

                    for old_version in old_versions:
                        logger.info(
                            f"Deleting old deactivated version: {server_name} "
                            f"v{old_version.version_number} (id: {old_version.id})"
                        )
                        session.delete(old_version)
                        deleted_count += 1

                # Single commit for both status update and cleanup
                session.commit()
                session.refresh(version)

                logger.info(
                    f"Updated version {version_id} status: {old_status} → {new_status} "
                    f"(by {updated_by})"
                )

                if deleted_count > 0:
                    logger.info(
                        f"Deleted {deleted_count} old deactivated version(s) for {server_name}"
                    )

                # Detach from session
                session.expunge(version)
                return version

            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"Failed to update version status: {e}")
                raise

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

def main():
    """
    Example usage of Step 1: Initial server discovery and backfill.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Database connection strings
    # NOTE: Update these with your actual database URLs
    MAIN_DB_URL = "postgresql://postgres:password@localhost:5433/mcp"
    VC_DB_URL = "postgresql://postgres:password@localhost:5433/mcp_version_control"

    try:
        # Initialize database manager
        logger.info("Initializing database connections...")
        db_manager = VersionControlDB(MAIN_DB_URL, VC_DB_URL)

        # Create tables if they don't exist
        logger.info("Creating version control tables...")
        db_manager.create_tables()

        # Initialize version control core
        logger.info("Initializing version control core...")
        vc_core = VersionControlCore(db_manager)

        # Run Step 1: Backfill existing servers
        backfilled = vc_core.backfill_existing_servers(created_by="admin@example.com")

        logger.info(f"\n✓ Step 1 complete! Backfilled {backfilled} servers.")

    except Exception as e:
        logger.error(f"Error during Step 1 execution: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())

# Made with Bob
