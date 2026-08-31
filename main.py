"""RAaye ABSA core — minimal FastAPI entry point.

Run locally:
    uvicorn main:app --reload

Demo mode (instant, no API calls):
    Set DEMO_MODE=true in .env, then only pre-cached reviews are served.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from database import init_db, get_db, Review, AspectSentiment, Action
from sqlalchemy.orm import Session
from preprocessing.normalizer import normalize
from routers.upload import router as upload_router
from services.absa_engine import MAX_BATCH, analyze_reviews

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- demo mode (cached results, zero API calls) --------------------------

DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")
_DEMO_CACHE: dict[str, dict] = {}

if DEMO_MODE:
    _cache_path = Path(__file__).parent / "data" / "cached_demo_results.json"
    try:
        with open(_cache_path, encoding="utf-8") as _f:
            _data = json.load(_f)
        _DEMO_CACHE = {
            entry["normalized"]: entry["absa"]
            for entry in _data["demo_reviews"]
        }
        logger.info(
            "DEMO_MODE enabled — loaded %d cached reviews from %s",
            len(_DEMO_CACHE), _cache_path.name,
        )
    except FileNotFoundError:
        logger.error(
            "DEMO_MODE=true but %s not found. "
            "Run: python evaluation/generate_demo_cache.py",
            _cache_path,
        )
    except Exception as exc:
        logger.error("Failed to load demo cache: %s", exc)


# --- app setup -----------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create SQLite tables on startup."""
    init_db()
    yield


app = FastAPI(
    title="RAaye ABSA Core",
    description="Aspect-based sentiment analysis for Roman Urdu / code-mixed Daraz reviews.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(upload_router)


class ABSARequest(BaseModel):
    reviews: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_BATCH,
        description="Up to 10 raw reviews per call.",
    )


@app.post("/analyze")
def analyze(request: ABSARequest) -> list[dict]:
    """One ``{"aspects": [{"aspect", "sentiment", "confidence"}]}`` object per
    review, as a JSON array in the same order as the input."""
    if DEMO_MODE:
        results = []
        for review in request.reviews:
            norm = normalize(review)
            cached = _DEMO_CACHE.get(norm)
            if cached:
                results.append(cached)
            else:
                results.append({
                    "aspects": [
                        {"aspect": "overall", "sentiment": "neutral",
                         "confidence": 0.5,
                         "note": "review not in demo cache"},
                    ]
                })
        return results
    return analyze_reviews(request.reviews)


# --- dashboard data endpoint ---------------------------------------------

@app.get("/api/reviews")
def list_reviews(
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return recent processed reviews with aspects and actions for the
    dashboard."""
    from sqlalchemy import desc
    reviews = (
        db.query(Review)
        .order_by(desc(Review.created_at))
        .limit(limit)
        .all()
    )
    result = []
    for r in reviews:
        aspects = [
            {
                "aspect": a.aspect,
                "sentiment": a.sentiment,
                "confidence": a.confidence,
            }
            for a in r.aspect_sentiments
        ]
        actions = [
            {
                "action_type": a.action_type,
                "action_text": a.action_text,
            }
            for a in r.actions
        ]
        result.append({
            "id": r.id,
            "raw_text": r.raw_text,
            "normalized_text": r.normalized_text,
            "aspects": aspects,
            "actions": actions,
        })
    return result
