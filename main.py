"""RAaye ABSA core — minimal FastAPI entry point.

Run locally:
    uvicorn main:app --reload
"""

import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

from services.absa_engine import MAX_BATCH, analyze_reviews

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="RAaye ABSA Core",
    description="Aspect-based sentiment analysis for Roman Urdu / code-mixed Daraz reviews.",
    version="0.1.0",
)


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
    return analyze_reviews(request.reviews)
