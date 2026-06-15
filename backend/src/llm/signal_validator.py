"""
LLM-powered signal validation using LangGraph (Phase 3 Multi-Agent).
Evolves from a single prompt to a debate-driven AI consensus.
Broadcasts pipeline steps via WebSocket for live frontend display.
"""
from typing import Dict, List, Optional, TypedDict
from langgraph.graph import StateGraph, END

from src.llm.client import get_llm_client
from src.utils.logger import get_logger

logger = get_logger("stock_ai.llm")

# ── Pipeline Event Broadcasting ─────────────────────────────────────────────

def _broadcast_pipeline_step(step: str, ticker: str, status: str, content: str = ""):
    """Broadcast a pipeline step event via WebSocket (fire-and-forget)."""
    try:
        from src.api.websocket import manager
        import asyncio

        event = {
            "type": "pipeline_step",
            "data": {
                "step": step,
                "ticker": ticker,
                "status": status,  # "start", "done", "error"
                "content": content if content else "",
            }
        }

        # Try to get an existing event loop; create one if needed (background thread)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast(event))
        except RuntimeError:
            if hasattr(manager, "main_loop") and manager.main_loop:
                asyncio.run_coroutine_threadsafe(manager.broadcast(event), manager.main_loop)
    except Exception:
        pass  # Never block the pipeline


# ── State Definition ────────────────────────────────────────────────────────
class ValidationState(TypedDict):
    signal: Dict
    news_context: str
    market_context: str
    mistake_history: str
    oi_analysis: str
    historical_patterns: str
    
    # Web Search History (Agentic loops)
    sentiment_search_history: str
    risk_search_history: str
    
    # AI Agent Outputs
    tech_analysis: str
    sentiment_analysis: str
    risk_analysis: str
    
    # State flags
    news_fallback: bool
    
    # Final Verdict Output
    final_result: Optional[Dict]


# ── Node Functions ─────────────────────────────────────────────────────────
def technical_analyst_node(state: ValidationState):
    """Analyzes the technical indicators and raw strategy signal."""
    ticker = state["signal"].get("ticker", "?")
    _broadcast_pipeline_step("Technical Analyst", ticker, "start")

    client = get_llm_client()
    if not client.is_healthy():
        _broadcast_pipeline_step("Technical Analyst", ticker, "error", "LLM unavailable")
        return {"tech_analysis": "Technical Analyst unavailable."}

    sig = state["signal"]
    
    ml_context = ""
    if "ml_probability" in sig:
        ml_context = (
            f"ML Model (XGBoost):\n"
            f"- Bullish Probability: {sig.get('ml_probability', 0):.2f}\n"
            f"- Confidence Adjustment: {sig.get('ml_adjustment', 0):+d} (Pre-ML: {sig.get('original_confidence', 0)})\n"
        )
        
    prompt = f"""You are an expert Technical Analyst.
Context: We are evaluating an intraday/swing trade setup (holding period: a few hours to a few weeks). We ONLY take LONG (buy) positions.
The proposed trade direction is: {sig.get('direction', 'long').upper()}

Analyze the following technical indicators for {sig.get('ticker')}:
Direction Proposed: {sig.get('direction', 'long').upper()}
Trend: {sig.get('trend')}
RSI: {sig.get('rsi')}
MACD Momentum: {sig.get('scores', {}).get('momentum')}
Volume Ratio: {sig.get('volume_ratio')}
ADX: {sig.get('adx')}

{ml_context}

Derivatives & Open Interest Data:
{state['oi_analysis']}

Historical Candlestick Patterns Detected:
{state['historical_patterns']}

Market Context:
{state['market_context']}

Provide a brief, concise technical analysis (1-2 paragraphs) assessing the strength and validity of this {sig.get('direction')} setup.
"""
    result = client.generate(prompt, system="You are a strict, objective Technical Analyst.")
    _broadcast_pipeline_step("Technical Analyst", ticker, "done", result or "")
    return {"tech_analysis": result or "Technical analysis failed."}


def sentiment_node(state: ValidationState):
    """Analyzes recent news and market sentiment, actively searching if needed."""
    ticker = state["signal"].get("ticker", "?")
    
    if not state.get("sentiment_search_history"):
        _broadcast_pipeline_step("Sentiment Analyst", ticker, "start")

    client = get_llm_client()
    if not client.is_healthy():
        if not state.get("sentiment_search_history"):
            _broadcast_pipeline_step("Sentiment Analyst", ticker, "error", "LLM unavailable")
        return {"sentiment_analysis": "Sentiment Analyst unavailable."}

    sig = state["signal"]
    search_context = ""
    if state.get("sentiment_search_history"):
        search_context = f"\nPrevious Web Search Results:\n{state['sentiment_search_history']}\n"

    search_count = state.get("sentiment_search_history", "").count("Query:")
    limit_warning = ""
    if search_count >= 2:
        limit_warning = "\nNOTE: You have reached the maximum number of web searches. You MUST output FINAL_ANALYSIS now."

    prompt = f"""You are an expert Sentiment Analyst.
Context: We are evaluating an intraday/swing trade setup (holding period: a few hours to a few weeks). We ONLY take LONG (buy) positions.

Analyze the recent news and overall market sentiment for {sig.get('ticker')}.
{search_context}
Market Context:
{state['market_context']}

If you need more information about recent news, earnings, or catalysts for {sig.get('ticker')}, you can search the web.
To search the web, output EXACTLY this format:
SEARCH: <your search query>
(IMPORTANT: Your search query must include the exact company name: "{sig.get('company_name', sig.get('ticker'))}". For example: "{sig.get('company_name', sig.get('ticker'))} stock news". Do not use the ticker symbol in your query).

If you have enough information to make a final analysis, output EXACTLY this format:
FINAL_ANALYSIS: <your 1-2 paragraph analysis>

Do NOT output both. Choose one.{limit_warning}
"""
    result = client.generate(prompt, system="You are a sharp Sentiment Analyst. Follow output formats strictly.")
    result = (result or "").strip()
    
    if result.startswith("SEARCH:"):
        return {"sentiment_analysis": result}
        
    analysis_text = result.replace("FINAL_ANALYSIS:", "").strip()
    if not analysis_text:
        analysis_text = result # fallback
        
    _broadcast_pipeline_step("Sentiment Analyst", ticker, "done", analysis_text)
    return {"sentiment_analysis": analysis_text}


def sentiment_search_node(state: ValidationState):
    """Executes a web search for the Sentiment Analyst."""
    from src.llm.tools import perform_web_search
    ticker = state["signal"].get("ticker", "?")
    
    query = state["sentiment_analysis"].replace("SEARCH:", "").strip()
    # Strip quotes if the LLM added them
    if query.startswith('"') and query.endswith('"'):
        query = query[1:-1]
        
    step_name = "Web Search (Sentiment)"
    _broadcast_pipeline_step(step_name, ticker, "start", f"Searching Web: '{query}'...")
    
    results = perform_web_search(query, max_results=5)
    
    # Broadcast the search results as done
    _broadcast_pipeline_step(step_name, ticker, "done", f"Query: {query}\n\n{results[:300]}...")
    
    new_history = state.get("sentiment_search_history", "") + f"\nQuery: {query}\nResults:\n{results}\n"
    
    fallback = state.get("news_fallback", False)
    if "DuckDuckGo Search Blocked" in results or "DuckDuckGo Search Failed" in results:
        fallback = True
        
    return {"sentiment_search_history": new_history, "news_fallback": fallback}


def sentiment_route(state: ValidationState) -> str:
    """Route back to search or proceed to risk manager."""
    if state.get("sentiment_analysis", "").startswith("SEARCH:"):
        # Prevent infinite loops (cap at 2 searches)
        if state.get("sentiment_search_history", "").count("Query:") >= 2:
            return "risk_manager"
        return "sentiment_search"
    return "risk_manager"


def risk_manager_node(state: ValidationState):
    """Evaluates the technical vs sentiment risk, actively searching for gaps."""
    ticker = state["signal"].get("ticker", "?")
    
    if not state.get("risk_search_history"):
        _broadcast_pipeline_step("Risk Manager", ticker, "start")

    client = get_llm_client()
    if not client.is_healthy():
        if not state.get("risk_search_history"):
            _broadcast_pipeline_step("Risk Manager", ticker, "error", "LLM unavailable")
        return {"risk_analysis": "Risk Manager unavailable."}

    sig = state["signal"]
    search_context = ""
    if state.get("risk_search_history"):
        search_context = f"\nYour Web Search Results (Risk Investigation):\n{state['risk_search_history']}\n"

    search_count = state.get("risk_search_history", "").count("Query:")
    limit_warning = ""
    if search_count >= 2:
        limit_warning = "\nNOTE: You have reached the maximum number of web searches. You MUST output FINAL_ANALYSIS now."

    prompt = f"""You are the Chief Risk Officer.
Context: We are evaluating an intraday/swing trade setup (holding period: a few hours to a few weeks). We ONLY take LONG (buy) positions.

Evaluate the risks for proposed {sig.get('direction', 'long').upper()} trade on {sig.get('ticker')}.

Technical Analyst's View:
{state['tech_analysis']}

Sentiment Analyst's View:
{state['sentiment_analysis']}

Past Mistakes / Warnings for this ticker:
{state['mistake_history']}
{search_context}
If you detect any missing information, unverified claims by the analysts, or need to check for upcoming earnings or macro risks, you can search the web.
To search the web, output EXACTLY this format:
SEARCH: <your search query>
(IMPORTANT: Your search query must include the exact company name: "{sig.get('company_name', sig.get('ticker'))}". For example: "{sig.get('company_name', sig.get('ticker'))} stock news". Do not use the ticker symbol in your query).

If you have enough information to make a final analysis, output EXACTLY this format:
FINAL_ANALYSIS: <your 1-2 paragraph risk assessment>

Do NOT output both. Choose one.{limit_warning}
"""
    result = client.generate(prompt, system="You are a pessimistic, cautious Risk Manager. Follow output formats strictly.")
    result = (result or "").strip()
    
    if result.startswith("SEARCH:"):
        return {"risk_analysis": result}
        
    analysis_text = result.replace("FINAL_ANALYSIS:", "").strip()
    if not analysis_text:
        analysis_text = result # fallback
        
    _broadcast_pipeline_step("Risk Manager", ticker, "done", analysis_text)
    return {"risk_analysis": analysis_text}


def risk_search_node(state: ValidationState):
    """Executes a web search for the Risk Manager."""
    from src.llm.tools import perform_web_search
    ticker = state["signal"].get("ticker", "?")
    
    query = state["risk_analysis"].replace("SEARCH:", "").strip()
    if query.startswith('"') and query.endswith('"'):
        query = query[1:-1]
        
    step_name = "Web Search (Risk)"
    _broadcast_pipeline_step(step_name, ticker, "start", f"Investigating Risk via Web: '{query}'...")
    
    results = perform_web_search(query, max_results=5)
    
    _broadcast_pipeline_step(step_name, ticker, "done", f"Query: {query}\n\n{results[:300]}...")
    
    new_history = state.get("risk_search_history", "") + f"\nQuery: {query}\nResults:\n{results}\n"
    
    fallback = state.get("news_fallback", False)
    if "DuckDuckGo Search Blocked" in results or "DuckDuckGo Search Failed" in results:
        fallback = True
        
    return {"risk_search_history": new_history, "news_fallback": fallback}


def risk_route(state: ValidationState) -> str:
    """Route back to search or proceed to verdict."""
    if state.get("risk_analysis", "").startswith("SEARCH:"):
        # Prevent infinite loops (cap at 2 searches)
        if state.get("risk_search_history", "").count("Query:") >= 2:
            return "verdict"
        return "risk_search"
    return "verdict"


def verdict_node(state: ValidationState):
    """Synthesizes the debate into a final YES/NO signal (JSON)."""
    ticker = state["signal"].get("ticker", "?")
    _broadcast_pipeline_step("Head of Trading", ticker, "start")

    client = get_llm_client()
    if not client.is_healthy():
        _broadcast_pipeline_step("Head of Trading", ticker, "error", "LLM unavailable")
        return {"final_result": None}

    sig = state["signal"]
    
    ml_context = ""
    if "ml_probability" in sig:
        ml_context = f"\nML Model Bullish Probability: {sig.get('ml_probability', 0):.2f}"

    prompt = f"""You are the Head of Trading.
Context: We are an intraday/swing trading desk (holding period: a few hours to a few weeks). We ONLY take LONG (buy) positions.
You must synthesize the reports from your analysts and make a FINAL trading decision for {sig.get('ticker')} (Proposed: {sig.get('direction', 'long').upper()}).

CRITICAL RULES FOR DECISION:
1. You must severely penalize the confidence score if the Risk Manager explicitly urges "extreme caution" or states "risks outweigh rewards".
2. If the ML Model Bullish Probability is below 0.40, your default verdict MUST be "avoid" UNLESS there is a highly significant fundamental catalyst (e.g., massive earnings beat, major new contract win, or buyout).
3. A bullish technical trend (e.g. high RSI/MACD) does NOT override severe macro risks or low ML probability. You must be ruthless and risk-averse.

Technical Analysis:
{state['tech_analysis']}

Sentiment Analysis:
{state['sentiment_analysis']}

Risk Assessment:
{state['risk_analysis']}

Original Base Confidence: {sig.get('confidence')}/100{ml_context}
Entry Price: {sig.get('entry_price')} | Stop Loss: {sig.get('stop_loss')} | Target: {sig.get('target')}

Output your final decision strictly as JSON.
Format required:
{{
    "verdict": "buy" | "strong_buy" | "hold" | "avoid",
    "reasoning": "A 1-2 sentence final synthesis explaining the decision",
    "adjusted_confidence": <integer 0-100>,
    "key_risk": "The single biggest risk identified"
}}
"""
    result = client.generate_json(prompt, system="You are the Head of Trading. Output strictly JSON.")
    
    if result is None:
        logger.warning(f"Verdict JSON parsing failed for {sig.get('ticker')}")
        _broadcast_pipeline_step("Head of Trading", ticker, "error", "JSON parsing failed")
        return {"final_result": None}
        
    valid_verdicts = {"strong_buy", "buy", "hold", "avoid"}
    if result.get("verdict") not in valid_verdicts:
        result["verdict"] = "buy"
        
    adj_conf = result.get("adjusted_confidence", sig.get("confidence", 50))
    result["adjusted_confidence"] = max(0, min(100, int(adj_conf)))
    result["news_fallback"] = state.get("news_fallback", False)
    
    verdict_str = f'{result["verdict"].upper()} — confidence {result["adjusted_confidence"]}%'
    _broadcast_pipeline_step("Head of Trading", ticker, "done", verdict_str)
    return {"final_result": result}


# ── Graph Construction ──────────────────────────────────────────────────────

workflow = StateGraph(ValidationState)

# Add nodes
workflow.add_node("technical_analyst", technical_analyst_node)
workflow.add_node("sentiment_analyst", sentiment_node)
workflow.add_node("sentiment_search", sentiment_search_node)
workflow.add_node("risk_manager", risk_manager_node)
workflow.add_node("risk_search", risk_search_node)
workflow.add_node("verdict", verdict_node)

# Define edges
workflow.set_entry_point("technical_analyst")
workflow.add_edge("technical_analyst", "sentiment_analyst")

# Sentiment Agentic Loop
workflow.add_conditional_edges(
    "sentiment_analyst",
    sentiment_route,
    {
        "sentiment_search": "sentiment_search",
        "risk_manager": "risk_manager"
    }
)
workflow.add_edge("sentiment_search", "sentiment_analyst")

# Risk Agentic Loop
workflow.add_conditional_edges(
    "risk_manager",
    risk_route,
    {
        "risk_search": "risk_search",
        "verdict": "verdict"
    }
)
workflow.add_edge("risk_search", "risk_manager")

workflow.add_edge("verdict", END)

# Compile graph
validation_app = workflow.compile()


def validate_signal(
    signal: Dict,
    market_context: str = "No market context available",
    mistake_history: str = "No past mistakes with this ticker",
    oi_analysis: str = "No OI data available",
    historical_patterns: str = "No patterns detected",
) -> Optional[Dict]:
    """
    Use LangGraph Multi-Agent debate to validate a trade signal with full context.
    """
    client = get_llm_client()
    if not client.is_healthy():
        return None
        
    ticker = signal.get('ticker', '?')
    
    # Broadcast ML Predictor Context to UI
    if "ml_probability" in signal:
        direction = signal.get("direction", "long")
        bullish_prob = signal.get("ml_probability", 0)
        
        if direction == "long":
            prob_str = f"Bullish Probability: {bullish_prob:.2f}"
        else:
            prob_str = f"Bearish Probability: {(1.0 - bullish_prob):.2f}"
            
        ml_desc = (
            f"XGBoost Model Prediction:\n"
            f"{prob_str}\n"
            f"Confidence Adjusted by: {signal.get('ml_adjustment', 0):+d} "
            f"(Original: {signal.get('original_confidence', 0)})"
        )
        _broadcast_pipeline_step("ML Predictor", ticker, "done", ml_desc)

    # Initialize state
    initial_state = {
        "signal": signal,
        "market_context": market_context,
        "mistake_history": mistake_history,
        "oi_analysis": oi_analysis,
        "historical_patterns": historical_patterns,
        "sentiment_search_history": "",
        "risk_search_history": "",
        "tech_analysis": "",
        "sentiment_analysis": "",
        "risk_analysis": "",
        "news_fallback": False,
        "final_result": None
    }

    try:
        logger.info(f"Starting Multi-Agent validation for {signal.get('ticker')}")
        final_state = validation_app.invoke(initial_state)
        result = final_state.get("final_result")
        
        if result:
            logger.info(
                f"Multi-Agent verdict for {signal.get('ticker')}: "
                f"{result['verdict'].upper()} (confidence: {result.get('adjusted_confidence')}) — "
                f"{result.get('reasoning', '')[:80]}"
            )
        return result
    except Exception as e:
        logger.error(f"LangGraph validation failed for {signal.get('ticker')}: {e}")
        return None


def batch_validate_signals(
    signals: List[Dict],
    market_context: str = "No market context available",
    mistake_histories: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """
    Validate a batch of signals with Multi-Agent LangGraph workflow.
    """
    mistake_histories = mistake_histories or {}

    for signal in signals:
        ticker = signal.get("ticker", "")
        
        # Resolve company name once so the LLM doesn't guess
        if "company_name" not in signal:
            try:
                import yfinance as yf
                import re
                stock = yf.Ticker(ticker)
                name = stock.info.get('shortName') or stock.info.get('longName')
                if name:
                    short_name = name.upper().replace("LTD.", "").replace("LIMITED", "").replace("LTD", "")
                    short_name = re.sub(r'[^A-Z0-9\s]', ' ', short_name).strip()
                    signal["company_name"] = short_name
                else:
                    signal["company_name"] = ticker.replace(".NS", "").replace(".BO", "")
            except Exception:
                signal["company_name"] = ticker.replace(".NS", "").replace(".BO", "")
        
        # Fetch dynamic agent data (Groww MCP)
        oi_data = "No OI data"
        patterns_data = "No historical patterns"
        try:
            from src.data.groww_mcp import get_oi_analysis_sync, get_historical_patterns_sync
            oi = get_oi_analysis_sync(ticker)
            if oi:
                oi_data = str(oi)
            
            pats = get_historical_patterns_sync(ticker)
            if pats:
                patterns_data = str(pats)
        except Exception as e:
            logger.warning(f"Failed to fetch MCP data for LLM: {e}")

        validation = validate_signal(
            signal,
            market_context=market_context,
            mistake_history=mistake_histories.get(ticker, "No past mistakes"),
            oi_analysis=oi_data,
            historical_patterns=patterns_data,
        )

        if validation:
            signal["llm_validation"] = validation
            signal["llm_verdict"] = validation["verdict"]
            signal["llm_reasoning"] = validation.get("reasoning", "")
            signal["llm_confidence"] = validation.get("adjusted_confidence", 0)
            signal["llm_key_risk"] = validation.get("key_risk", "")
            signal["news_fallback"] = validation.get("news_fallback", False)
        else:
            signal["llm_validation"] = None
            signal["llm_verdict"] = None
            signal["llm_reasoning"] = "LLM analysis unavailable"
            signal["llm_confidence"] = signal.get("confidence", 0)

    return signals
