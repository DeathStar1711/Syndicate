"""
Trades API routes — trade actions and mistake journal.
"""
from fastapi import APIRouter
from src.utils.logger import get_logger

logger = get_logger("stock_ai.api")
router = APIRouter()


@router.get("/mistakes")
async def get_mistake_analysis():
    """Get mistake journal analysis with LLM insights."""
    from src.ml.mistake_journal import MistakeJournal

    journal = MistakeJournal()
    patterns = journal.get_mistake_patterns()
    report = journal.get_analysis_report()

    return {
        "patterns": patterns,
        "report": report,
    }


@router.get("/mistakes/recent")
async def get_recent_mistakes(limit: int = 10):
    """Get recent mistake entries."""
    from src.ml.mistake_journal import MistakeJournal
    journal = MistakeJournal()
    samples = journal.get_mistake_samples(n=limit)
    return {"mistakes": samples, "count": len(samples)}
