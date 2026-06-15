#!/bin/bash
# ════════════════════════════════════════════════
# Stock-AI V2 — First-Time Setup
# ════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "📦 Setting up Stock-AI V2..."

# 1. Python virtual environment
echo "🐍 Creating Python virtual environment..."
cd "$SCRIPT_DIR/backend"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 2. Copy env file
if [ ! -f .env ]; then
  cp .env.example .env
  echo "📝 Created .env from template — please fill in your API keys!"
fi

# 3. Pull Gemma 4 E4B via Ollama
echo "🤖 Pulling Gemma 4 E4B model..."
if command -v ollama &> /dev/null; then
  ollama pull gemma4:e4b
else
  echo "⚠️  Ollama not found. Install from: https://ollama.com"
  echo "   Then run: ollama pull gemma4:e4b"
fi

# 4. Frontend dependencies
echo "🌐 Installing frontend dependencies..."
cd "$SCRIPT_DIR/frontend"
npm install

# 5. Initialize data directories
mkdir -p "$SCRIPT_DIR/backend/data/"{trades,ml,models,logs,reports,historical}

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit backend/.env with your API keys"
echo "  2. Make sure Ollama is running: ollama serve"
echo "  3. Run: bash scripts/start.sh"
