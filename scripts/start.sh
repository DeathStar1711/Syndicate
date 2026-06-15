#!/bin/bash
# ════════════════════════════════════════════════
# Stock-AI V2 — Start All Services
# ════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "🚀 Starting Stock-AI V2..."

# Check Groq API
echo "🤖 Using Groq Cloud API for LLM features"

# Start backend
echo "🧹 Cleaning up existing processes..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true
lsof -ti:52155 | xargs kill -9 2>/dev/null || true
pkill -f "mcp-remote" 2>/dev/null || true
sleep 1

echo "⚙️  Starting backend API..."
cd "$SCRIPT_DIR/backend"
source venv/bin/activate 2>/dev/null || true
caffeinate -i -s python run.py --reload --ngrok &
BACKEND_PID=$!
sleep 2

# Start frontend
echo "🌐 Starting frontend..."
cd "$SCRIPT_DIR/frontend"
caffeinate -i -s npm run dev &
FRONTEND_PID=$!

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        Stock-AI V2 — All Systems Go      ║"
echo "║                                          ║"
echo "║  Dashboard: http://localhost:5173         ║"
echo "║  API:       http://localhost:8000         ║"
echo "║  API Docs:  http://localhost:8000/docs    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Press Ctrl+C to stop all services"

# Trap SIGINT to kill all background processes
trap "echo '⏹  Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

# Wait for processes
wait
