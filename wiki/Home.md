# RAaye ABSA Core

Aspect-based sentiment analysis (ABSA) for Daraz e-commerce reviews written in English, Roman Urdu, or a code-mix of both. Built for the Alibaba Hackathon 2026 — this is the ABSA core only: no database, dashboard, or auth.

## What was built

| File | Purpose |
|---|---|
| `main.py` | Minimal FastAPI app with a single `POST /analyze` endpoint |
| `preprocessing/normalizer.py` | Rule-based Roman Urdu normalizer with 4 inline test cases |
| `services/absa_engine.py` | Qwen-powered ABSA engine with retry + rule-based fallback |
| `requirements.txt` | `fastapi`, `uvicorn`, `openai` |

## API

`POST /analyze` — body `{"reviews": ["...", ...]}` (1–10 reviews per call). Returns a JSON array, one object per review in input order:

```json
[{"aspects": [{"aspect": "delivery", "sentiment": "positive", "confidence": 0.95}]}]
```

Run with `uvicorn main:app --reload`. Config is env-var only: `DASHSCOPE_API_KEY` (required for Qwen), optional `QWEN_MODEL` (default `qwen-plus`), `DASHSCOPE_BASE_URL` (default intl OpenAI-compatible endpoint). Without a key the service degrades gracefully to the fallback.

## How it works

1. **Normalization** (`preprocessing/normalizer.py`): lowercase → strip URLs/mentions/emoji/U+FFFD garbage/punctuation → collapse repeated characters (`bohoooot` → `bohot`) → canonicalize common phonetic variants (`bht/bohot/bahut` → `bohat`, `nhi` → `nahi`, `qlty` → `quality`, `parxel` → `parcel`, …). Test with `python preprocessing/normalizer.py`.
2. **LLM pass** (`services/absa_engine.py`): batched call (up to 10 reviews) to Alibaba Cloud Model Studio / Qwen via the OpenAI-compatible API, with a compact few-shot prompt. The 6 few-shot examples (2 per sentiment class) are real code-mixed rows from `data/daraz_reviews_labeled.csv` (lines 12165, 16794, 2817, 889, 8123, 15170). 30 s timeout and one retry per request.
3. **Fallback**: if both Qwen attempts fail, a rule-based pass detects aspects by keyword (delivery, price, quality, packaging, product, item-as-described, seller service, functionality) and assigns polarity from an English + Roman Urdu lexicon over a ±8-token window.

No model training or fine-tuning is involved.

## Data report — `data/daraz_reviews_labeled.csv`

Inspected 2026-08-27 (reported only, **not** fixed):

- **Encoding corruption**: the file is not valid UTF-8 — decoding yields **21,135 U+FFFD replacement characters** (first bad byte at offset 808). Emoji and some punctuation are mangled. The normalizer strips this noise.
- **Duplicates**: **185 exact duplicate** `(Sentiments, Reviews)` rows (first occurrences at file lines 855, 1027, 1099, 1185, 1727, …).
- **Structure**: clean otherwise — 16,990 data rows, header `Sentiments,Reviews`, no empty rows, no empty labels, no malformed rows.
- **Label distribution**: positive 10,167 · negative 4,362 · neutral 2,461 (imbalanced ~4.1:1 toward positive).
- **Truncation**: some review texts appear cut off mid-word (e.g. "…not s", "…colo").
