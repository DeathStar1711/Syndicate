# Stock-AI V2: Comprehensive Architecture & Improvements Analysis

This document outlines the substantial improvements and architectural shifts made in **Stock-AI V2** compared to the legacy `Stock-AI-Live` (V1) project. The migration transitions the project from a set of disjointed, static scripts triggered by GitHub Actions into a cohesive, interactive, LLM-native web application.

---

## 1. Architectural Overhaul

### V1 Architecture (Legacy)
- **Execution:** Headless Python scripts executed linearly via CRON and GitHub Actions.
- **State Management:** Loose JSON/CSV files, often overwritten directly.
- **Delivery:** Output generated as static reports and emailed to the user via SMTP.
- **Model Integration:** Hardcoded or loosely coupled API calls to external services.

### V2 Architecture (Modernized)
- **Backend (FastAPI):** A robust, asynchronous REST API serving as the central nervous system.
- **Frontend (React + Vite):** A responsive, state-aware single-page application (SPA) acting as a live trading dashboard.
- **Live Communication (WebSockets):** Bi-directional live data streams for portfolio updates and price ticking.
- **Internal Scheduling (APScheduler):** Replaced GitHub Actions with a native Python scheduler running inside the FastApi application lifecycle, allowing precise minute-level control (e.g., EOD checks at exactly 3:45 PM IST).

---

## 2. LLM Integration & Inference Pipeline

### Local Intelligence (Ollama + Gemma 4 E4B)
- **Offline First:** Moved away from cloud dependencies to a local Ollama instance running the `gemma4:e4b` model. This reduces latency, ensures privacy, and avoids API token limits.
- **Graceful Degradation:** The backend is designed with robust fault tolerance. If Ollama goes offline, the trading engine falls back to purely technical indicators (moving averages, RSI, MACD) without crashing the application.

### AI-Augmented Features
- **Signal Validation:** Before proposing a trade, the system generates technical signals and passes them through an LLM validator (`signal_validator.py`) alongside live news sentiment to filter out false positives and generate human-readable reasoning.
- **Market Briefing:** An automated morning job fetches index performance, VIX data, and global headlines, synthesizing them via the LLM into a concise "Market Mood" briefing visible on the dashboard.

---

## 3. Real-Time Trading Dashboard (Frontend)

The introduction of a proper UI is the most significant user-facing improvement.

- **Vite + React + TypeScript:** Built for extreme speed and strict type safety.
- **Responsive Design System:** Completely overhauled UI utilizing modern CSS, glassmorphism, and dynamic layout scaling (Mobile-first bottom navigation, Tablet, and Desktop layouts).
- **Interactive Portfolio:** Instead of reading an email, users can actively manage paper trades. You can click "Add to Portfolio" on an AI signal, and the system executes the simulated trade at the live market price.
- **Live Metrics:** The top bar streams NIFTY 50 and SENSEX values without requiring page refreshes.
- **Sector Heatmap:** A visual representation of market breadth, displaying percentage changes across 10 major Indian sectors in real-time.

---

## 4. Enhanced Data & Trading Engine

### Data Reliability
- **NaN Handling:** Implemented robust sanitization (`_fetch_clean()`) to handle off-market hours and missing daily rows, preventing JSON serialization crashes (a major issue in V1).
- **Delisted Asset Protection:** Removed invalid tickers (e.g., Tata Motors demerger) from the watchlist and added try/except blocks to ensure one failing stock doesn't crash the entire batch.

### Strategy & Position Sizing
- **Multi-Factor Logic:** The signal generator (`signals.py`) now combines EMA crossovers, RSI bounds, and MACD histograms with news sentiment.
- **Dynamic Risk Management:** Automatically calculates position size based on a predefined `max_risk_per_trade_pct` against the available simulated capital.

---

## 5. Operations & Developer Experience

- **Hot Reloading:** Configured Uvicorn (`run.py`) to correctly monitor only the `src/` directory and ignore `venv/` and `data/`, resolving the infinite restart loop bug that plagued early development.
- **Unified Startup:** A single `start.sh` script handles cleaning up dead ports (8000, 5173), activating virtual environments, and spinning up both the backend and frontend concurrently.
- **Extensibility:** The modular folder structure (`api/`, `data/`, `strategy/`, `llm/`) makes it trivial to swap out the trading logic or upgrade the underlying LLM without refactoring the entire codebase.

---

**Summary:** Stock-AI V2 transforms a passive script into an active, intelligent, and resilient localized trading terminal.
