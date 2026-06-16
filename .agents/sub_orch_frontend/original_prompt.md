## 2026-06-16T22:55:03Z

You are a Sub-Orchestrator for the "Frontend Audit & Optimization" track.
Your parent conversation ID is 7bb45366-fe5b-4a10-84c0-63d5c79dbc7e.

Mission: Deep codebase audit and optimization for the frontend of Stock-AI V2. Find unseen edge cases, performance bottlenecks, and long-term stability bugs. Deploy fixes.

Working directory: /Users/shubhamac/Desktop/AI Projects/Stock-AI-V2/.agents/sub_orch_frontend/

Scope document: /Users/shubhamac/Desktop/AI Projects/Stock-AI-V2/.agents/sub_orch_frontend/SCOPE.md

Since your scope fits a single iteration loop, you must execute the Explorer -> Worker -> Reviewer loop (Pattern 2B in your instructions):
1. Spawn 3 teamwork_preview_explorer agents to investigate the frontend codebase.
2. Spawn a teamwork_preview_worker to implement the fixes based on the explorers' reports.
3. Spawn 2 teamwork_preview_reviewer agents to review the worker's changes.
4. Spawn a teamwork_preview_auditor to ensure no integrity violations.
5. If all gates pass, write a final report to your working directory and notify me.

When you are done, send me a message with the path to your final report detailing all bugs found and fixes made.
