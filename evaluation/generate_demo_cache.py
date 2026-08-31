"""Generate cached demo results for DEMO_MODE.

Runs 18 representative reviews through the full pipeline (normalizer +
absa_engine + action_engine) and saves to data/cached_demo_results.json.

Usage (from project root):
    python evaluation/generate_demo_cache.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from preprocessing.normalizer import normalize
from services.absa_engine import MAX_BATCH, analyze_reviews
from services.action_engine import (
    generate_auto_replies_for_review,
    generate_executive_summary,
)

REVIEWS = [
    # ---- Positive (4) ----
    "Bohat hi kamal kay Airbird hain sound or bass bohat hi kamal ka hai battery timing bohat achi hai",
    "Excellent product, amazing quality and fast delivery. Highly recommended!",
    "MashAllah bohat achi chiz hai jo mangwaya tha wohi aya hai bilkul orignal",
    "Best purchase this year. Works perfectly, looks great, and the price is fair.",
    # ---- Negative (4) ----
    "Product ki Finishing bilkul Achi nahi hai Glue clear visible hai jesa photo me dekhaya hai wesa bilkul nahi hai",
    "Terrible quality, broke after 2 days. Complete waste of money.",
    "Jo pic hai waise cheez nahi hai ye bht mehangi hai remote bhi achi quality ka nahi hai",
    "Worst experience ever. Damaged packaging, wrong item, and no response from seller.",
    # ---- Neutral / mixed (10) ----
    "ye achi items h quality bi theek but price zaida h",
    "Good product but delivery was very late and packaging was damaged",
    "Quality is ok but size is too small for me",
    "Packing was not good at all come little bit late But mouse is working well",
    "sound quality is good but battery timing is very short",
    "amazing product but length chouti hai aur delivery b late thi",
    "Nice design but the sole is not comfortable otherwise its good",
    "the material is ok but width and length is too small",
    "original hands-free with perfect sound quality but you should deliver it in a box to avoid damages",
    "packing is good delivery on time but sound quality is very low and not clear",
]


def main() -> None:
    print(f"Processing {len(REVIEWS)} demo reviews through the full pipeline ...")

    normalized = [normalize(r) for r in REVIEWS]

    # Step 1: ABSA engine (live Qwen API, batched)
    print("  Running ABSA analysis via Qwen ...")
    absa_results: list[dict] = []
    for start in range(0, len(REVIEWS), MAX_BATCH):
        batch = REVIEWS[start:start + MAX_BATCH]
        absa_results.extend(analyze_reviews(batch))

    # Step 2: Action engine (auto-replies for negative aspects)
    print("  Generating auto-replies ...")
    cache = []
    for i, (review, norm, result) in enumerate(zip(REVIEWS, normalized, absa_results)):
        enriched = generate_auto_replies_for_review(result, review)
        cache.append({
            "review": review,
            "normalized": norm,
            "absa": result,
            "actions": enriched,
        })
        print(f"  [{i + 1}/{len(REVIEWS)}] done")

    # Step 3: Executive summary
    print("  Generating executive summary ...")
    summary = generate_executive_summary(absa_results)

    output = {
        "demo_reviews": cache,
        "executive_summary": summary,
        "meta": {
            "count": len(REVIEWS),
            "generated_with": "absa_engine (live Qwen) + action_engine",
        },
    }

    out_path = PROJECT_ROOT / "data" / "cached_demo_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(REVIEWS)} demo entries to {out_path}")


if __name__ == "__main__":
    main()
