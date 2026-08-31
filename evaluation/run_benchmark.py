"""Evaluation benchmark for the ABSA pipeline.

Builds a balanced test set from data/daraz_reviews_cleaned.csv, runs every
review through the app's real pipeline (preprocessing.normalize +
services.absa_engine.analyze_reviews), aggregates aspect-level output into
an overall sentiment, and scores it against the gold labels.

Outputs:
    - console summary table (accuracy / per-class precision / recall / F1)
    - misclassified_examples.json with every wrong prediction

This script only measures the pipeline; it never modifies absa_engine.py
or action_engine.py.

Usage (from the project root):
    python evaluation/run_benchmark.py [--per-class N]
"""

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

# Make project-root imports work regardless of the current working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from preprocessing.normalizer import normalize  # noqa: E402
from services.absa_engine import MAX_BATCH, analyze_reviews  # noqa: E402

DATA_PATH = PROJECT_ROOT / "data" / "daraz_reviews_cleaned.csv"
OUTPUT_PATH = PROJECT_ROOT / "misclassified_examples.json"
CLASSES = ("positive", "negative", "neutral")
SEED = 42


# --- test set construction -----------------------------------------------

def load_balanced_test_set(per_class: int) -> list[dict]:
    """Sample an equal number of rows from each sentiment class."""
    rows_by_class = {label: [] for label in CLASSES}
    with open(DATA_PATH, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            label = (row.get("Sentiments") or "").strip().lower()
            review = (row.get("Reviews") or "").strip()
            if label in rows_by_class and review:
                rows_by_class[label].append({"review": review, "gold": label})

    rng = random.Random(SEED)
    test_set = []
    for label in CLASSES:
        pool = rows_by_class[label]
        if len(pool) < per_class:
            print(f"WARNING: only {len(pool)} '{label}' rows available, "
                  f"using all of them")
        sampled = rng.sample(pool, min(per_class, len(pool)))
        test_set.extend(sampled)
    rng.shuffle(test_set)
    return test_set


# --- overall sentiment aggregation ---------------------------------------

def overall_sentiment(aspects: list[dict]) -> str:
    """Collapse aspect-level sentiments into one overall label.

    Majority vote over aspects. When positive and negative votes are
    tied, return 'neutral' (mixed sentiment). Other ties broken by total
    confidence. If the majority is only 'neutral' with no polarity signal,
    stays neutral.
    """
    if not aspects:
        return "neutral"
    votes = Counter()
    confidence = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    for a in aspects:
        sent = a.get("sentiment", "neutral")
        if sent not in confidence:
            sent = "neutral"
        votes[sent] += 1
        confidence[sent] += a.get("confidence", 0.5)
    top = max(votes.values())
    winners = [s for s, c in votes.items() if c == top]
    if len(winners) == 1:
        return winners[0]
    if "positive" in winners and "negative" in winners:
        return "neutral"
    return max(winners, key=lambda s: confidence[s])


# --- prediction -----------------------------------------------------------

def predict_all(test_set: list[dict]) -> list[dict]:
    """Run the pipeline batch by batch and attach predictions."""
    total = len(test_set)
    results = []
    for start in range(0, total, MAX_BATCH):
        batch = test_set[start:start + MAX_BATCH]
        texts = [item["review"] for item in batch]
        print(f"  batch {start // MAX_BATCH + 1}/"
              f"{(total + MAX_BATCH - 1) // MAX_BATCH} "
              f"({min(start + MAX_BATCH, total)}/{total} reviews)")
        batch_results = analyze_reviews(texts)
        for item, result in zip(batch, batch_results):
            results.append({
                "review": item["review"],
                "normalized": normalize(item["review"]),
                "gold": item["gold"],
                "predicted": overall_sentiment(result.get("aspects", [])),
                "aspects": result.get("aspects", []),
            })
    return results


# --- metrics ---------------------------------------------------------------

def compute_metrics(results: list[dict]) -> dict:
    correct = sum(1 for r in results if r["predicted"] == r["gold"])
    metrics = {label: {} for label in CLASSES}
    for label in CLASSES:
        tp = sum(1 for r in results if r["gold"] == label and r["predicted"] == label)
        fp = sum(1 for r in results if r["gold"] != label and r["predicted"] == label)
        fn = sum(1 for r in results if r["gold"] == label and r["predicted"] != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        metrics[label] = {"precision": precision, "recall": recall, "f1": f1,
                          "support": tp + fn}
    return {"accuracy": correct / len(results) if results else 0.0,
            "total": len(results), "correct": correct, "per_class": metrics}


def print_summary(metrics: dict) -> None:
    print()
    print("=" * 66)
    print("EVALUATION SUMMARY")
    print("=" * 66)
    print(f"{'Class':<10}{'Precision':>11}{'Recall':>9}{'F1':>9}{'Support':>9}")
    print("-" * 66)
    for label in CLASSES:
        m = metrics["per_class"][label]
        print(f"{label:<10}{m['precision']:>11.3f}{m['recall']:>9.3f}"
              f"{m['f1']:>9.3f}{m['support']:>9}")
    print("-" * 66)
    macro_f1 = sum(m["f1"] for m in metrics["per_class"].values()) / len(CLASSES)
    print(f"{'Overall':<10}{'':>11}{'':>9}{macro_f1:>9.3f}{metrics['total']:>9}")
    print(f"Accuracy: {metrics['accuracy']:.3f} "
          f"({metrics['correct']}/{metrics['total']})   Macro-F1: {macro_f1:.3f}")
    print("=" * 66)


# --- misclassified examples -------------------------------------------------

def save_misclassified(results: list[dict]) -> int:
    mistakes = [
        {
            "review": r["review"],
            "normalized": r["normalized"],
            "gold": r["gold"],
            "predicted": r["predicted"],
            "aspects": r["aspects"],
        }
        for r in results if r["predicted"] != r["gold"]
    ]
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(mistakes, f, ensure_ascii=False, indent=2)
    return len(mistakes)


# --- entrypoint --------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ABSA pipeline benchmark")
    parser.add_argument("--per-class", type=int, default=100,
                        help="rows sampled per sentiment class (default: 100)")
    args = parser.parse_args()

    print(f"Loading data from {DATA_PATH} ...")
    test_set = load_balanced_test_set(args.per_class)
    counts = Counter(r["gold"] for r in test_set)
    print(f"Test set: {len(test_set)} reviews "
          f"({', '.join(f'{c}={counts[c]}' for c in CLASSES)}), seed={SEED}")

    print("Running predictions through normalizer + ABSA pipeline ...")
    started = time.time()
    results = predict_all(test_set)
    elapsed = max(time.time() - started, 1e-6)
    print(f"Done in {elapsed:.1f}s ({len(results) / elapsed:.1f} reviews/s)")

    metrics = compute_metrics(results)
    print_summary(metrics)

    n_wrong = save_misclassified(results)
    print(f"\n{n_wrong} misclassified examples saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
