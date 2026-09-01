# Raaye — AI-Powered Feedback-to-Action Engine for Pakistani SMEs

> Turn thousands of Roman Urdu reviews into actionable insights — not just sentiment scores, but automated recovery.

---

## Live Demo

- **Frontend:** [https://frontend-khaki-chi-97.vercel.app](https://frontend-khaki-chi-97.vercel.app)
- **Backend API:** [https://raaye-api-qtzkqnhirs.ap-southeast-1.fcapp.run](https://raaye-api-qtzkqnhirs.ap-southeast-1.fcapp.run)
- **API Docs (Swagger):** [https://raaye-api-qtzkqnhirs.ap-southeast-1.fcapp.run/docs](https://raaye-api-qtzkqnhirs.ap-southeast-1.fcapp.run/docs)

The frontend is hosted on **Vercel** and the backend runs on **Alibaba Cloud Function Compute** (serverless). Try the three demo businesses (TechHub Electronics, Zara's Fashion Store, General Store Demo) for instant cached results, or upload your own CSV for live Qwen-powered analysis.

---

## Screenshots

<!-- TODO: add dashboard screenshots here -->
| Upload & Demo Selector | KPI Dashboard | Flagged Reviews & Auto-Replies |
|:---:|:---:|:---:|
| *screenshot pending* | *screenshot pending* | *screenshot pending* |

## The Problem

A mid-size Daraz seller wakes up to 300 new reviews. Half are in Roman Urdu ("*bohat achi quality but delivery late thi*"), mixed with English, emoji, and abbreviations that no off-the-shelf tool can parse. Recurring complaints — late deliveries, wrong sizes, damaged packaging — go unnoticed for weeks until ratings silently drop and sales follow. Existing sentiment analysis tools are built for English, return a single thumbs-up or thumbs-down per review, and give sellers zero actionable next steps. For a seller managing thousands of reviews across dozens of SKUs, this isn't an analytics gap — it's a revenue leak.

## The Solution

**Raaye** reads code-mixed Roman Urdu + English reviews natively. Using Alibaba Cloud's **Qwen** model through Model Studio, it breaks every review into individual aspects — delivery, price, quality, packaging, seller service — and assigns sentiment to each one. A review like "*sound quality zabardast but price zaida hai*" correctly produces `sound → positive`, `price → negative`, instead of a single misleading score.

But detection is only half the job. Raaye closes the loop: for every negative aspect detected above a confidence threshold, it **auto-generates a recovery reply** in the same Roman Urdu + English mix the customer wrote in. It also synthesizes an **executive summary** across entire review batches — top complaint, sentiment split, most urgent flagged review — so a seller can go from raw CSV to action plan in one upload.

## Architecture

```
┌─────────────┐
│  CSV Upload  │  Seller uploads Daraz review export
│  (FastAPI)   │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                    PREPROCESSING                          │
│  normalizer.py                                           │
│  lowercase → strip noise/emoji → collapse repeats →      │
│  canonicalize Roman Urdu spelling variants               │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│              AI ENGINE — Qwen (Alibaba Cloud)             │
│  services/absa_engine.py                                  │
│                                                          │
│  ┌─────────────────────────────────────────────────┐     │
│  │  Few-shot prompt (code-mixed examples)           │     │
│  │  → Batched LLM call (≤10 reviews / request)     │     │
│  │  → Aspect extraction + per-aspect sentiment      │     │
│  │  → Retry (2 attempts) + rule-based fallback      │     │
│  └─────────────────────────────────────────────────┘     │
│  Model: qwen-plus via DashScope OpenAI-compatible API    │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│              ACTION ENGINE                                │
│  services/action_engine.py                                │
│                                                          │
│  • Auto-reply drafts for negative aspects (Qwen +        │
│    template fallback)                                     │
│  • Executive summary per batch (top complaint,            │
│    sentiment split, most urgent review)                   │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────┐   ┌─────────────────────────────────────────┐
│   SQLite /   │   │          Dashboard (Frontend)            │
│  SQLAlchemy  │◄──│          React + Tailwind CSS            │
│  raaye.db    │   │                                         │
└──────────────┘   │  ┌───────────────────────────────────┐  │
                   │  │  Demo Business Selector           │  │
                   │  │  TechHub Electronics              │  │
                   │  │  Zara's Fashion Store             │  │
                   │  │  General Store Demo               │  │
                   │  │  (cached results, instant load)   │  │
                   │  └───────────────────────────────────┘  │
                   │  CSV Upload · KPI Cards · Flagged       │
                   │  Reviews · AI Auto-Reply Approval       │
                   └─────────────────────────────────────────┘
```

## Key Results

Evaluated on a balanced test set of **300 Daraz reviews** (100 per class) from `daraz_reviews_cleaned.csv`, run through the full pipeline with Qwen inference:

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|------|---------|
| Positive | 0.758 | 0.940 | **0.839** | 100 |
| Negative | 0.767 | 0.890 | **0.824** | 100 |
| Neutral | 0.783 | 0.470 | **0.587** | 100 |

**Overall accuracy: 76.7%** — up from a 64% baseline.

### Technical highlight: the tie-breaking bug

During evaluation, we discovered that the prompt improvements correctly produced balanced mixed-sentiment aspects for neutral reviews (e.g., 1 positive + 1 negative), but the `overall_sentiment()` aggregation function broke ties by confidence — reliably picking a polarity winner instead of returning "neutral". A two-line fix (`if positive and negative are tied → return neutral`) jumped accuracy from 68% to 76.7% and neutral F1 from 0.250 to 0.587. This was a case where improving the model output exposed a downstream aggregation bug — the fix was in the evaluation layer, not the prompt.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend API** | FastAPI + Uvicorn |
| **AI / LLM** | Qwen (Alibaba Cloud Model Studio) via OpenAI-compatible API |
| **Database** | SQLite + SQLAlchemy ORM |
| **Frontend** | React + Tailwind CSS (Vite) |
| **Backend Hosting** | Alibaba Cloud Function Compute (FC 3.0, Custom Runtime) |
| **Frontend Hosting** | Vercel |
| **Language** | Python 3.9 (FC runtime) / 3.11+ (local dev) |

## How to Run

### 1. Clone and install

```bash
git clone https://github.com/codebyzahra/Raaye_Alibaba_Hackathon2026.git
cd Raaye_Alibaba_Hackathon2026
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
DASHSCOPE_API_KEY=sk-your-key-here
QWEN_MODEL=qwen-plus-2025-07-28
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
DEMO_MODE=false
```

Get your API key from [Alibaba Cloud Model Studio](https://www.alibabacloud.com/product/model-studio). Without it, the service degrades gracefully to a rule-based keyword fallback.

### 3. Start the backend

```bash
uvicorn main:app --reload
```

The API is live at `http://localhost:8000`. Endpoints:

- `POST /analyze` — send up to 10 reviews, get per-aspect sentiment back
- `POST /api/upload` — upload a CSV of reviews for full pipeline processing

### 4. Demo mode (no API key required)

Set `DEMO_MODE=true` in `.env` to instantly load cached reviews from three demo businesses (38 reviews total) — useful for demos and judging without consuming API quota. The dashboard shows clickable business cards: **TechHub Electronics**, **Zara's Fashion Store**, and **General Store Demo**.

```bash
# Regenerate the cache with live Qwen results (optional):
python evaluation/generate_demo_cache.py
```

### 5. Run the benchmark

```bash
python evaluation/run_benchmark.py --per-class 100
```

This samples 100 reviews per class, runs them through the full pipeline, and saves misclassified examples to `misclassified_examples.json`.

## Deploy

### Backend — Alibaba Cloud Function Compute

Dependencies are pre-installed locally into `.fc-deps/` for the FC custom runtime (Python 3.9 / Linux). All config lives in `s.yaml`.

```bash
# 1. Pre-install dependencies for FC (Python 3.9, Linux)
pip install --no-user --target .fc-deps -r requirements.txt \
  --python-version 3.9 --platform manylinux2014_x86_64 --only-binary=:all:

# 2. Deploy
s deploy -y
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full guide.

### Frontend — Vercel

```bash
cd frontend
npm install -g vercel   # one-time
vercel login            # one-time
vercel --yes --prod     # deploy
```

The frontend's `API_BASE` in `src/App.jsx` must point to the FC backend URL.

**Files:**
- `s.yaml` — Serverless Devs config (FC 3.0, Custom Runtime `custom.debian11`, HTTP trigger)
- `bootstrap` — Custom Runtime entry point (sets PYTHONPATH, starts uvicorn on port 9000)
- `.fcignore` — excludes frontend, CSVs, and docs from the FC deployment package
- `.fc-deps/` — pre-installed Python dependencies (Python 3.9 Linux wheels)

## Roadmap

- **Daraz Seller Center API** — pull reviews directly instead of CSV upload
- **WhatsApp Business API** — send auto-reply drafts to sellers for one-tap approval
- ~~**Alibaba Cloud Function Compute**~~ — ✅ deployed to FC 3.0 (custom.debian11, Python 3.9)
- ~~**Vercel Frontend**~~ — ✅ deployed and connected to FC backend
- **Multilingual expansion** — Sindhi, Pashto, and Bengali review support
- **Trend detection** — track aspect sentiment over time to surface emerging issues before ratings drop
