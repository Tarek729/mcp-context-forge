#!/bin/bash
# Quick start script for Version Control UI

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Version Control Approval Workflow UI                       ║"
echo "║  Starting local development server...                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check if Python 3 is available
if command -v python3 &> /dev/null; then
    echo "✓ Python 3 found"
    python3 server.py
elif command -v python &> /dev/null; then
    echo "✓ Python found"
    python server.py
else
    echo "❌ Python not found. Please install Python 3."
    echo ""
    echo "Alternative: Open index.html directly in your browser"
    exit 1
fi

# Made with Bob
