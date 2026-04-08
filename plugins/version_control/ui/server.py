#!/usr/bin/env python3
"""
Simple HTTP server for Version Control UI
Serves the UI on http://localhost:8080
"""

import http.server
import socketserver
import os
import sys

PORT = 8080

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler to add CORS headers for local development"""
    
    def end_headers(self):
        # Add CORS headers for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        super().end_headers()
    
    def do_OPTIONS(self):
        """Handle preflight requests"""
        self.send_response(200)
        self.end_headers()

def main():
    # Change to the directory containing this script
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Version Control Approval Workflow UI                       ║
║  Standalone web application for ContextForge                ║
╚══════════════════════════════════════════════════════════════╝

🚀 Server starting on http://localhost:{PORT}

📋 Quick Setup:
   1. Open http://localhost:{PORT} in your browser
   2. Click 'Settings' in the navigation
   3. Enter your API URL (default: http://localhost:4444)
   4. Enter your JWT Bearer token
   5. Click 'Save Settings' and 'Test Connection'

🔑 Generate JWT Token:
   python -m mcpgateway.utils.create_jwt_token \\
     --username admin@example.com \\
     --exp 10080 \\
     --secret YOUR_JWT_SECRET_KEY

Press Ctrl+C to stop the server
""")
    
    try:
        with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped. Goodbye!")
        sys.exit(0)
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"\n❌ Error: Port {PORT} is already in use.")
            print(f"   Try stopping other services or use a different port.")
            sys.exit(1)
        else:
            raise

if __name__ == "__main__":
    main()

# Made with Bob
