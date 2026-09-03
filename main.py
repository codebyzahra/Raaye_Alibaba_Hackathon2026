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
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from database import init_db, get_db, Review, AspectSentiment, Action
from sqlalchemy.orm import Session
from preprocessing.normalizer import normalize
from routers.upload import router as upload_router
from services.absa_engine import MAX_BATCH, analyze_reviews, API_KEY, BASE_URL, MODEL, _call_model

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- demo mode (cached results, zero API calls) --------------------------

DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")
_DEMO_CACHES: dict[str, dict] = {}       # business_id → full cache dict
_DEMO_REVIEWS: dict[str, dict] = {}      # normalized_text → absa result (merged)

# Always load demo caches so the business list is visible.
# The POST /api/demo/{id} endpoint still requires DEMO_MODE=true.
_data_dir = Path(__file__).parent / "data"
for _cache_file in sorted(_data_dir.glob("*.json")):
    try:
        with open(_cache_file, encoding="utf-8") as _f:
            _data = json.load(_f)
        if "demo_reviews" not in _data:
            continue
        _bid = _data.get("business_id", _cache_file.stem)
        _DEMO_CACHES[_bid] = _data
        for _entry in _data["demo_reviews"]:
            _DEMO_REVIEWS[_entry["normalized"]] = _entry["absa"]
        logger.info(
            "Loaded demo cache '%s' (%d reviews) from %s",
            _bid, len(_data["demo_reviews"]), _cache_file.name,
        )
    except Exception as exc:
        logger.error("Failed to load demo cache %s: %s", _cache_file.name, exc)
logger.info(
    "Demo summary: %d business(es), %d total cached reviews",
    len(_DEMO_CACHES), len(_DEMO_REVIEWS),
)


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
            cached = _DEMO_REVIEWS.get(norm)
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


# --- temporary debug endpoint (remove before production) -----------------

@app.get("/health")
def health_check() -> dict:
    """Debug endpoint: env status + live Qwen connectivity test."""
    api_key_set = bool(API_KEY)
    model_loaded = MODEL

    qwen_test: dict = {}
    if not api_key_set:
        qwen_test = {"status": "skipped", "error": "DASHSCOPE_API_KEY is not set"}
    else:
        try:
            raw = _call_model(
                'Respond with ONLY the text: {"ok": true}'
            )
            qwen_test = {"status": "ok", "raw_response": raw[:300]}
        except Exception as exc:
            qwen_test = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    return {
        "api_key_set": api_key_set,
        "model": model_loaded,
        "base_url": BASE_URL,
        "qwen_test": qwen_test,
    }


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


# --- demo business endpoints ----------------------------------------------

@app.get("/api/demo/businesses")
def list_demo_businesses() -> list[dict]:
    """Return metadata for all available demo businesses."""
    businesses = []
    for bid, cache in _DEMO_CACHES.items():
        businesses.append({
            "id": bid,
            "name": cache.get("business_name", bid),
            "description": cache.get("business_description", ""),
            "review_count": cache.get("meta", {}).get("count", 0),
        })
    return businesses


@app.post("/api/demo/{business_id}")
def load_demo(
    business_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Load cached demo reviews into the database for a specific business."""
    cache = _DEMO_CACHES.get(business_id)
    if not cache:
        raise HTTPException(404, f"Demo business '{business_id}' not found")

    total = 0
    actions_saved = 0
    for entry in cache.get("demo_reviews", []):
        review = Review(
            raw_text=entry["review"],
            normalized_text=entry["normalized"],
            source=f"demo_{business_id}",
        )
        db.add(review)
        db.flush()
        total += 1

        for asp in entry.get("absa", {}).get("aspects", []):
            db.add(AspectSentiment(
                review_id=review.id,
                aspect=asp["aspect"],
                sentiment=asp["sentiment"],
                confidence=asp["confidence"],
            ))

        for act in entry.get("actions", []):
            reply = act.get("auto_reply", "")
            if reply:
                db.add(Action(
                    review_id=review.id,
                    action_type="auto_reply",
                    action_text=reply,
                ))
                actions_saved += 1

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Failed to persist demo data: {exc}")

    return {
        "status": "success",
        "total_reviews": total,
        "reviews_saved": total,
        "reviews_failed": 0,
        "aspects_saved": sum(
            len(e.get("absa", {}).get("aspects", []))
            for e in cache.get("demo_reviews", [])
        ),
        "actions_saved": actions_saved,
        "business_name": cache.get("business_name", business_id),
        "errors": None,
    }
