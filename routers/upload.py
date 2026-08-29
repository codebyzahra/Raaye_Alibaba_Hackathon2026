"""CSV upload endpoint — processes reviews through the full pipeline.

Flow per review:  CSV row → normalizer → ABSA engine → action engine → SQLite.
"""

import csv
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import Action, AspectSentiment, Review, get_db
from preprocessing.normalizer import normalize
from services.absa_engine import MAX_BATCH, analyze_reviews
from services.action_engine import generate_auto_replies_for_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a CSV file of reviews and process them through the ABSA pipeline."""

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV file.")

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read uploaded file.")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no headers.")

    # Auto-detect review column
    review_col: str | None = None
    for col in reader.fieldnames:
        if col.strip().lower() in ("review", "text", "review_text", "reviews"):
            review_col = col
            break
    if review_col is None:
        review_col = reader.fieldnames[0]

    # Collect rows
    all_reviews: list[str] = []
    for row in reader:
        val = row.get(review_col, "").strip()
        if val:
            all_reviews.append(val)

    if not all_reviews:
        raise HTTPException(status_code=400, detail="No reviews found in the CSV file.")

    total = len(all_reviews)
    success_count = 0
    failed_count = 0
    total_aspects = 0
    total_actions = 0
    errors: list[str] = []

    # Process in batches of MAX_BATCH (10)
    for batch_start in range(0, total, MAX_BATCH):
        batch = all_reviews[batch_start: batch_start + MAX_BATCH]

        try:
            absa_results = analyze_reviews(batch)
        except Exception as exc:
            logger.error("ABSA batch starting at %d failed: %s", batch_start, exc)
            for idx_in_batch in range(len(batch)):
                errors.append(f"Review {batch_start + idx_in_batch + 1}: ABSA batch failed — {exc}")
            failed_count += len(batch)
            continue

        for idx_in_batch, raw_text in enumerate(batch):
            review_num = batch_start + idx_in_batch + 1
            try:
                normalized_text = normalize(raw_text)
                review_result = absa_results[idx_in_batch]
                aspects = review_result.get("aspects", [])

                # Generate auto-replies (action engine)
                enriched = generate_auto_replies_for_review(review_result, raw_text)

                # Persist review
                review = Review(
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    source="csv_upload",
                )
                db.add(review)
                db.flush()  # obtain review.id

                # Persist aspect sentiments
                for asp in aspects:
                    db.add(AspectSentiment(
                        review_id=review.id,
                        aspect=asp["aspect"],
                        sentiment=asp["sentiment"],
                        confidence=asp["confidence"],
                    ))
                total_aspects += len(aspects)

                # Persist actions (non-empty auto-replies only)
                for asp_enriched in enriched:
                    reply = asp_enriched.get("auto_reply", "")
                    if reply:
                        db.add(Action(
                            review_id=review.id,
                            action_type="auto_reply",
                            action_text=reply,
                        ))
                        total_actions += 1

                success_count += 1

            except Exception as exc:
                db.rollback()
                failed_count += 1
                errors.append(f"Review {review_num}: {exc}")
                logger.error("Error processing review %d: %s", review_num, exc)

        # Commit the whole batch at once
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            errors.append(f"DB commit for batch starting at {batch_start} failed: {exc}")
            logger.error("DB commit error: %s", exc)

    return {
        "status": "success" if failed_count == 0 else "partial",
        "total_reviews": total,
        "reviews_saved": success_count,
        "reviews_failed": failed_count,
        "aspects_saved": total_aspects,
        "actions_saved": total_actions,
        "errors": errors if errors else None,
    }
