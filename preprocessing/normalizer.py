"""Rule-based normalizer for Roman Urdu / code-mixed Daraz reviews.

Pipeline: lowercase -> strip noise (URLs, mentions, emoji, U+FFFD garbage,
punctuation) -> collapse repeated characters ('bohoooot' -> 'bohot')
-> map common phonetic spelling variants to canonical forms.

Run this file directly to execute the inline test cases:
    python preprocessing/normalizer.py
"""

import re

# --- noise patterns ----------------------------------------------------

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#(\w+)")
_REPEAT_RE = re.compile(r"(.)\1{2,}")       # 3+ identical chars -> 1
_NOISE_CHAR_RE = re.compile(r"[^\w\s']")    # punctuation, emoji, U+FFFD

# --- common phonetic spelling variants -> canonical form ---------------

VARIANT_MAP = {
    # intensifier "bohat" (very)
    "bohot": "bohat", "bhut": "bohat", "bahut": "bohat", "bhot": "bohat",
    "bohut": "bohat", "bohatt": "bohat", "buhat": "bohat", "bht": "bohat",
    # "acha" (good) and its gender/number forms
    "achha": "acha", "accha": "acha", "achaa": "acha", "achy": "acha",
    "achee": "achi", "achii": "achi",
    # negation "nahi"
    "nhi": "nahi", "nahin": "nahi", "nai": "nahi", "nhe": "nahi",
    # copula "hai"
    "hain": "hai", "hy": "hai",
    # common descriptors
    "khrab": "kharab", "zbrdst": "zabardast", "zabrdast": "zabardast",
    "bilkl": "bilkul", "bilkol": "bilkul",
    "thek": "theek", "teek": "theek", "theik": "theek",
    "bekar": "bekaar",
    # e-commerce vocabulary (Roman Urdu + misspelled English)
    "delivry": "delivery", "dlvery": "delivery", "delvery": "delivery",
    "parxel": "parcel", "parsal": "parcel", "parsel": "parcel",
    "prodct": "product", "prodact": "product", "pruduct": "product",
    "qlty": "quality", "qulity": "quality", "qualty": "quality",
    "prise": "price", "prce": "price",
    "pakaging": "packing", "paking": "packing", "packaing": "packing",
    "orginal": "original", "orignal": "original", "origanal": "original",
    "recomend": "recommend", "recomond": "recommend", "recamend": "recommend",
    "seler": "seller", "sellar": "seller",
    "mje": "mujhe", "mujhy": "mujhe",
}


def normalize(text: str) -> str:
    """Normalize one raw review into clean, canonical lowercase tokens."""
    if not text:
        return ""
    text = text.lower()
    text = _URL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(r"\1", text)        # keep the word, drop the '#'
    text = _NOISE_CHAR_RE.sub(" ", text)       # emoji, U+FFFD, punctuation
    text = text.replace("_", " ")
    text = _REPEAT_RE.sub(r"\1", text)         # 'bohoooot' -> 'bohot'
    tokens = [VARIANT_MAP.get(tok, tok) for tok in text.split()]
    return " ".join(tokens).strip()


# --- inline test cases --------------------------------------------------

if __name__ == "__main__":
    _CASES = [
        # repeated-character collapse + intensifier canonicalization
        ("Bohoooot acha product hai!!",
         "bohat acha product hai"),
        # abbreviations + misspelled commerce words
        ("product ki qlty bht khrab hai, delivry bhi late thi",
         "product ki quality bohat kharab hai delivery bhi late thi"),
        # URL + mention + emoji noise stripping
        ("nice product https://daraz.pk/p/123 @daraz bohat achi quality \U0001f60d\U0001f60d",
         "nice product bohat achi quality"),
        # negation variants and encoding garbage
        ("bilkul fake cheez hai, nhi kharidna chahiy\ufffd",
         "bilkul fake cheez hai nahi kharidna chahiy"),
    ]
    for raw, expected in _CASES:
        got = normalize(raw)
        assert got == expected, f"normalize({raw!r}) = {got!r}, expected {expected!r}"
        print(f"PASS: {raw!r} -> {got!r}")
    print(f"All {len(_CASES)} normalizer tests passed.")
