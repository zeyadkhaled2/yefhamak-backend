"""Runs the evaluation cases against the bot and prints a report.

    python -m evals.run --quick              the 8 most important cases
    python -m evals.run                      everything
    python -m evals.run --category order_flow
    python -m evals.run --case full-order
    python -m evals.run --repeat 3           run each case 3 times (LLMs are not perfectly repeatable)
    python -m evals.run --price-in 0.15 --price-out 0.60     USD per 1M tokens, to estimate cost per conversation

WARNING: every case resets the Demo Store (it re-runs the seed), so earlier test orders and chats are deleted.
"""
import argparse
import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.agent.guards import allowed_numbers, numbers_in
from app.agent.loop import handle_message
from app.core.config import settings
from app.db.session import SessionLocal
from evals.cases import CASES, Case
from evals.checks import GLOBAL_CHECKS, Run, TurnResult
from app.models import (
    ChannelType,
    Conversation,
    Customer,
    DeliveryZone,
    Message,
    MessageDirection,
    Product,
    Seller,
)
from app.demo.seed import DEMO_NAME, seed

RESULTS_DIR = Path("eval_results")

# Problems on the provider's side. Anything else that crashes is a bug in OUR code and is counted as a failure.
_INFRA_ERRORS = ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError", "EmptyProviderResponse")


def is_infra_error(error: str) -> bool:
    return error.startswith(_INFRA_ERRORS)


def is_daily_limit(error: str) -> bool:
    return error.startswith("RateLimitError") and "per-day" in error.lower()


def compute_allowed(db, seller, conversation, turns) -> set[int]:
    """Numbers the bot may say: shop prices (x quantity, + delivery), anything a tool produced, the customer's phone."""
    prices = db.scalars(select(Product.price).where(Product.seller_id == seller.id)).all()
    fees = db.scalars(select(DeliveryZone.fee).where(DeliveryZone.seller_id == seller.id)).all()
    allowed = set(allowed_numbers(prices, fees))
    for turn in turns:
        allowed |= {n for n in numbers_in(turn.user) if n >= 10**8}  # phone numbers typed by the customer
        for event in turn.events:
            if event.get("type") == "tool":
                allowed |= numbers_in(json.dumps(event["result"], ensure_ascii=False, default=str))
                if event["name"] == "create_order":
                    allowed |= numbers_in(event["args"])
    allowed |= numbers_in(json.dumps((conversation.state or {}).get("last_order", {})))
    return allowed


def run_case(case: Case) -> dict:
    seed(quiet=True)  # a fresh store for every case, so cases cannot affect each other
    db = SessionLocal()
    try:
        seller = db.scalar(select(Seller).where(Seller.name == DEMO_NAME))
        customer = Customer(seller_id=seller.id, channel_type=ChannelType.WHATSAPP, external_id=f"eval-{uuid.uuid4().hex[:8]}")
        db.add(customer)
        db.flush()
        conversation = Conversation(seller_id=seller.id, customer_id=customer.id)
        db.add(conversation)
        db.commit()

        if case.setup:
            case.setup(db, seller)

        turns: list[TurnResult] = []
        for text in case.turns:
            trace: list = []
            reply = handle_message(db, seller, conversation, text, trace=trace)
            out = None
            if reply:
                out = db.scalar(
                    select(Message)
                    .where(Message.conversation_id == conversation.id, Message.direction == MessageDirection.OUT)
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            turns.append(TurnResult(
                user=text,
                reply=reply,
                events=trace,
                tokens_in=(out.tokens_in or 0) if out else 0,
                tokens_out=(out.tokens_out or 0) if out else 0,
                latency_ms=(out.latency_ms or 0) if out else 0,
            ))
            if any(is_daily_limit(e.get("error", "")) for e in trace if e.get("type") == "error"):
                break  # No more requests, even within this conversation, once today's quota is gone.

        run = Run(db=db, seller=seller, conversation=conversation, turns=turns)
        run.allowed = compute_allowed(db, seller, conversation, turns)

        all_errors = [e["error"] for t in turns for e in t.events if e.get("type") == "error"]
        infra_errors = [e for e in all_errors if is_infra_error(e)]
        crashes = [e for e in all_errors if not is_infra_error(e)]
        failures = [f"crashed: {c}" for c in crashes]
        for check in GLOBAL_CHECKS + case.checks:
            reason = check.fn(run)
            if reason:
                failures.append(f"{check.name}: {reason}")

        status = "fail" if crashes else ("error" if infra_errors else ("pass" if not failures else "fail"))
        return {
            "id": case.id,
            "category": case.category,
            "status": status,
            "failures": failures,
            "infra_errors": infra_errors,
            "quota_exhausted": any(is_daily_limit(e) for e in infra_errors),
            "tokens_in": sum(t.tokens_in for t in turns),
            "tokens_out": sum(t.tokens_out for t in turns),
            "latency_ms": [t.latency_ms for t in turns if t.latency_ms],
            "turns": [
                {
                    "user": t.user,
                    "reply": t.reply,
                    "tools": [e["name"] for e in t.events if e.get("type") == "tool"],
                    "guards": [e["type"] for e in t.events if e.get("type") not in ("tool",)],
                }
                for t in turns
            ],
        }
    finally:
        db.close()


def print_failure(result: dict) -> None:
    print(f"      why it failed:")
    for f in result["failures"]:
        print(f"        - {f}")
    for t in result["turns"]:
        tools = f"  [tools: {', '.join(t['tools'])}]" if t["tools"] else ""
        guards = f"  [guards: {', '.join(t['guards'])}]" if t["guards"] else ""
        print(f"      You: {t['user']}")
        print(f"      Bot: {t['reply'][:300]}{tools}{guards}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--category")
    parser.add_argument("--case")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--price-in", type=float, help="USD per 1M input tokens")
    parser.add_argument("--price-out", type=float, help="USD per 1M output tokens")
    args = parser.parse_args()

    cases = CASES
    if args.quick:
        cases = [c for c in cases if c.quick]
    if args.category:
        cases = [c for c in cases if c.category == args.category]
    if args.case:
        cases = [c for c in cases if c.id == args.case]
    if not cases:
        print("No cases match. Categories:", sorted({c.category for c in CASES}))
        return

    print(f"Model: {settings.llm_model}")
    print(f"Running {len(cases)} case(s) x {args.repeat}. Each case resets the Demo Store.\n")

    results = []
    stopped = False
    for case in cases:
        if stopped:
            break
        for i in range(args.repeat):
            result = run_case(case)
            results.append(result)
            label = {"pass": "PASS ", "fail": "FAIL ", "error": "ERROR"}[result["status"]]
            suffix = f" (run {i + 1})" if args.repeat > 1 else ""
            print(f"{label} [{case.category}] {case.id}{suffix}")
            if result["status"] == "fail":
                print_failure(result)
            elif result["status"] == "error":
                print(f"      API problem (not counted as a failure): {result['infra_errors'][0][:160]}")
            if result["quota_exhausted"]:
                completed = {c.id: sum(r["id"] == c.id and not r["quota_exhausted"] for r in results) for c in cases}
                left = [f"{c.id} ({args.repeat - completed[c.id]} run(s) remaining)" for c in cases if completed[c.id] < args.repeat]
                print("\nSTOPPED: the daily free-model limit is used up. Results so far are saved below.")
                print("Run again after it resets (or after adding credits). Still to complete: " + (", ".join(left) or "none"))
                stopped = True
                break

    # ---------- Report ----------
    graded = [r for r in results if r["status"] != "error"]
    passed = [r for r in graded if r["status"] == "pass"]
    errors = [r for r in results if r["status"] == "error"]

    print("\n" + "=" * 50)
    print(f"RESULT: {len(passed)}/{len(graded)} conversations passed"
          + (f"  ({len(errors)} skipped because of API errors)" if errors else ""))

    by_category = defaultdict(lambda: [0, 0])
    for r in graded:
        by_category[r["category"]][1] += 1
        by_category[r["category"]][0] += r["status"] == "pass"
    print("\nBy category:")
    for category, (ok, total) in sorted(by_category.items()):
        print(f"  {category:<14} {ok}/{total}  ({100 * ok // total}%)")

    if graded:
        tokens_in = sum(r["tokens_in"] for r in graded) / len(graded)
        tokens_out = sum(r["tokens_out"] for r in graded) / len(graded)
        latencies = [ms for r in graded for ms in r["latency_ms"]]
        print(f"\nAverage per conversation: {tokens_in:.0f} input tokens, {tokens_out:.0f} output tokens")
        if latencies:
            print(f"Reply time per message: average {sum(latencies) / len(latencies) / 1000:.1f}s, slowest {max(latencies) / 1000:.1f}s")
        if args.price_in is not None and args.price_out is not None:
            cost = (tokens_in * args.price_in + tokens_out * args.price_out) / 1_000_000
            print(f"Estimated cost per conversation: ${cost:.5f}")

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"model": settings.llm_model, "stopped_on_daily_limit": stopped,
                                "remaining": left if stopped else [], "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull transcripts saved to {path}")


if __name__ == "__main__":
    main()
