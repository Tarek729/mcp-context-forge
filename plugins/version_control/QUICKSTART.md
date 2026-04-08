# 🚀 Quick Start Guide - Version Control Plugin

This guide will get the Version Control plugin running in 5 minutes.

## Prerequisites

- ContextForge running with PostgreSQL
- Docker (if using containerized PostgreSQL)
- Access to modify plugin configuration

## Step-by-Step Setup

### 1️⃣ Create Version Control Database (1 minute)

```bash
# If using Docker PostgreSQL
docker exec mcp-postgres psql -U postgres -c "CREATE DATABASE mcp_version_control;"

# Verify it was created
docker exec mcp-postgres psql -U postgres -c "\l" | grep version_control
```

Expected output:
```
 mcp_version_control | postgres | UTF8     | ...
```

### 2️⃣ Configure the Plugin (2 minutes)

Edit `plugins/config.yaml` and add this at the end:

```yaml
plugins:
  - name: "VersionControl"
    kind: "plugins.version_control.version_control_plugin.VersionControlPlugin"
    hooks: ["tool_pre_invoke", "on_startup", "on_shutdown"]
    mode: "permissive"
    priority: 100
    config:
      enabled: true
      poll_interval_seconds: 60
      main_db_url: "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp"
      vc_db_url: "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp_version_control"
```

**Important**: Update the database URLs with your actual credentials!

### 3️⃣ Enable Plugins (30 seconds)

Edit `.env` file and ensure these lines exist:

```bash
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

### 4️⃣ Restart ContextForge (1 minute)

```bash
# Stop current instance
docker-compose down

# Start with plugins enabled
docker-compose up -d

# Watch the logs
docker logs -f mcp-gateway | grep -i "version"
```

### 5️⃣ Verify It's Working (30 seconds)

Check the logs for these messages:

```
✅ Version control database initialized
✅ VersionControlPlugin initialized (poll interval: 60s)
✅ Initial backfill complete: 2 servers
✅ Background polling started
```

Check the database:

```bash
docker exec mcp-postgres psql -U postgres -d mcp_version_control -c "
  SELECT server_name, version_number, tools_count, is_current
  FROM server_versions;
"
```

Expected output:
```
        server_name        | version_number | tools_count | is_current
---------------------------+----------------+-------------+------------
 output-schema-test-server |              1 |           8 | t
 qr-code-server            |              1 |           4 | t
```

## 🎉 Success!

Your Version Control plugin is now:
- ✅ Tracking all MCP servers
- ✅ Monitoring for changes every 60 seconds
- ✅ Storing complete version history

## What Happens Next?

1. **Automatic Monitoring**: Plugin polls servers every 60 seconds
2. **Change Detection**: When tools change, new version is created
3. **Version History**: All changes are logged in the database

## Testing the Plugin

### Trigger a Version Change

1. Modify one of your MCP servers (add/remove a tool)
2. Restart the server
3. Wait 60 seconds
4. Check logs: `docker logs mcp-gateway | grep "version change"`
5. Check database for new version entry

### View Version History

```bash
docker exec mcp-postgres psql -U postgres -d mcp_version_control -c "
  SELECT server_name, version_number, tools_count, created_at
  FROM server_versions
  ORDER BY server_name, version_number;
"
```

## Troubleshooting

### Plugin Not Loading?

```bash
# Check if plugins are enabled
docker exec mcp-gateway env | grep PLUGINS

# Check plugin configuration
cat plugins/config.yaml | grep -A 10 "VersionControl"

# View full logs
docker logs mcp-gateway
```

### Database Connection Failed?

```bash
# Test database connection
docker exec mcp-postgres psql -U postgres -d mcp_version_control -c "SELECT 1;"

# Check if database exists
docker exec mcp-postgres psql -U postgres -c "\l" | grep version_control
```

### No Versions Being Created?

```bash
# Check if servers are registered
docker exec mcp-postgres psql -U postgres -d mcp -c "SELECT name, url FROM gateways;"

# Check plugin logs
docker logs mcp-gateway | grep -i "backfill\|polling"
```

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Customize `poll_interval_seconds` based on your needs
- Set up monitoring/alerting for version changes
- Integrate with your CI/CD pipeline

## Need Help?

1. Check logs: `docker logs mcp-gateway`
2. Verify database: `psql -d mcp_version_control`
3. Review [README.md](README.md) for detailed docs
4. Contact your team lead

---

**Estimated Setup Time**: 5 minutes
**Difficulty**: Easy
**Prerequisites**: Basic Docker and PostgreSQL knowledge
