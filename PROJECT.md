# Project: Syndicate (Stock-AI V2) Enhancement

## Architecture
- **Backend**: Python-based AI trading pipeline. Connects to `groww_mcp`, LLM (Groq/Llama-3), ML (XGBoost).
- **Frontend**: React + Vite, visualizing signals and portfolio.
- **Data Flow**: `groww_feed` -> `historical` -> `features` -> `ml` -> `llm` (Signal validation / Mistake analysis) -> `api` -> `frontend`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Architecture & Discovery | Analyze and map current architecture, data flow, bottlenecks, and missing edge cases. | none | DONE |
| 2 | Backend Audit & Optimization | Fix unseen edge cases, performance bottlenecks, long-term stability bugs in backend code. | 1 | IN_PROGRESS (23abeb7b-5398-4d04-8e9c-416ba6c5e960) |
| 3 | Frontend Audit & Optimization | Fix edge cases and improve stability/performance of the frontend. | 1 | IN_PROGRESS (55de0a18-a9d9-40b6-8025-80e4396e0dea) |
| 4 | AI Output Enhancement | Optimize ML (XGBoost) and LLM (Groq/Llama-3.3) pipeline, signal generation, prompt architecture, and data formatting. | 2 | PLANNED |
| 5 | E2E Testing & Final Verification | Verify application boots, AI generates valid signals without exceptions, and produce `audit_report.md`. | 2, 3, 4 | PLANNED |

## Interface Contracts
### Backend API ↔ Frontend
- Standard REST API + Websocket (`/backend/src/api`).
- No breaking changes to existing endpoints unless required for enhancements (must be synchronized).

## Code Layout
- `backend/src/`: Backend logic.
  - `llm/`: Prompts and Groq/Llama-3 logic.
  - `ml/`: XGBoost model, mistake journal.
  - `strategy/`: Trading rules, signal generation.
  - `api/`: REST server, WebSocket.
- `frontend/src/`: UI components, pages, stores.
