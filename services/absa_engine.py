"""Aspect-based sentiment analysis engine.

Calls Alibaba Cloud Model Studio (Qwen) through its OpenAI-compatible
endpoint with a compact few-shot prompt built from real code-mixed rows of
data/daraz_reviews_labeled.csv. Accepts batches of up to 10 reviews and
returns one ``{"aspects": [...]}`` object per review, in input order.

Resilience: request timeout + one retry; if both attempts fail, a simple
rule-based (keyword) fallback produces the output instead.

Config (.env file or environment variables):
    DASHSCOPE_API_KEY   required for the Qwen call
    QWEN_MODEL          optional, default "qwen-plus-2025-07-28"
    DASHSCOPE_BASE_URL  optional, default intl OpenAI-compatible endpoint
"""

import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # load .env if present; env vars still take precedence

from preprocessing.normalizer import normalize

logger = logging.getLogger(__name__)

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.getenv("QWEN_MODEL", "qwen-plus-2025-07-28")
TIMEOUT_SECONDS = 30.0
ATTEMPTS = 2          # initial call + one retry
MAX_BATCH = 10
SENTIMENTS = ("positive", "negative", "neutral")

# --- prompt --------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an aspect-based sentiment analysis (ABSA) system for Daraz "
    "e-commerce reviews written in English, Roman Urdu, or a code-mix of both. "
    "For every review, extract the product/service aspects mentioned (e.g. "
    "quality, price, delivery, packaging, sound, battery, seller service, "
    "item-as-described) and label EACH aspect's sentiment as positive, "
    "negative, or neutral with a confidence between 0 and 1. "
    "IMPORTANT: when a review clearly praises some aspects AND criticizes "
    "others (mixed sentiment), assign positive sentiment to the praised "
    "aspects and negative sentiment to the criticized aspects — do NOT let "
    "one side dominate. "
    "Respond with ONLY a raw JSON array, no markdown, no commentary."
)

# Few-shot examples picked from data/daraz_reviews_labeled.csv, prioritizing
# visible Roman Urdu / code-mixed phrases (line numbers noted).
FEW_SHOT_EXAMPLES = [
    # positive, CSV L12165
    {
        "review": "Bohat hi kamal kay Airbird hain sound or bass bohat hi kamal ka hai "
                  "battery timing bohat achi hai Seller bohat coprative hain delivery "
                  "timing bohat fast tha thank daraz",
        "output": {"aspects": [
            {"aspect": "sound quality", "sentiment": "positive", "confidence": 0.95},
            {"aspect": "battery timing", "sentiment": "positive", "confidence": 0.9},
            {"aspect": "seller service", "sentiment": "positive", "confidence": 0.9},
            {"aspect": "delivery", "sentiment": "positive", "confidence": 0.95},
        ]},
    },
    # positive, CSV L16794
    {
        "review": "MashAllah bohat achi chiz hai jo mangwaya tha wohi aya hai bilkul "
                  "orignal Handfree hai bohat achi serves hai time py mara parsal pohnca",
        "output": {"aspects": [
            {"aspect": "item as described", "sentiment": "positive", "confidence": 0.9},
            {"aspect": "authenticity", "sentiment": "positive", "confidence": 0.9},
            {"aspect": "service", "sentiment": "positive", "confidence": 0.85},
            {"aspect": "delivery", "sentiment": "positive", "confidence": 0.9},
        ]},
    },
    # negative, CSV L2817
    {
        "review": "Product ki Finishing bilkul Achi nahi hai Glue clear visible hai or "
                  "side pe white pattern thek se print bhi nahi hua hai. jesa photo me "
                  "dekhaya hai wesa bilkul nahi hai",
        "output": {"aspects": [
            {"aspect": "finishing", "sentiment": "negative", "confidence": 0.95},
            {"aspect": "item as described", "sentiment": "negative", "confidence": 0.9},
        ]},
    },
    # negative, CSV L889
    {
        "review": "Jo pic hai waise cheez nahi hai ye aur cheez hai bht mehangi hai "
                  "remote bhi achi quality ka nahi hai don't recommend it for new customers",
        "output": {"aspects": [
            {"aspect": "item as described", "sentiment": "negative", "confidence": 0.95},
            {"aspect": "price", "sentiment": "negative", "confidence": 0.85},
            {"aspect": "remote quality", "sentiment": "negative", "confidence": 0.85},
        ]},
    },
    # neutral (mixed: quality praised, price criticized), CSV cleaned L640
    {
        "review": "ye achi items h quality bi theek but price zaida h",
        "output": {"aspects": [
            {"aspect": "quality", "sentiment": "positive", "confidence": 0.8},
            {"aspect": "price", "sentiment": "negative", "confidence": 0.8},
        ]},
    },
    # neutral (mixed: product praised, delivery + size criticized), CSV cleaned L4845
    {
        "review": "amazing product.. length chouti hai... but product achi hai... "
                  "aur delivery b late thi..but satisfied in the end",
        "output": {"aspects": [
            {"aspect": "product quality", "sentiment": "positive", "confidence": 0.85},
            {"aspect": "size", "sentiment": "negative", "confidence": 0.75},
            {"aspect": "delivery", "sentiment": "negative", "confidence": 0.8},
        ]},
    },
    # neutral (mixed: functionality praised, packaging + delivery criticized), CSV cleaned L308
    {
        "review": "Packing was not good at all come little bit late "
                  "But mouse is working well",
        "output": {"aspects": [
            {"aspect": "packaging", "sentiment": "negative", "confidence": 0.85},
            {"aspect": "delivery", "sentiment": "negative", "confidence": 0.75},
            {"aspect": "functionality", "sentiment": "positive", "confidence": 0.85},
        ]},
    },
]


def _few_shot_block() -> str:
    lines = []
    for ex in FEW_SHOT_EXAMPLES:
        lines.append(f"Review: {ex['review']}")
        lines.append(f"Output: {json.dumps(ex['output'])}")
        lines.append("")
    return "\n".join(lines)


def _build_user_prompt(reviews: list[str]) -> str:
    numbered = "\n".join(f"[{i + 1}] {r}" for i, r in enumerate(reviews))
    return (
        "Few-shot examples:\n"
        f"{_few_shot_block()}\n"
        f"Now analyze these {len(reviews)} reviews. Respond with ONLY a JSON array "
        f"of exactly {len(reviews)} objects, in the same order as the input. Each "
        'object must have this shape: {"aspects": [{"aspect": "...", '
        '"sentiment": "positive|negative|neutral", "confidence": 0.0}]}. '
        "Use an empty aspects array only if no aspect is mentioned.\n"
        f"{numbered}"
    )


# --- model call with timeout + one retry ---------------------------------

def _extract_json_array(raw: str) -> list:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON array found in model output: {raw[:120]!r}")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, list):
        raise ValueError("model output is not a JSON array")
    return parsed


def _coerce_entry(entry) -> dict:
    """Validate/reshape one per-review result from the model."""
    aspects = []
    if isinstance(entry, dict):
        for a in entry.get("aspects") or []:
            if not isinstance(a, dict):
                continue
            sentiment = str(a.get("sentiment", "")).strip().lower()
            if sentiment not in SENTIMENTS:
                sentiment = "neutral"
            try:
                confidence = max(0.0, min(1.0, float(a.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5
            aspect = str(a.get("aspect") or "overall").strip() or "overall"
            aspects.append({
                "aspect": aspect,
                "sentiment": sentiment,
                "confidence": round(confidence, 2),
            })
    if not aspects:
        aspects = [{"aspect": "overall", "sentiment": "neutral", "confidence": 0.3}]
    return {"aspects": aspects}


def _call_model(prompt: str) -> str:
    client = OpenAI(
        api_key=API_KEY, base_url=BASE_URL,
        timeout=TIMEOUT_SECONDS, max_retries=0,
    )
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""


# --- rule-based fallback --------------------------------------------------

_ASPECT_RULES = [
    ("delivery", r"\b(deliver\w*|shipping|parcel|time|pohn\w+|late|fast)\b"),
    ("price", r"\b(price|pais[ae]|cost|mehang\w*|sasta|expensive|cheap|overpriced|value)\b"),
    ("quality", r"\b(quality|qlty|material|stuff|finishing|built|durable)\b"),
    ("packaging", r"\b(pack\w*|box|wrapped)\b"),
    ("product", r"\b(product|item|cheez|piece)\b"),
    ("item as described", r"\b(picture|pic|photo|described|same|design|look\w*|colou?r|size|fake|original)\b"),
    ("seller service", r"\b(seller|service|daraz|cooperative|behaviour|response)\b"),
    ("functionality", r"\b(work\w*|function\w*|sound|bass|battery|charging|alarm|speed|performance|awaz)\b"),
]
_POSITIVE_RE = re.compile(
    r"\b(good|great|excellent|amazing|best|nice|love[d]?|happy|satisf\w*|perfect|"
    r"awesome|recommend\w*|acha|achi|achy|zabardast|kamaal|kamal|original|"
    r"genuine|fresh|thanks|thank|wow|superb|worth|outclass|theek)\b", re.I)
_NEGATIVE_RE = re.compile(
    r"\b(bad|worst|poor|terrible|awful|fake|damag\w*|broken|late|defect\w*|"
    r"disappoint\w*|waste|refund|kharab|bakwas|bekar|bekaar|dhoka|dhooka|ganda|"
    r"faaltu|faltu|useless|overpriced|problem|issue\w*|shor)\b", re.I)


def _fallback_entry(review: str) -> dict:
    """Keyword-based aspect detection + lexicon polarity around each aspect."""
    tokens = review.split()
    aspects = []
    for aspect, pattern in _ASPECT_RULES:
        match = re.search(pattern, review, re.I)
        if not match:
            continue
        # sentiment from a +/-8 token window around the aspect keyword
        hit = None
        for i, tok in enumerate(tokens):
            if re.search(pattern, tok, re.I):
                hit = i
                break
        window = " ".join(tokens[max(0, hit - 8):hit + 9]) if hit is not None else review
        pos = len(_POSITIVE_RE.findall(window))
        neg = len(_NEGATIVE_RE.findall(window))
        if pos > neg:
            sentiment, confidence = "positive", 0.5
        elif neg > pos:
            sentiment, confidence = "negative", 0.5
        else:
            sentiment, confidence = "neutral", 0.4
        aspects.append({"aspect": aspect, "sentiment": sentiment, "confidence": confidence})
    if not aspects:  # no known aspect keyword: overall polarity only
        pos = len(_POSITIVE_RE.findall(review))
        neg = len(_NEGATIVE_RE.findall(review))
        sentiment = "positive" if pos > neg else "negative" if neg > pos else "neutral"
        aspects = [{"aspect": "overall", "sentiment": sentiment, "confidence": 0.35}]
    return {"aspects": aspects}


# --- public API -----------------------------------------------------------

def analyze_reviews(reviews: list[str]) -> list[dict]:
    """Analyze up to MAX_BATCH reviews; one result object per review, in order."""
    if not reviews:
        raise ValueError("reviews list must not be empty")
    if len(reviews) > MAX_BATCH:
        raise ValueError(f"at most {MAX_BATCH} reviews per call")

    normalized = [normalize(r) for r in reviews]

    if API_KEY:
        prompt = _build_user_prompt(normalized)
        for attempt in range(1, ATTEMPTS + 1):
            try:
                parsed = _extract_json_array(_call_model(prompt))
                results = []
                for i in range(len(reviews)):
                    try:
                        results.append(_coerce_entry(parsed[i]))
                    except (IndexError, TypeError):
                        logger.warning("bad model output for review %d, using fallback", i)
                        results.append(_fallback_entry(normalized[i]))
                return results
            except Exception as exc:  # timeout, API error, JSON parse error
                logger.warning("Qwen call attempt %d/%d failed: %s", attempt, ATTEMPTS, exc)
        logger.error("Qwen unavailable after %d attempts, using rule-based fallback", ATTEMPTS)
    else:
        logger.warning("DASHSCOPE_API_KEY not set, using rule-based fallback")

    return [_fallback_entry(r) for r in normalized]
