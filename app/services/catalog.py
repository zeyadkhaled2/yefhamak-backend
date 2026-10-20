"""Product search: turns what a customer typed into candidate products.

The search never decides for the customer. It returns candidates, and when more than one
product matches it sets needs_clarification=True so the bot must ask which one they mean.
"""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Product

# ---------- Text normalization (Arabic spelling variants -> one form) ----------

_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")  # tashkeel + tatweel
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_TOKEN_RE = re.compile(r"[a-z0-9\u0621-\u064a]+")


def normalize(text: str) -> str:
    text = text.lower().translate(_ARABIC_DIGITS)
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآ]", "ا", text)
    return text.replace("ى", "ي").replace("ة", "ه")


# ---------- Starter dictionaries (extend these as you see real messages) ----------

_RAW_SYNONYMS = {
    # product types
    "هودي": "hoodie", "هوديز": "hoodie", "هوديي": "hoodie", "hoodie": "hoodie", "hoodies": "hoodie",
    "hodi": "hoodie", "hoodi": "hoodie",
    "بنطلون": "trousers", "بنطلونات": "trousers", "بنطال": "trousers", "pants": "trousers",
    "trousers": "trousers", "bantalon": "trousers", "pantalon": "trousers",
    # colors (Arabic, English, Franco)
    "بني": "brown", "brown": "brown", "bonni": "brown", "bunni": "brown",
    "اسود": "black", "black": "black", "aswad": "black", "aswed": "black",
    "ابيض": "white", "white": "white", "abyad": "white", "abyed": "white",
    "بيج": "beige", "beige": "beige",
    "كحلي": "navy", "navy": "navy",
    "رمادي": "grey", "grey": "grey", "gray": "grey",
    "احمر": "red", "red": "red",
}
SYNONYMS = {normalize(k): v for k, v in _RAW_SYNONYMS.items()}

COLORS = {"brown", "black", "white", "beige", "navy", "grey", "red"}
SIZE_TOKENS = {"xs", "s", "m", "l", "xl", "xxl", "xxxl"}

_RAW_STOPWORDS = [
    # Arabic
    "عايز", "عايزه", "عايزة", "عاوز", "عندكم", "عندك", "فيه", "في", "هل", "ممكن", "لو", "من", "ده", "دي", "دا",
    "بكام", "وبكام", "كام", "مقاس", "مقاسات", "متاح", "متوفر", "موجود", "لسه", "اريد", "ايه", "انا", "عن", "على",
    "علي", "يا", "اهلا", "مرحبا", "سعر", "السعر",
    # English
    "is", "are", "there", "do", "you", "have", "a", "an", "the", "i", "need", "want", "in", "size", "how", "much",
    "price", "available", "stock", "any", "for", "me", "can", "please", "got", "hi", "hello",
]
STOPWORDS = {normalize(w) for w in _RAW_STOPWORDS}


def tokenize(text: str) -> list[str]:
    tokens = []
    for tok in _TOKEN_RE.findall(normalize(text)):
        if tok in STOPWORDS:
            continue
        if tok.startswith("ال") and len(tok) > 4:  # "الهودي" -> "هودي"
            tok = tok[2:]
        tokens.append(SYNONYMS.get(tok, tok))
    return tokens


# ---------- Search ----------

def _product_tokens(product: Product) -> set[str]:
    texts = [product.name, product.category or "", *product.nicknames]
    tokens: set[str] = set()
    for t in texts:
        tokens |= set(tokenize(t))
    tokens |= {SYNONYMS.get(normalize(v.color), normalize(v.color)) for v in product.variants if v.color}
    return tokens


def _variants_payload(product: Product, colors: set[str], sizes: set[str]) -> tuple[list[dict], bool]:
    filtered = [
        v for v in product.variants
        if (not colors or SYNONYMS.get(normalize(v.color), v.color.lower()) in colors)
        and (not sizes or v.size.upper() in sizes)
    ]
    chosen = filtered or list(product.variants)  # if the filter removes everything, show what exists
    payload = [
        {"variant_id": str(v.id), "color": v.color, "size": v.size, "available": max(v.stock - v.reserved, 0)}
        for v in sorted(chosen, key=lambda v: (v.color, v.size))
    ]
    return payload, bool(filtered)


def search_products(db: Session, seller_id: uuid.UUID, query: str, limit: int = 5) -> dict:
    tokens = tokenize(query)
    sizes = {t.upper() for t in tokens if t.lower() in SIZE_TOKENS}
    content = {t for t in tokens if t not in SIZE_TOKENS}
    colors = content & COLORS

    empty = {"matches": [], "count": 0, "needs_clarification": False, "full_match": False}
    if not content:
        return {**empty, "reason": "empty_query"}

    products = db.scalars(
        select(Product)
        .where(Product.seller_id == seller_id, Product.active.is_(True))
        .options(selectinload(Product.variants))
    ).all()

    scored = [(len(content & _product_tokens(p)), p) for p in products]
    scored = [(s, p) for s, p in scored if s > 0]
    if not scored:
        return {**empty, "reason": "no_match"}

    best = max(s for s, _ in scored)
    top = [p for s, p in scored if s == best][:limit]

    matches = []
    for p in top:
        variants, options_found = _variants_payload(p, colors, sizes)
        matches.append({
            "product_id": str(p.id),
            "code": p.code,
            "name": p.name,
            "price": float(p.price),
            "photo_url": p.photo_url,
            "variants": variants,
            "matches_requested_options": options_found,
        })

    return {
        "matches": matches,
        "count": len(matches),
        "needs_clarification": len(matches) > 1,  # the bot MUST ask which one
        "full_match": best == len(content),       # False = only part of the request matched
        "requested_sizes": sorted(sizes),
    }
