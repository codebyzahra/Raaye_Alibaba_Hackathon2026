"""Action layer for the ABSA engine.

Generates auto-reply drafts for negative aspects and executive summaries
from batches of processed reviews.

Uses Qwen API with deterministic fallbacks.
"""

import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.getenv("QWEN_MODEL", "qwen-plus-2025-07-28")
TIMEOUT_SECONDS = 30.0
ATTEMPTS = 2

# Confidence threshold for auto-reply generation
REPLY_CONFIDENCE_THRESHOLD = 0.75

# --- Auto-reply templates (fallback) ------------------------------------

_REPLY_TEMPLATES = {
    "delivery": (
        "We're sorry to hear about the delivery issues. "
        "Hum delivery time improve karne ke liye kaam kar rahe hain. "
        "Aapke feedback ke liye shukriya — hum isay seriously le rahe hain."
    ),
    "price": (
        "Thank you for your feedback on pricing. "
        "Hum competitive prices provide karne ki koshish karte hain. "
        "Aapki suggestion humari team ko bhej di gayi hai."
    ),
    "quality": (
        "We apologize for the quality concerns. "
        "Quality control humari priority hai. "
        "Hum is issue ko investigate karenge aur improve karenge."
    ),
    "packaging": (
        "Sorry about the packaging experience. "
        "Hum packaging standards ko review kar rahe hain. "
        "Aapka feedback humari improvement mein madad karega."
    ),
    "product": (
        "Thank you for sharing your experience. "
        "Hum product quality par kaam kar rahe hain. "
        "Aapki feedback humare liye bohat important hai."
    ),
    "item as described": (
        "We're sorry the item didn't match expectations. "
        "Hum product descriptions ko aur accurate banane ki koshish karenge. "
        "Aapke trust ke liye shukriya."
    ),
    "seller service": (
        "Sorry about your experience with the seller. "
        "Hum seller standards ko improve kar rahe hain. "
        "Aapki complaint humari team ne note kar li hai."
    ),
    "functionality": (
        "We apologize for the functionality issues. "
        "Hum product performance ko behtar banane par kaam kar rahe hain. "
        "Aapke patience ke liye shukriya."
    ),
}

_DEFAULT_REPLY = (
    "Thank you for your feedback. "
    "Hum aapki complaint ko seriously le rahe hain aur improve karne ki koshish karenge. "
    "Aapke support ke liye shukriya."
)


def _call_qwen_for_reply(aspect: str, review_snippet: str) -> str:
    """Generate an auto-reply via Qwen API."""
    client = OpenAI(
        api_key=API_KEY, base_url=BASE_URL,
        timeout=TIMEOUT_SECONDS, max_retries=0,
    )

    system_prompt = (
        "You are a customer service representative for a Daraz-like e-commerce platform. "
        "Generate a short, apologetic, solution-oriented reply to a customer who left a negative review. "
        "The reply should be a mix of Roman Urdu and English (code-mixed), friendly and professional. "
        "Keep it to 2-3 sentences max. Do not include any explanation or preamble — just the reply itself."
    )

    user_prompt = (
        f"Aspect: {aspect}\n"
        f"Customer said: {review_snippet[:200]}\n\n"
        "Generate a short apologetic reply (Roman Urdu + English mix):"
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.choices[0].message.content.strip()


def generate_auto_reply(aspect_dict: dict, review_text: str = "") -> str:
    """Generate an auto-reply draft for a negative aspect.

    Args:
        aspect_dict: Dict with 'aspect', 'sentiment', 'confidence' keys.
        review_text: Optional original review text for context.

    Returns:
        Short reply draft (Roman Urdu + English mix).
    """
    aspect_name = aspect_dict.get("aspect", "overall")
    confidence = aspect_dict.get("confidence", 0.0)

    # Only generate replies for high-confidence negative aspects
    if confidence < REPLY_CONFIDENCE_THRESHOLD:
        return ""

    if API_KEY:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return _call_qwen_for_reply(aspect_name, review_text)
            except Exception as exc:
                logger.warning(
                    "Qwen reply attempt %d/%d failed: %s", attempt, ATTEMPTS, exc
                )
        logger.warning("Qwen unavailable for reply, using template fallback")

    # Template fallback
    return _REPLY_TEMPLATES.get(aspect_name.lower(), _DEFAULT_REPLY)


def generate_auto_replies_for_review(review_result: dict, review_text: str = "") -> list[dict]:
    """Generate auto-replies for all negative aspects in a review result.

    Args:
        review_result: Dict with 'aspects' list from ABSA engine.
        review_text: Optional original review text for context.

    Returns:
        List of dicts with 'aspect', 'sentiment', 'confidence', 'auto_reply'.
    """
    enriched = []
    for aspect in review_result.get("aspects", []):
        reply = ""
        if aspect.get("sentiment") == "negative":
            reply = generate_auto_reply(aspect, review_text)
        enriched.append({**aspect, "auto_reply": reply})
    return enriched


# --- Executive summary --------------------------------------------------

def _call_qwen_for_summary(reviews_data: list[dict]) -> str:
    """Generate an executive summary via Qwen API."""
    client = OpenAI(
        api_key=API_KEY, base_url=BASE_URL,
        timeout=TIMEOUT_SECONDS, max_retries=0,
    )

    system_prompt = (
        "You are a business analyst. Generate a concise executive summary (2-4 sentences) "
        "from a batch of customer reviews. Include:\n"
        "1. The top complaint aspect (most frequently mentioned negative aspect)\n"
        "2. Overall sentiment split (roughly how many positive/negative/neutral)\n"
        "3. The most urgent flagged review (the one with the most severe issues)\n"
        "Keep it factual and actionable. No preamble."
    )

    # Prepare a compact representation of the reviews
    review_snippets = []
    for i, r in enumerate(reviews_data, 1):
        aspects = r.get("aspects", [])
        neg_aspects = [a for a in aspects if a.get("sentiment") == "negative"]
        snippet = f"[{i}] {len(aspects)} aspects, {len(neg_aspects)} negative"
        if neg_aspects:
            snippet += f": {', '.join(a['aspect'] for a in neg_aspects[:3])}"
        review_snippets.append(snippet)

    user_prompt = (
        f"Analyzed {len(reviews_data)} reviews:\n"
        + "\n".join(review_snippets[:10])  # Cap at 10 for token limits
        + "\n\nGenerate a 2-4 sentence executive summary:"
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.choices[0].message.content.strip()


def _fallback_summary(reviews_data: list[dict]) -> str:
    """Generate a deterministic executive summary without the API."""
    if not reviews_data:
        return "No reviews to summarize."

    # Count sentiments
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    aspect_counts = {}
    most_urgent_idx = 0
    max_neg_confidence = 0.0

    for i, r in enumerate(reviews_data):
        aspects = r.get("aspects", [])
        review_has_negative = False
        for a in aspects:
            sent = a.get("sentiment", "neutral")
            sentiment_counts[sent] = sentiment_counts.get(sent, 0) + 1
            if sent == "negative":
                review_has_negative = True
                aspect_name = a.get("aspect", "unknown")
                aspect_counts[aspect_name] = aspect_counts.get(aspect_name, 0) + 1
                conf = a.get("confidence", 0.0)
                if conf > max_neg_confidence:
                    max_neg_confidence = conf
                    most_urgent_idx = i

    total = sum(sentiment_counts.values()) or 1
    top_complaint = max(aspect_counts, key=aspect_counts.get) if aspect_counts else "none"

    summary = (
        f"Analyzed {len(reviews_data)} reviews with {total} total aspects. "
        f"Sentiment split: {sentiment_counts['positive']} positive, "
        f"{sentiment_counts['negative']} negative, {sentiment_counts['neutral']} neutral. "
        f"Top complaint aspect: {top_complaint} "
        f"(mentioned {aspect_counts.get(top_complaint, 0)} times). "
        f"Most urgent review: #{most_urgent_idx + 1} "
        f"(highest negative confidence: {max_neg_confidence:.2f})."
    )

    return summary


def generate_executive_summary(reviews_data: list[dict]) -> str:
    """Generate a short executive summary from a batch of processed reviews.

    Args:
        reviews_data: List of dicts, each with 'aspects' list from ABSA engine.

    Returns:
        2-4 sentence summary covering top complaint, sentiment split, most urgent review.
    """
    if API_KEY:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return _call_qwen_for_summary(reviews_data)
            except Exception as exc:
                logger.warning(
                    "Qwen summary attempt %d/%d failed: %s", attempt, ATTEMPTS, exc
                )
        logger.warning("Qwen unavailable for summary, using deterministic fallback")

    return _fallback_summary(reviews_data)
