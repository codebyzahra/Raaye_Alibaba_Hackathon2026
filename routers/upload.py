"""CSV upload endpoint — processes reviews through the full pipeline.

Flow per review:  CSV row → normalizer → ABSA engine → action engine → SQLite.
"""

import csv
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import Action, AspectSentiment, Review, get_db
from preprocessing.normalizer import normalize
from services.absa_engine import MAX_BATCH, analyze_reviews, rule_based_results
from services.action_engine import (
    generate_auto_reply_detailed,
    needs_auto_reply,
    template_auto_reply,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_WORKERS = 6                 # parallel Qwen calls (batches + replies; DB stays sequential)
BATCH_RESULT_TIMEOUT_SECONDS = 45.0   # max wait on one ABSA batch before rule-based fallback
REPLY_RESULT_TIMEOUT_SECONDS = 18.0   # max wait on one auto-reply call before template fallback
UPLOAD_DEADLINE_SECONDS = 100.0       # hard cap for the whole upload request


def _run_batch(entry: dict, batch: list[str]) -> list[dict]:
    """Executor task: run ABSA on one batch, recording start/finish timing.

    ``entry`` is a request-local dict mutated by the worker; the main thread only
    reads it after ``future.result()`` returns (or after a timeout, in which case
    the in-flight worker's late writes are harmless)."""
    start = time.perf_counter()
    entry["start_abs"] = start
    logger.info("Batch %d (reviews %s) started", entry["index"], entry["range"])
    try:
        return analyze_reviews(batch)
    finally:
        finish = time.perf_counter()
        entry["finish_abs"] = finish
        entry["qwen_call_ms"] = round((finish - start) * 1000)
        logger.info("Batch %d finished in %dms", entry["index"], entry["qwen_call_ms"])


def _run_reply(entry: dict, aspect: dict, review_text: str) -> str:
    """Executor task: generate one auto-reply via the action engine, recording
    start/finish timing and its provenance (qwen vs template)."""
    start = time.perf_counter()
    entry["start_abs"] = start
    text, source = generate_auto_reply_detailed(aspect, review_text)
    finish = time.perf_counter()
    ms = round((finish - start) * 1000)
    # Only record if the collector hasn't already timed this call out and fallen
    # back to the template — a late completion must not rewrite the reported
    # source of a reply we never actually used.
    if not entry.get("decided"):
        entry["finish_abs"] = finish
        entry["ms"] = ms
        entry["source"] = source
    logger.info(
        "Reply (review %s / %s) completed in %dms (source=%s)",
        entry["review_index"], entry["aspect"], ms, source,
    )
    return text


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
    analyzed_rows: list[dict] = []

    # Timing scaffolding. All *_abs values are absolute perf_counter() stamps;
    # they are converted to ms-relative-to-upload when building the response.
    upload_t0 = time.perf_counter()
    deadline = upload_t0 + UPLOAD_DEADLINE_SECONDS

    def _rel_ms() -> int:
        return round((time.perf_counter() - upload_t0) * 1000)

    def _to_rel_ms(abs_val):
        return None if abs_val is None else round((abs_val - upload_t0) * 1000)

    # Split into batches of MAX_BATCH reviews (now 3-4 per Qwen call).
    batches = [
        (start, all_reviews[start: start + MAX_BATCH])
        for start in range(0, total, MAX_BATCH)
    ]

    # ONE thread pool serves both the ABSA batch calls AND the action-engine
    # reply calls. The replies used to be a sequential Qwen call per negative
    # aspect on this thread — the hidden latency (that's why actions_saved 0->6
    # added ~37s). DB writes stay here because the SQLAlchemy session is not
    # thread-safe.
    #
    # We deliberately avoid `with ThreadPoolExecutor(...)`: its __exit__ runs
    # shutdown(wait=True) and blocks on any stuck call. Instead each future is
    # collected with its own timeout, then we shut down without waiting.
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    # --- Phase 1: ABSA analysis (parallel) ------------------------------
    phase1_t0 = time.perf_counter()
    batch_timings: list[dict] = []
    analyze_futures = []
    for bi, (batch_start, batch) in enumerate(batches):
        entry = {
            "index": bi,
            "range": f"{batch_start + 1}-{batch_start + len(batch)}",
            "submit_ms": _rel_ms(),
            "start_abs": None,
            "finish_abs": None,
            "qwen_call_ms": None,
            "outcome": "ok",
        }
        batch_timings.append(entry)
        logger.info(
            "Batch %d (reviews %s) submitted at +%dms",
            bi, entry["range"], entry["submit_ms"],
        )
        analyze_futures.append(executor.submit(_run_batch, entry, batch))

    batch_results: list[tuple[int, list[str], list[dict] | None]] = []
    for (batch_start, batch), entry, future in zip(batches, batch_timings, analyze_futures):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            entry["outcome"] = "deadline"
            logger.warning(
                "Upload deadline (%.0fs) reached at batch %d — rule-based fallback",
                UPLOAD_DEADLINE_SECONDS, batch_start,
            )
            batch_results.append((
                batch_start, batch,
                rule_based_results(batch, f"upload exceeded {UPLOAD_DEADLINE_SECONDS:.0f}s deadline"),
            ))
            continue
        try:
            absa_results = future.result(timeout=min(BATCH_RESULT_TIMEOUT_SECONDS, remaining))
        except FuturesTimeout:
            entry["outcome"] = "timeout"
            logger.warning("ABSA batch starting at %d timed out — rule-based fallback", batch_start)
            absa_results = rule_based_results(batch, "Qwen batch timed out")
        except Exception as exc:
            entry["outcome"] = "error"
            logger.error("ABSA batch starting at %d failed: %s", batch_start, exc)
            for idx_in_batch in range(len(batch)):
                errors.append(f"Review {batch_start + idx_in_batch + 1}: ABSA batch failed — {exc}")
            failed_count += len(batch)
            batch_results.append((batch_start, batch, None))
            continue
        batch_results.append((batch_start, batch, absa_results))

    analysis_wall_ms = round((time.perf_counter() - phase1_t0) * 1000)

    # --- Phase 2: auto-reply generation (parallel, same pool) -----------
    # The reply text is attached to each aspect dict as ``auto_reply`` so Phase
    # 3 (persistence) makes no network calls at all.
    phase2_t0 = time.perf_counter()
    reply_timings: list[dict] = []
    reply_futures: list[tuple[dict, object, dict]] = []
    for batch_start, batch, absa_results in batch_results:
        if absa_results is None:
            continue
        for idx_in_batch, raw_text in enumerate(batch):
            review_num = batch_start + idx_in_batch + 1
            for asp in absa_results[idx_in_batch].get("aspects", []):
                if not needs_auto_reply(asp):
                    asp["auto_reply"] = ""
                    continue
                remaining = deadline - time.perf_counter()
                entry = {
                    "review_index": review_num,
                    "aspect": asp.get("aspect"),
                    "submit_ms": _rel_ms(),
                    "start_abs": None,
                    "finish_abs": None,
                    "ms": None,
                    "source": None,
                }
                reply_timings.append(entry)
                if remaining <= 0:
                    entry["source"] = "template(deadline)"
                    entry["ms"] = 0
                    asp["auto_reply"] = template_auto_reply(asp)
                    continue
                fut = executor.submit(_run_reply, entry, asp, raw_text)
                reply_futures.append((entry, fut, asp))

    # Collect replies with a per-call timeout + the global deadline; on either,
    # degrade to the deterministic template so the action is never lost. Marking
    # ``decided`` stops a late worker from rewriting the reported source.
    for entry, fut, asp in reply_futures:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            entry["decided"] = True
            entry["source"] = "template(deadline)"
            asp["auto_reply"] = template_auto_reply(asp)
            continue
        try:
            asp["auto_reply"] = fut.result(timeout=min(REPLY_RESULT_TIMEOUT_SECONDS, remaining))
        except FuturesTimeout:
            entry["decided"] = True
            entry["source"] = "template(timeout)"
            asp["auto_reply"] = template_auto_reply(asp)
        except Exception as exc:
            logger.error("Reply generation failed for review %s/%s: %s",
                         entry["review_index"], entry["aspect"], exc)
            entry["decided"] = True
            entry["source"] = "template(error)"
            asp["auto_reply"] = template_auto_reply(asp)

    action_wall_ms = round((time.perf_counter() - phase2_t0) * 1000)

    # --- Phase 3: persist (sequential; no Qwen calls here) --------------
    db_t0 = time.perf_counter()
    for batch_start, batch, absa_results in batch_results:
        if absa_results is None:
            continue
        for idx_in_batch, raw_text in enumerate(batch):
            review_num = batch_start + idx_in_batch + 1
            try:
                normalized_text = normalize(raw_text)
                review_result = absa_results[idx_in_batch]
                aspects = review_result.get("aspects", [])

                # Record provenance for this analyzed row.
                analyzed_rows.append({
                    "review_index": review_num,
                    "raw_text": raw_text,
                    "source": review_result.get("source", "fallback"),
                    "fallback_reason": review_result.get("fallback_reason"),
                })

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

                # Persist actions (auto_reply was filled in Phase 2, so no API
                # call happens on this thread).
                for asp in aspects:
                    reply = asp.get("auto_reply", "")
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

    db_write_ms = round((time.perf_counter() - db_t0) * 1000)

    # Don't wait on threads still working a slow/stuck call: cancel queued work
    # and return now. Any in-flight call finishes harmlessly in the background
    # (its result was already replaced by a rule-based / template fallback).
    executor.shutdown(wait=False, cancel_futures=True)

    timings = {
        "total_ms": _rel_ms(),
        "deadline_seconds": UPLOAD_DEADLINE_SECONDS,
        "max_workers": MAX_WORKERS,
        "analysis": {
            "wall_ms": analysis_wall_ms,
            "qwen_calls": sum(1 for e in batch_timings if e["qwen_call_ms"] is not None),
            "batches": [
                {
                    "index": e["index"],
                    "range": e["range"],
                    "submit_ms": e["submit_ms"],
                    "start_ms": _to_rel_ms(e.get("start_abs")),
                    "finish_ms": _to_rel_ms(e.get("finish_abs")),
                    "qwen_call_ms": e.get("qwen_call_ms"),
                    "outcome": e["outcome"],
                }
                for e in batch_timings
            ],
        },
        "action": {
            "wall_ms": action_wall_ms,
            "qwen_calls": sum(1 for e in reply_timings if e["source"] == "qwen"),
            "template_fallbacks": sum(1 for e in reply_timings if e["source"] and e["source"] != "qwen"),
            "calls": [
                {
                    "review_index": e["review_index"],
                    "aspect": e["aspect"],
                    "submit_ms": e["submit_ms"],
                    "start_ms": _to_rel_ms(e.get("start_abs")),
                    "finish_ms": _to_rel_ms(e.get("finish_abs")),
                    "ms": e.get("ms"),
                    "source": e.get("source"),
                }
                for e in reply_timings
            ],
        },
        "db_write_ms": db_write_ms,
    }

    return {
        "status": "success" if failed_count == 0 else "partial",
        "total_reviews": total,
        "reviews_saved": success_count,
        "reviews_failed": failed_count,
        "aspects_saved": total_aspects,
        "actions_saved": total_actions,
        "analyzed_reviews": analyzed_rows,
        "timings": timings,
        "errors": errors if errors else None,
    }
