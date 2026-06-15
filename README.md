# Syndicate: Autonomous Multi-Agent Trading Desk

**Syndicate** (formerly Stock-AI-V2) is an institutional-grade, fully automated trading pipeline that combines deterministic Machine Learning (XGBoost) with cutting-edge Large Language Models (Llama-3.3 via Groq) to analyze, debate, and execute equity trades.

## Key Features

* **🤖 Multi-Agent LLM Debate System:** Every stock undergoes a rigorous review by four distinct AI agents:
  * **Technical Analyst:** Interprets momentum indicators (RSI, MACD, Volume).
  * **Sentiment Analyst:** Crawls the web via search APIs to summarize real-time news and macro catalysts.
  * **Risk Manager:** A ruthless, risk-averse agent designed to identify macro headwinds and veto statistically poor setups.
  * **Head of Trading:** Synthesizes the debate and makes a final `BUY/AVOID` call based on strict algorithmic constraints.
* **🧮 XGBoost ML Predictor:** A dynamically retrained machine learning model that calculates the mathematical probability of a successful breakout over a 5-day horizon based on historical feature weights.
* **⚡ Ultra-Fast Groq Cloud Integration:** Utilizes `llama-3.3-70b-versatile` running on Groq's LPUs for near-instantaneous multi-agent reasoning, bypassing the constraints of local hardware.
* **📊 Real-Time React Dashboard:** A beautiful, glassmorphic UI built with Vite/React that streams the live "AI Pipeline Logs" via WebSockets, allowing you to watch the AI's internal debate unfold in real-time.
* **🌐 Secure Remote Access:** Fully configured with `ngrok` for static tunneling, allowing the backend to run securely on a local machine while being accessible from a cloud-deployed frontend (e.g., Vercel).

## Architecture

* **Frontend:** React, Vite, TypeScript, custom glassmorphism CSS framework.
* **Backend:** FastAPI (Python), APScheduler, WebSockets, SQLite.
* **AI/ML:** XGBoost for predictive modeling, Groq Cloud API (Llama-3.3-70b) for LLM agents, LangGraph for agent orchestration.
* **Market Data:** Groww API (live feeds), Tiingo (news parsing), Yahoo Finance.

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/DeathStar1711/Syndicate.git
cd Syndicate
```

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the `backend/` directory with the necessary keys (Groq, Ngrok, etc.). *Note: `.env` is intentionally gitignored for security.*

### 3. Frontend Setup
```bash
cd frontend
npm install
```

### 4. Running the System
You can start the entire stack using the provided shell script:
```bash
./scripts/start.sh
```
This will start the FastAPI backend, initialize the ngrok tunnel, and boot up the Vite frontend on `localhost:5173`.

To cleanly terminate all processes:
```bash
./scripts/stop.sh
```

## Disclaimer
This system is for research and paper trading only. It does not guarantee returns and is not financial advice.
