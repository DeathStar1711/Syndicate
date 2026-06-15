#!/bin/bash
# ════════════════════════════════════════════════
# Stock-AI V2 — Stop All Services
# ════════════════════════════════════════════════

echo "🛑 Stopping Stock-AI V2 services..."

# Kill backend API (port 8000)
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚙️  Killing backend API (Port 8000)..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
else
    echo "⚙️  Backend API is not running."
fi

# Kill Groww MCP Server (port 52155)
if lsof -Pi :52155 -sTCP:LISTEN -t >/dev/null ; then
    echo "🔌 Killing Groww MCP Auth Server (Port 52155)..."
    lsof -ti:52155 | xargs kill -9 2>/dev/null || true
    pkill -f "mcp-remote" 2>/dev/null || true
else
    echo "🔌 Groww MCP Auth Server is not running."
fi

# Kill frontend (port 5173)
if lsof -Pi :5173 -sTCP:LISTEN -t >/dev/null ; then
    echo "🌐 Killing frontend (Port 5173)..."
    lsof -ti:5173 | xargs kill -9 2>/dev/null || true
else
    echo "🌐 Frontend is not running."
fi

# Kill hanging MCP processes
if pgrep -f "chrome-devtools-mcp" > /dev/null ; then
    echo "🤖 Killing dangling MCP processes..."
    pkill -f "chrome-devtools-mcp" 2>/dev/null || true
fi

echo "✅ All Stock-AI services have been cleanly terminated."
