#!/usr/bin/env python3
"""
Stock-AI V2 — Main Entry Point
Starts FastAPI server + APScheduler + optional ngrok tunnel.

Usage:
  python run.py                    # Start server on port 8000
  python run.py --port 8080        # Custom port
  python run.py --ngrok            # Start with ngrok tunnel
"""
import os
import sys
import argparse

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Stock-AI V2 Server")
    parser.add_argument("--host", default=os.getenv("API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("API_PORT", "8000")))
    parser.add_argument("--ngrok", action="store_true", help="Start ngrok tunnel")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    # Start ngrok if requested
    if args.ngrok:
        try:
            from pyngrok import ngrok
            token = os.getenv("NGROK_AUTHTOKEN")
            if token:
                ngrok.set_auth_token(token)
            
            # Use the static dev domain so the URL never expires
            tunnel = ngrok.connect(5173, "http", domain="anime-luckily-enforced.ngrok-free.dev")
            print(f"\n🌐 ngrok tunnel: {tunnel.public_url}\n")
        except Exception as e:
            print(f"⚠️ ngrok failed: {e} — running without tunnel")

    print(f"""
╔═══════════════════════════════════════════════════════╗
║           Stock-AI V2 — LLM Trading System            ║
║                                                       ║
║  API:       http://localhost:{args.port}                   ║
║  Dashboard: http://localhost:5173                     ║
║  Docs:      http://localhost:{args.port}/docs               ║
╚═══════════════════════════════════════════════════════╝
    """)

    import uvicorn
    uvicorn.run(
        "src.api.server:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["src"] if args.reload else None,
        reload_excludes=["venv/*", "data/*", "*.db"] if args.reload else None,
        factory=True,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
