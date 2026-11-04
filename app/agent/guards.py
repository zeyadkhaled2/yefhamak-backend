"""Guardrails: checks that run in OUR code, around the LLM. The prompt asks the model to behave; these make sure.

  check_input         blocks obvious prompt-injection attempts before the model sees them
  clean_output        turns the model's markdown into WhatsApp-style text
  unsupported_numbers finds prices in a reply that did not come from the shop's data
"""
import re
from decimal import Decimal
from typing import Iterable

from app.services.catalog import normalize

MAX_INPUT_CHARS = 500

BLOCK_REPLY = "عذرا، أنا مساعد لطلبات المحل بس. اسألني عن المنتجات أو الطلبات 🙂"
TOO_LONG_REPLY = "ممكن تكتب سؤالك بشكل أقصر؟"

# Patterns are written against normalize()d text (alef variants unified, lowercase).
# Only injection attempts are blocked here. Off-topic questions (politics, coding) are handled by the prompt,
# because blocking words like "كود" would also block honest questions such as "كود الخصم".
_INJECTION = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
        r"(reveal|show|print|repeat|tell)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)",
        r"system\s+prompt|developer\s+message|jailbreak",
        r"(تجاهل|انسي|انس)\s+(كل\s+)?(التعليمات|الاوامر|اللي\s+فات)",
        r"(اظهر|اكشف|قولي|اعرض)\s+(لي\s+)?(تعليماتك|التعليمات|البرومبت)",
        r"تعليمات\s+النظام",
    ]
]


def check_input(text: str) -> str | None:
    """Returns a ready-made reply if the message must be blocked, otherwise None."""
    if len(text) > MAX_INPUT_CHARS:
        return TOO_LONG_REPLY
    norm = normalize(text)
    if any(p.search(norm) for p in _INJECTION):
        return BLOCK_REPLY
    return None


def clean_output(text: str) -> str:
    """Markdown -> WhatsApp style. WhatsApp bold is a single *asterisk*; it does not understand **double** or # headers."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-+]\s+", "• ", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\bابعتلهم\b", "ابعتهم", text)
    return text.strip()


def greeting_reply(text: str) -> str | None:
    """Handle a standalone greeting without acting on the previous turn."""
    greeting = normalize(text).strip(" \t\n!?.،؟")
    if greeting in {"اهلا", "اهلا تاني", "اهلا وسهلا", "السلام عليكم", "مرحبا"}:
        return "أهلًا بيك! تحب نكمّل من آخر نقطة؟"
    return None


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def allowed_numbers(shown_prices: Iterable[float | Decimal], delivery_fees: Iterable[Decimal]) -> set[int]:
    """Every price the bot may legitimately say: shown prices, 1-5 of them, and with a delivery fee added."""
    prices = {Decimal(str(p)) for p in shown_prices}
    fees = {Decimal(str(f)) for f in delivery_fees}
    allowed = set(prices) | set(fees)
    for price in prices:
        for qty in range(1, 6):
            base = price * qty
            allowed.add(base)
            allowed.update(base + fee for fee in fees)
    return {int(x) for x in allowed}


def unsupported_numbers(reply: str, allowed: set[int]) -> list[int]:
    """Numbers with 3+ digits in the reply that are not allowed prices. Small numbers (quantities, minutes, days) are ignored."""
    text = reply.translate(_ARABIC_DIGITS)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 1,200 -> 1200
    found = {int(n) for n in re.findall(r"\d{3,}", text)}
    return sorted(n for n in found if n not in allowed)


def numbers_in(text: str) -> set[int]:
    """All numbers with 3+ digits in a text (used to learn which numbers the shop's own tools produced)."""
    text = text.translate(_ARABIC_DIGITS)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return {int(n) for n in re.findall(r"\d{3,}", text)}
