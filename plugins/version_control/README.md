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
│                    ContextForge Gateway                      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Version Control Plugin                         │ │
│  │  ┌──────────────┐         ┌──────────────┐           │ │
│  │  │   Startup    │────────▶│  Background  │           │ │
│  │  │   Backfill   │         │   Polling    │           │ │
│  │  └──────────────┘         └──────┬───────┘           │ │
│  │         │                         │                    │ │
│  │         └─────────┬───────────────┘                    │ │
│  │                   ▼                                     │ │
│  │         ┌──────────────────┐                           │ │
│  │         │ Version Control  │                           │ │
│  │         │      Core        │                           │ │
│  │         └────────┬─────────┘                           │ │
│  └──────────────────┼──────────────────────────────────────┘ │
│                     │                                        │
│         ┌───────────┼───────────┐                           │
│         ▼           ▼           ▼                           │
│    ┌────────┐  ┌────────┐  ┌────────┐                     │
│    │  MCP   │  │  MCP   │  │  MCP   │                     │
│    │Server 1│  │Server 2│  │Server 3│                     │
│    └────────┘  └────────┘  └────────┘                     │
└─────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
    ┌─────────────────────────────────────┐
    │   mcp_version_control Database      │
    │  ┌─────────────────────────────┐   │
    │  │    server_versions table    │   │
    │  │  - gateway_id               │   │
    │  │  - server_name              │   │
    │  │  - server_version           │   │
    │  │  - version_number           │   │
    │  │  - tools_hash (SHA256)      │   │
    │  │  - version_hash (SHA256)    │   │
    │  │  - tools_count              │   │
    │  │  - is_current               │   │
    │  │  - created_at               │   │
    │  └─────────────────────────────┘   │
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

## 📝 Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable/disable plugin |
| `poll_interval_seconds` | integer | `60` | Polling frequency |
| `main_db_url` | string | required | Main database connection |
| `vc_db_url` | string | required | Version control database |

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
4. Contact: Your team lead or ContextForge maintainers