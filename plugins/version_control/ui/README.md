# Version Control Approval Workflow UI

A standalone web application for managing MCP server version approvals in ContextForge. Built with IBM Carbon Design System.

## 🎨 Features

- **Real-time Updates**: Auto-refresh every 30 seconds
- **Secure Authentication**: JWT token-based authentication with localStorage
- **Intuitive Workflow**: Easy approve/reject/reactivate actions with confirmation dialogs
- **Status Tracking**: Visual indicators for pending, active, and deactivated versions
- **Flexible Reactivation**: Reactivate deactivated versions to either active or pending status
- **Active Version Management**: View and deactivate currently active versions

## 📋 Prerequisites

- ContextForge gateway running with version control plugin enabled
- Valid JWT token for API authentication
- Modern web browser (Chrome, Firefox, Safari, Edge)

## 🚀 Quick Start

### Option 1: Open Directly in Browser

1. Navigate to the UI directory:
   ```bash
   cd plugins/version_control/ui
   ```

2. Open `index.html` in your browser:
   ```bash
   # macOS
   open index.html

   # Linux
   xdg-open index.html

   # Windows
   start index.html
   ```

### Option 2: Use Python HTTP Server

1. Start a local web server:
   ```bash
   cd plugins/version_control/ui
   python3 -m http.server 8080
   ```

2. Open in browser:
   ```
   http://localhost:8080
   ```

### Option 3: Use Node.js HTTP Server

1. Install http-server globally (one-time):
   ```bash
   npm install -g http-server
   ```

2. Start the server:
   ```bash
   cd plugins/version_control/ui
   http-server -p 8080
   ```

3. Open in browser:
   ```
   http://localhost:8080
   ```

## ⚙️ Configuration

### First-Time Setup

1. Click on **Settings** in the navigation menu
2. Configure the following:
   - **API Base URL**: Your ContextForge gateway URL (default: `http://localhost:4444`)
   - **Bearer Token**: Your JWT authentication token

3. Click **Save Settings** to persist configuration
4. Click **Test Connection** to verify connectivity

### Generating a JWT Token

Generate a token using the ContextForge utility:

```bash
# Generate token that expires in 7 days (10080 minutes)
python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret YOUR_JWT_SECRET_KEY

# For quick testing (no expiration)
python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 0 \
  --secret YOUR_JWT_SECRET_KEY
```

Copy the generated token and paste it into the Bearer Token field in Settings.

## 📖 Usage Guide

### Viewing Versions

The UI has three main sections accessible via navigation tabs:

#### Pending Approvals
Shows all versions awaiting review. Each card displays:
- Server name and version number
- Server version string
- Tool count
- Creation timestamp
- Creator information
- Version ID

#### Active Versions
Shows all currently active versions. Each card displays the same information as pending versions, plus a **Deactivate** button to move versions back to deactivated status.

#### Deactivated Versions
Shows all rejected or deactivated versions. Each card displays the same information with **Reactivate** options.

### Approving a Version

1. Click the **Approve** button on a pending version card
2. Review the confirmation dialog
3. Click **Confirm** to activate the version
4. The version will move to active status and tool calls will be allowed

### Rejecting a Version

1. Click the **Reject** button on a pending version card
2. Review the confirmation dialog
3. Click **Confirm** to deactivate the version
4. The version will move to deactivated status and tool calls will be blocked

### Deactivating an Active Version

1. Navigate to the **Active** section
2. Click the **Deactivate** button on an active version
3. Review the confirmation dialog
4. Click **Confirm** to deactivate the version
5. The version will move to deactivated status and tool calls will be blocked

### Reactivating a Deactivated Version

1. Navigate to the **Deactivated** section
2. Click the **Reactivate** dropdown button on a deactivated version
3. Choose one of two options:
   - **Reactivate to Active**: Immediately activates the version for tool calls
   - **Reactivate to Pending**: Moves version to pending status for re-approval
4. Confirm the action
5. The version will be updated to the selected status

### Statistics Dashboard

The top of the page shows:
- **Pending Approvals**: Count of versions awaiting review
- **Active Versions**: Count of currently active versions
- **Deactivated**: Count of rejected versions
- **Last Updated**: Timestamp of last data refresh (displayed in header)

### Manual Refresh

Click the refresh icon (🔄) in the header to manually reload all data.

## 🔧 API Endpoints Used

The UI interacts with the following ContextForge API endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/version-control/pending` | GET | List all pending versions |
| `/api/version-control/active` | GET | List all active versions |
| `/api/version-control/deactivated` | GET | List all deactivated versions |
| `/api/version-control/versions/{id}/update-status` | PUT | Update version status (approve/reject/reactivate) |

## 🎨 Design System

This UI uses the [IBM Carbon Design System](https://carbondesignsystem.com/):

- **Components**: Buttons, tiles, modals, notifications, forms
- **Typography**: IBM Plex Sans font family
- **Colors**: Carbon color palette with custom theme variables
- **Icons**: Carbon icon set
- **Grid**: Carbon grid system (16 columns)

## 📱 Responsive Breakpoints

- **Desktop**: > 1056px (full layout)
- **Tablet**: 672px - 1056px (adjusted spacing)
- **Mobile**: < 672px (stacked layout, full-width buttons)

## 🔒 Security Considerations

1. **Token Storage**: JWT tokens are stored in browser localStorage
2. **HTTPS Recommended**: Use HTTPS in production environments
3. **Token Expiration**: Tokens should have reasonable expiration times
4. **CORS**: Ensure ContextForge gateway allows CORS from your UI domain

### Production Deployment

For production use:

1. Serve over HTTPS
2. Configure proper CORS headers on the gateway
3. Use environment-specific API URLs
4. Implement token refresh mechanism
5. Add audit logging

## 🐛 Troubleshooting

### Connection Failed

**Problem**: "Connection failed" error when testing connection

**Solutions**:
- Verify ContextForge gateway is running
- Check API Base URL is correct
- Ensure JWT token is valid and not expired
- Check browser console for CORS errors
- Verify network connectivity

### 401 Unauthorized

**Problem**: API requests return 401 Unauthorized

**Solutions**:
- Generate a new JWT token
- Verify token secret matches gateway configuration
- Check token hasn't expired
- Ensure user has proper permissions

### No Data Loading

**Problem**: UI shows loading state indefinitely

**Solutions**:
- Check browser console for JavaScript errors
- Verify API endpoints are accessible
- Test API endpoints directly with curl
- Check network tab in browser DevTools

### CORS Errors

**Problem**: Browser blocks API requests due to CORS

**Solutions**:
- Configure CORS headers on ContextForge gateway
- Use a reverse proxy to serve UI and API from same origin
- For development, use browser extensions to disable CORS (not recommended for production)

## 📁 File Structure

```
plugins/version_control/ui/
├── index.html          # Main HTML page
├── app.js              # Application logic and API interactions
├── styles.css          # Custom styles extending Carbon Design
├── README.md           # This file
└── server.py           # Optional: Simple Python server script
```

## 🔄 Auto-Refresh

The UI automatically refreshes data every 30 seconds. To change this interval, modify the `setInterval` value in `app.js`:

```javascript
// Change 30000 (30 seconds) to desired milliseconds
setInterval(() => {
    if (this.bearerToken) {
        this.loadAllData();
    }
}, 30000);
```

## 🌐 Browser Compatibility

Tested and supported on:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 🔗 Related Documentation

- [Version Control Plugin README](../README.md)
- [ContextForge Documentation](../../../docs/)
- [IBM Carbon Design System](https://carbondesignsystem.com/)
- [ContextForge API Documentation](../../../docs/api/)
