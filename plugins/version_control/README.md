# 🔄 Version Control Plugin for ContextForge

Automatically tracks MCP server versions and detects tool changes over time.

## 📋 Overview

This plugin monitors all registered MCP servers and maintains a complete version history:
- **Automatic Discovery**: Finds all servers on startup
- **Change Detection**: Uses SHA256 hashing to detect tool modifications
- **Background Polling**: Checks for changes every 60 seconds (configurable)
- **Separate Database**: Isolated `mcp_version_control` database
- **Session Management**: Properly handles STREAMABLEHTTP session IDs

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ContextForge Gateway                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Version Control Plugin                         │ │
│  │  ┌──────────────┐         ┌──────────────┐             │ │
│  │  │   Startup    │────────▶│  Background  │             │ │
│  │  │   Backfill   │         │   Polling    │             │ │
│  │  └──────────────┘         └──────┬───────┘             │ │
│  │         │                        │                     │ │
│  │         └─────────┬──────────────┘                     │ │
│  │                   ▼                                    │ │
│  │         ┌──────────────────┐                           │ │
│  │         │ Version Control  │                           │ │
│  │         │      Core        │                           │ │
│  │         └────────┬─────────┘                           │ │
│  └──────────────────┼─────────────────────────────────────┘ │
│                     │                                       │
│         ┌───────────┼───────────┐                           │
│         ▼           ▼           ▼                           │
│    ┌────────┐  ┌────────┐  ┌────────┐                       │
│    │  MCP   │  │  MCP   │  │  MCP   │                       │
│    │Server 1│  │Server 2│  │Server 3│                       │
│    └────────┘  └────────┘  └────────┘                       │
└─────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
    ┌─────────────────────────────────────┐
    │   mcp_version_control Database      │
    │  ┌─────────────────────────────┐    │
    │  │    server_versions table    │    │
    │  │  - gateway_id               │    │
    │  │  - server_name              │    │
    │  │  - server_version           │    │
    │  │  - version_number           │    │
    │  │  - tools_hash (SHA256)      │    │
    │  │  - version_hash (SHA256)    │    │
    │  │  - tools_count              │    │
    │  │  - is_current               │    │
    │  │  - created_at               │    │
    │  └─────────────────────────────┘    │
    └─────────────────────────────────────┘
```

## 🚀 Installation

### Step 1: Copy Plugin Files

The plugin is already in the correct location:
```
mcp-context-forge/plugins/version_control/
├── __init__.py
├── version_control_plugin.py
├── plugin-manifest.yaml
├── README.md
└── core/
    ├── __init__.py
    └── version_control_core.py
```

### Step 2: Create Version Control Database

```bash
# Using Docker (if PostgreSQL is in Docker)
docker exec mcp-postgres psql -U postgres -c "CREATE DATABASE mcp_version_control;"

# Or using psql directly
psql -h localhost -p 5433 -U postgres -c "CREATE DATABASE mcp_version_control;"
```

### Step 3: Configure Plugin

Edit `plugins/config.yaml` and add:

```yaml
plugins:
  - name: "VersionControl"
    kind: "plugins.version_control.version_control_plugin.VersionControlPlugin"
    hooks:
      - "tool_pre_invoke"
      - "on_startup"
      - "on_shutdown"
    mode: "permissive"  # Doesn't block requests
    priority: 100
    config:
      enabled: true
      poll_interval_seconds: 60
      main_db_url: "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp"
      vc_db_url: "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp_version_control"
```

### Step 4: Enable Plugins

Edit `.env` file:

```bash
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

### Step 5: Restart ContextForge

```bash
# Stop current instance
docker-compose down

# Start with plugins enabled
docker-compose up -d
```

## 📊 Database Schema

### `server_versions` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) | Primary key (UUID) |
| `gateway_id` | VARCHAR(36) | Foreign key to gateways table |
| `server_name` | VARCHAR(255) | MCP server name |
| `server_version` | VARCHAR(50) | Server version string |
| `version_number` | INTEGER | Sequential version number (1, 2, 3...) |
| `tools_hash` | VARCHAR(64) | SHA256 hash of tools list |
| `version_hash` | VARCHAR(64) | Combined hash (tools + version) |
| `tools_count` | INTEGER | Number of tools |
| `is_current` | BOOLEAN | True for latest version |
| `status` | VARCHAR(20) | Version status: 'active', 'pending', or 'deactivated' |
| `created_at` | TIMESTAMP | When version was detected |
| `created_by` | VARCHAR(255) | Who created (plugin/system) |

## 🔍 How It Works

### 1. Initial Backfill (on_startup)
```python
# Plugin starts up
→ Discovers all registered MCP servers
→ Calls initialize handshake to get server info
→ Calls tools/list to get current tools
→ Computes SHA256 hashes
→ Creates version 1 for each server
```

### 2. Background Polling (every 60s)
```python
# Every poll interval
→ For each server:
  → Call tools/list endpoint
  → Compute new hash
  → Compare with current hash
  → If different:
    → Mark old version as not current
    → Create new version entry
    → Log the change
```

### 3. Hash Computation
```python
tools_hash = SHA256(sorted_tools_json)
version_hash = SHA256(tools_hash + server_version)
```

### 4. Session Management (STREAMABLEHTTP)
```python
# Initialize handshake
→ Capture mcp-session-id from response headers
→ Store session ID

# Subsequent requests (tools/list)
→ Include mcp-session-id in request headers
→ Server validates session
```

## 🧪 Testing

### Check Plugin Status

```bash
# View logs
docker logs mcp-gateway | grep -i "version"

# Check database
docker exec mcp-postgres psql -U postgres -d mcp_version_control -c "
  SELECT server_name, version_number, tools_count, is_current, created_at
  FROM server_versions
  ORDER BY server_name, version_number;
"
```

### Expected Output

```
        server_name        | version_number | tools_count | is_current |         created_at
---------------------------+----------------+-------------+------------+----------------------------
 output-schema-test-server |              1 |           8 | t          | 2026-03-19 17:58:07.264517
 qr-code-server            |              1 |           4 | t          | 2026-03-19 17:58:07.311271
```

### Trigger a Version Change

1. Modify an MCP server (add/remove a tool)
2. Wait 60 seconds (or restart the server)
3. Check logs for "Detected version change"
4. Query database to see new version entry

##  Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable/disable plugin |
| `poll_interval_seconds` | integer | `60` | Polling frequency |
| `main_db_url` | string | required | Main database connection |
| `vc_db_url` | string | required | Version control database |
## 🎨 Web UI for Approval Workflow

A standalone web application is available for managing version approvals through a modern, user-friendly interface.

### Quick Start

```bash
# Navigate to the UI directory
cd plugins/version_control/ui

# Start the development server
./start.sh

# Or use Python directly
python3 server.py

# Then open http://localhost:8080 in your browser
```

### Features

- **Modern Interface**: Built with IBM Carbon Design System
- **Real-time Updates**: Auto-refresh every 30 seconds
- **Secure Authentication**: JWT token-based with localStorage
- **Visual Status Indicators**: Clear pending/active/deactivated states
- **One-Click Actions**: Approve, reject, deactivate, or reactivate versions
- **Flexible Reactivation**: Reactivate to either active or pending status
- **Active Version Management**: View and manage currently active versions
- **Error Handling**: Comprehensive error messages and retry mechanisms

### UI Documentation

For complete UI setup, configuration, and usage instructions, see:
- **[UI README](ui/README.md)** - Full documentation
- **[UI Directory](ui/)** - Source files

### UI File Structure

```
plugins/version_control/ui/
├── index.html          # Main HTML page with Carbon Design
├── app.js              # Application logic and API interactions
├── styles.css          # Custom styles extending Carbon
├── server.py           # Simple Python HTTP server
├── start.sh            # Quick start script
└── README.md           # UI documentation
```


## 🔐 Admin Approval Workflow

When the Version Control plugin detects changes to an MCP server, it creates a new version entry with `status='pending'`. Administrators can then approve or reject these changes using the API.

### Workflow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│              ADMIN APPROVAL WORKFLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Server change detected, Tool calls blocked               │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│              ┌──────────────────────────────┐                   │
│              │   Admin Decision via cURL    │                   │
│              └──────────┬───────────┬───────┘                   │
│                         │           │                           │
│              ┌──────────┘           └──────────┐                │
│              │ Approve                  Reject │                │
│              ▼                                 ▼                │
│  ┌─────────────────────────┐      ┌─────────────────────────┐   │
│  │  OPTION A:              │      │  OPTION B:              │   │
│  │  Approve Changes        │      │  Reject Changes         │   │
│  │                         │      │                         │   │
│  │  cURL Command:          │      │  cURL Command:          │   │
│  │  - curl -X PUT          │      │  - curl -X PUT          │   │
│  │  - Authorization: Bearer│      │  - Authorization: Bearer│   │
│  │  - Content-Type: json   │      │  - Content-Type: json   │   │
│  │  - new_status: "active" │      │  - new_status:          │   │
│  │                         │      │    "deactivated"        │   │
│  └────────────┬────────────┘      └────────────┬────────────┘   │
│               │                                │                │
│               ▼                                ▼                │
│  ┌─────────────────────────┐      ┌─────────────────────────┐   │
│  │  Update Database:       │      │  Update Database:       │   │
│  │  Server_Versions        │      │  Server_Versions        │   │
│  │                         │      │                         │   │
│  │  Status: pending →      │      │  Status: pending →      │   │
│  │          active         │      │          deactivated    │   │
│  └─────────────────────────┘      └─────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Prerequisites

Before using the approval workflow, you need:

1. **Authentication Token**: Generate a JWT token for API access
2. **Version ID**: Identify the pending version that needs approval

#### Generate Authentication Token

```bash
# Generate a JWT token (expires in 7 days = 10080 minutes)
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret YOUR_JWT_SECRET_KEY)

# Verify token was created
echo $MCPGATEWAY_BEARER_TOKEN
```

#### List Versions by Status

```bash
# List pending versions
curl -X GET "http://localhost:4444/api/version-control/pending" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json"

# List active versions
curl -X GET "http://localhost:4444/api/version-control/active" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json"

# List deactivated versions
curl -X GET "http://localhost:4444/api/version-control/deactivated" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json"
```

**Example Response:**
```json
{
  "total": 1,
  "versions": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "gateway_id": "abc123-gateway-id",
      "server_name": "output-schema-test-server",
      "server_version": "1.0.1",
      "version_number": 2,
      "tools_count": 9,
      "status": "pending",
      "created_at": "2026-03-19T18:30:00.123456",
      "created_by": "version_control_plugin"
    }
  ]
}
```

### OPTION A: Approve Changes

Approve a pending version to activate it and allow tool calls to proceed.

```bash
# Set the version ID from the list above
VERSION_ID="550e8400-e29b-41d4-a716-446655440000"

# Approve the version (set status to 'active')
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "active" }'
```

**Expected Response:**
```json
{
  "success": true,
  "version_id": "550e8400-e29b-41d4-a716-446655440000",
  "old_status": "pending",
  "new_status": "active",
  "message": "Successfully updated version 550e8400-e29b-41d4-a716-446655440000 status from 'pending' to 'active'"
}
```

**What Happens:**
- ✅ Version status changes from `pending` → `active`
- ✅ `is_current` flag is set to `true`
- ✅ Previous version's `is_current` flag is set to `false`
- ✅ Tool calls to this server are now allowed
- ✅ Database record is updated with admin's email

### OPTION B: Reject Changes

Reject a pending version to deactivate it and prevent tool calls.

```bash
# Set the version ID from the list above
VERSION_ID="550e8400-e29b-41d4-a716-446655440000"

# Reject the version (set status to 'deactivated')
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "deactivated" }'
```

**Expected Response:**
```json
{
  "success": true,
  "version_id": "550e8400-e29b-41d4-a716-446655440000",
  "old_status": "pending",
  "new_status": "deactivated",
  "message": "Successfully updated version 550e8400-e29b-41d4-a716-446655440000 status from 'pending' to 'deactivated'"
}
```

**What Happens:**
- ❌ Version status changes from `pending` → `deactivated`
- ❌ `is_current` flag remains `false`
- ❌ Tool calls to this version are blocked
- ❌ Previous active version remains current
- ✅ Database record is updated with admin's email

### OPTION C: Reactivate a Deactivated Version

Reactivate a previously deactivated version, either directly to active status or back to pending for re-approval.

#### Reactivate to Active

```bash
# Set the version ID of a deactivated version
VERSION_ID="550e8400-e29b-41d4-a716-446655440000"

# Reactivate directly to active status
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "active" }'
```

**What Happens:**
- ✅ Version status changes from `deactivated` → `active`
- ✅ `is_current` flag is set to `true`
- ✅ Previous version's `is_current` flag is set to `false`
- ✅ Tool calls to this server are now allowed
- ✅ Database record is updated with admin's email

#### Reactivate to Pending

```bash
# Reactivate to pending status for re-approval
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "pending" }'
```

**What Happens:**
- ✅ Version status changes from `deactivated` → `pending`
- ❌ `is_current` flag remains `false`
- ❌ Tool calls remain blocked until approved
- ✅ Version is now available for re-approval workflow
- ✅ Database record is updated with admin's email

### OPTION D: Deactivate an Active Version

Deactivate a currently active version to block tool calls.

```bash
# Set the version ID of an active version
VERSION_ID="550e8400-e29b-41d4-a716-446655440000"

# Deactivate the version
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "deactivated" }'
```

**What Happens:**
- ❌ Version status changes from `active` → `deactivated`
- ❌ `is_current` flag is set to `false`
- ❌ Tool calls to this version are blocked
- ⚠️ No other version becomes current automatically
- ✅ Database record is updated with admin's email

### Complete Example Workflow

Here's a complete example showing the full approval workflow:

```bash
# Step 1: Set up authentication
export JWT_SECRET="your-secret-key-from-env"
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret $JWT_SECRET)

# Step 2: Check for pending versions
echo "Checking for pending versions..."
curl -s -X GET "http://localhost:4444/api/version-control/pending" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" | jq '.'

# Step 3: Extract version ID (using jq)
VERSION_ID=$(curl -s -X GET "http://localhost:4444/api/version-control/pending" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" | jq -r '.versions[0].id')

echo "Found version ID: $VERSION_ID"

# Step 4: Approve the version
echo "Approving version..."
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "active" }' | jq '.'

# Step 5: Verify the update
echo "Verifying database update..."
docker exec mcp-postgres psql -U postgres -d mcp_version_control -c "
  SELECT id, server_name, version_number, status, is_current
  FROM server_versions
  WHERE id = '$VERSION_ID';
"
```

### API Reference

#### Endpoint
```
PUT /api/version-control/versions/{version_id}/update-status
```

#### Request Headers
| Header | Value | Required |
|--------|-------|----------|
| `Authorization` | `Bearer <token>` | Yes |
| `Content-Type` | `application/json` | Yes |

#### Request Body
```json
{
  "new_status": "active" | "pending" | "deactivated"
}
```

#### Response Codes
| Code | Description |
|------|-------------|
| `200` | Success - version status updated |
| `400` | Bad Request - invalid status value |
| `401` | Unauthorized - missing or invalid token |
| `404` | Not Found - version ID doesn't exist |
| `500` | Server Error - database or internal error |

### Monitoring and Auditing

#### View Approval History

```sql
-- See all status changes with timestamps
SELECT
  server_name,
  version_number,
  status,
  is_current,
  created_by,
  created_at
FROM server_versions
ORDER BY created_at DESC
LIMIT 10;
```

#### Check Current Active Versions

```sql
-- List all currently active versions
SELECT
  server_name,
  server_version,
  version_number,
  tools_count,
  status,
  created_at
FROM server_versions
WHERE is_current = true AND status = 'active';
```

#### Find Rejected Versions

```sql
-- List all rejected/deactivated versions
SELECT
  server_name,
  version_number,
  status,
  created_by,
  created_at
FROM server_versions
WHERE status = 'deactivated'
ORDER BY created_at DESC;
```

## 🐛 Troubleshooting

### Plugin Not Loading

```bash
# Check logs
docker logs mcp-gateway | grep -i "plugin"

# Verify config
cat plugins/config.yaml | grep -A 10 "VersionControl"
```

### Database Connection Issues

```bash
# Test connection
docker exec mcp-postgres psql -U postgres -l

# Check if database exists
docker exec mcp-postgres psql -U postgres -c "\l" | grep version_control
```

### No Version Changes Detected

```bash
# Check polling is active
docker logs mcp-gateway | grep -i "polling"

# Manually trigger by restarting a server
docker restart output-schema-test-server
```


#### Authentication Errors

```bash
# Error: 401 Unauthorized
# Solution: Verify your JWT token is valid and not expired

# Check token expiration
python -c "
import jwt
import os
token = os.getenv('MCPGATEWAY_BEARER_TOKEN')
decoded = jwt.decode(token, options={'verify_signature': False})
print(f'Token expires at: {decoded.get(\"exp\")}')
"

# Generate a new token if expired
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret $JWT_SECRET)
```

#### Version Not Found

```bash
# Error: 404 Not Found
# Solution: Verify the version ID exists in the database

docker exec mcp-postgres psql -U postgres -d mcp_version_control -c "
  SELECT id, server_name, version_number, status
  FROM server_versions
  WHERE id = 'YOUR_VERSION_ID';
"
```

#### Invalid Status Value

```bash
# Error: 400 Bad Request - Invalid status
# Solution: Use only valid status values: 'active', 'pending', or 'deactivated'

# Correct usage:
curl -X PUT "http://localhost:4444/api/version-control/versions/${VERSION_ID}/update-status" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "new_status": "active" }'  # Valid: active, pending, deactivated
```

## 🔧 Advanced Usage

### Query Version History

```sql
-- Get all versions for a server
SELECT version_number, tools_count, tools_hash, created_at
FROM server_versions
WHERE server_name = 'qr-code-server'
ORDER BY version_number;

-- Find servers with recent changes
SELECT server_name, MAX(version_number) as latest_version, COUNT(*) as total_versions
FROM server_versions
GROUP BY server_name
HAVING COUNT(*) > 1;

-- Get current versions only
SELECT server_name, server_version, tools_count, created_at
FROM server_versions
WHERE is_current = true;
```

### Custom Polling Interval

```yaml
config:
  poll_interval_seconds: 30  # Poll every 30 seconds
```

### Disable Plugin Temporarily

```yaml
config:
  enabled: false  # Plugin loaded but inactive
```

## 📚 Technical Details

### Transport Support

- ✅ **STREAMABLEHTTP**: Full session management support
- ✅ **SSE**: Async streaming support
- ✅ **STDIO**: Not applicable (local processes)
- ✅ **WebSocket**: Not yet tested

### Hash Algorithm

```python
import hashlib
import json

def compute_tools_hash(tools: List[Dict]) -> str:
    # Sort tools by name for consistency
    sorted_tools = sorted(tools, key=lambda t: t.get('name', ''))

    # Convert to JSON string
    tools_json = json.dumps(sorted_tools, sort_keys=True)

    # Compute SHA256
    return hashlib.sha256(tools_json.encode()).hexdigest()
```

### Performance

- **Startup**: ~2-5 seconds for 10 servers
- **Polling**: ~100-500ms per server
- **Memory**: ~10-20MB overhead
- **Database**: ~1KB per version entry

## 🤝 Contributing

To extend this plugin:

1. Add new hooks in `version_control_plugin.py`
2. Extend core logic in `core/version_control_core.py`
3. Update schema in database migrations
4. Add tests in `tests/` directory

## 📄 License

Same as ContextForge main project.

## 🆘 Support

For issues or questions:
1. Check logs: `docker logs mcp-gateway`
2. Verify database: `psql -d mcp_version_control`
3. Review configuration: `plugins/config.yaml`
