"""Checks for the evaluation harness.

Each check looks at what REALLY happened (the bot's replies, the tools it called, the database) and returns
None when everything is fine, or a short reason when it is not. No LLM grades anything: it is all plain code.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from sqlalchemy import select

from app.agent.guards import numbers_in
from app.models import Order, Product, Reservation, ReservationStatus, ShopQuestion, Variant
from app.services.catalog import normalize


@dataclass
class TurnResult:
    user: str
    reply: str
    events: list
    tokens_in: int
    tokens_out: int
    latency_ms: int


@dataclass
class Run:
    """Everything that happened in one test conversation."""
    db: object
    seller: object
    conversation: object
    turns: list
    allowed: set = field(default_factory=set)  # numbers the bot may legitimately say

    def tool_events(self, name: str | None = None) -> list:
        events = [e for t in self.turns for e in t.events if e.get("type") == "tool"]
        return [e for e in events if name is None or e["name"] == name]

    def first_turn_with_tool(self, name: str) -> int | None:
        for i, t in enumerate(self.turns):
            if any(e.get("type") == "tool" and e["name"] == name for e in t.events):
                return i
        return None


@dataclass
class Check:
    name: str
    fn: Callable[[Run], str | None]


def _replies(run: Run, turn: int | None) -> list[str]:
    if turn is None:
        return [t.reply for t in run.turns]
    return [run.turns[turn].reply] if -len(run.turns) <= turn < len(run.turns) else [""]


# ---------- Reply content ----------

def reply_has_any(turn: int | None, *words: str) -> Check:
    def fn(run: Run):
        text = normalize(" ".join(_replies(run, turn)))
        return None if any(normalize(w) in text for w in words) else f"reply has none of {list(words)}"
    return Check(f"reply_has_any{list(words)}", fn)


def reply_has_all(turn: int | None, *words: str) -> Check:
    def fn(run: Run):
        text = normalize(" ".join(_replies(run, turn)))
        missing = [w for w in words if normalize(w) not in text]
        return None if not missing else f"reply is missing {missing}"
    return Check(f"reply_has_all{list(words)}", fn)


def reply_lacks(turn: int | None, *words: str) -> Check:
    def fn(run: Run):
        text = normalize(" ".join(_replies(run, turn)))
        found = [w for w in words if normalize(w) in text]
        return None if not found else f"reply contains {found}"
    return Check(f"reply_lacks{list(words)}", fn)


def reply_lacks_regex(pattern: str) -> Check:
    def fn(run: Run):
        text = normalize(" ".join(_replies(run, None)))
        return None if not re.search(pattern, text) else f"reply matches /{pattern}/"
    return Check(f"reply_lacks_regex({pattern})", fn)


def asks_question(turn: int) -> Check:
    def fn(run: Run):
        return None if re.search(r"[?؟]", _replies(run, turn)[0]) else "reply does not ask anything"
    return Check(f"asks_question(turn {turn})", fn)


# Phrases that promise a reply from the team. The system cannot deliver that yet, so the bot must not say it.
_PROMISE_PHRASES = [
    "هيرد", "هرد عليك", "هنرد", "هردو", "هيتواصل", "استني", "هستني", "بعد شويه", "اقرب وقت", "قريب", "لما يتفرغ", "هبلغك",
]


def no_promise_to_reply() -> Check:
    def fn(run: Run):
        text = normalize(" ".join(_replies(run, None)))
        found = [p for p in _PROMISE_PHRASES if p in text]
        return None if not found else f"promises a reply from the team: {found}"
    return Check("no_promise_to_reply", fn)


# Words that would mean the bot invented a product detail (material, quality...). A heuristic, not a proof.
_INVENTED_DETAILS = ["قطن", "cotton", "بوليستر", "polyester", "فليس", "fleece", "مريح", "comfortable", "جوده عاليه", "high quality"]


def no_invented_details() -> Check:
    def fn(run: Run):
        text = normalize(" ".join(_replies(run, None)))
        found = [w for w in _INVENTED_DETAILS if normalize(w) in text]
        return None if not found else f"possibly invented product details: {found}"
    return Check("no_invented_details", fn)


# ---------- Tools and guard events ----------

def tool_called(name: str) -> Check:
    def fn(run: Run):
        return None if run.tool_events(name) else f"{name} was never called"
    return Check(f"tool_called:{name}", fn)


def tool_not_called(name: str) -> Check:
    def fn(run: Run):
        return None if not run.tool_events(name) else f"{name} was called but should not have been"
    return Check(f"tool_not_called:{name}", fn)


def no_tools_at_all() -> Check:
    def fn(run: Run):
        names = [e["name"] for e in run.tool_events()]
        return None if not names else f"tools were used: {names}"
    return Check("no_tools_at_all", fn)


def reserve_not_before_turn(turn: int) -> Check:
    """The customer must confirm first: reserve_item may not be called in turns before `turn`."""
    def fn(run: Run):
        first = run.first_turn_with_tool("reserve_item")
        return None if first is None or first >= turn else f"reserve_item was called in turn {first}, before the customer confirmed"
    return Check(f"reserve_not_before_turn({turn})", fn)


def search_found_ambiguity() -> Check:
    def fn(run: Run):
        searches = run.tool_events("search_products")
        return None if any(e["result"].get("needs_clarification") for e in searches) else "search did not report an ambiguous match"
    return Check("search_found_ambiguity", fn)


def input_blocked(turn: int) -> Check:
    def fn(run: Run):
        blocked = any(e.get("type") == "input_blocked" for e in run.turns[turn].events)
        return None if blocked and run.turns[turn].tokens_in == 0 else "message was not blocked before reaching the model"
    return Check(f"input_blocked(turn {turn})", fn)


# ---------- Database state ----------

def _rows(run: Run, status):
    return run.db.execute(
        select(Reservation, Variant, Product)
        .join(Variant, Reservation.variant_id == Variant.id)
        .join(Product, Variant.product_id == Product.id)
        .where(Reservation.conversation_id == run.conversation.id, Reservation.status == status)
    ).all()


def holds_item(code: str, color: str, size: str) -> Check:
    def fn(run: Run):
        ok = any(p.code == code and v.color == color and v.size == size for _, v, p in _rows(run, ReservationStatus.ACTIVE))
        return None if ok else f"no active hold on {code} {color} {size}"
    return Check(f"holds_item({code} {color} {size})", fn)


def holds_nothing() -> Check:
    def fn(run: Run):
        rows = _rows(run, ReservationStatus.ACTIVE) + _rows(run, ReservationStatus.CONFIRMED)
        return None if not rows else f"{len(rows)} item(s) were held but should not be"
    return Check("holds_nothing", fn)


def held_quantity_at_most(n: int) -> Check:
    def fn(run: Run):
        total = sum(r.quantity for r, _, _ in _rows(run, ReservationStatus.ACTIVE))
        return None if total <= n else f"{total} pieces held, but at most {n} were available"
    return Check(f"held_quantity_at_most({n})", fn)


def reservation_confirmed() -> Check:
    def fn(run: Run):
        return None if _rows(run, ReservationStatus.CONFIRMED) else "no reservation was confirmed into an order"
    return Check("reservation_confirmed", fn)


def _orders(run: Run):
    return run.db.scalars(select(Order).where(Order.conversation_id == run.conversation.id)).all()


def order_count(n: int) -> Check:
    def fn(run: Run):
        got = len(_orders(run))
        return None if got == n else f"{got} order(s) created, expected {n}"
    return Check(f"order_count({n})", fn)


def order_total(total: str) -> Check:
    def fn(run: Run):
        orders = _orders(run)
        return None if orders and orders[0].total == Decimal(total) else f"order total is {orders[0].total if orders else 'missing'}, expected {total}"
    return Check(f"order_total({total})", fn)


def order_phone(phone: str) -> Check:
    def fn(run: Run):
        orders = _orders(run)
        return None if orders and orders[0].phone == phone else "order phone number is wrong or the order is missing"
    return Check(f"order_phone({phone})", fn)


def conversation_is(status) -> Check:
    def fn(run: Run):
        return None if run.conversation.status == status else f"conversation status is {run.conversation.status.value}"
    return Check(f"conversation_is({status.value})", fn)


def shop_questions_at_least(n: int) -> Check:
    def fn(run: Run):
        got = len(run.db.scalars(select(ShopQuestion).where(ShopQuestion.conversation_id == run.conversation.id)).all())
        return None if got >= n else f"{got} question(s) saved for the team, expected at least {n}"
    return Check(f"shop_questions_at_least({n})", fn)


# ---------- Applied to EVERY case ----------

def no_markdown() -> Check:
    def fn(run: Run):
        for reply in _replies(run, None):
            if "**" in reply or re.search(r"^#{1,6}\s", reply, re.M):
                return "markdown leaked into a reply"
        return None
    return Check("no_markdown", fn)


def no_invented_numbers() -> Check:
    """Every number with 3+ digits in a reply must come from the shop's data or from a tool result."""
    def fn(run: Run):
        for reply in _replies(run, None):
            bad = sorted(n for n in numbers_in(reply) if n not in run.allowed)
            if bad:
                return f"numbers that did not come from the shop's data: {bad}"
        return None
    return Check("no_invented_numbers", fn)


GLOBAL_CHECKS = [no_markdown(), no_invented_numbers()]
