"""The agent loop: customer message -> LLM -> (tools) -> LLM -> reply, with guardrails around it.

  1. Save the customer's message. A blocked message gets a canned reply and never reaches the LLM.
  2. Send the LLM the instructions, the recent chat, and the list of tools.
  3. If the LLM asks to use a tool, run it, give the result back, and ask the LLM again.
  4. When the LLM answers in text, check its numbers (they must come from the shop data or a tool result). One wrong price = one automatic correction. Still wrong = hand off to a human.
  5. Clean the text for WhatsApp, save it, return it.
"""
import json
import time
import traceback
from datetime import datetime, timezone

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.guards import allowed_numbers, check_input, clean_output, greeting_reply, numbers_in, unsupported_numbers
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS, run_tool
from app.core.config import settings
from app.models import Conversation, ConversationStatus, DeliveryZone, Message, MessageDirection, Seller

MAX_STEPS = 6       # most LLM rounds per customer message (stops endless loops)
HISTORY_LIMIT = 12  # how many recent messages the LLM gets to see

HANDOFF_REPLY = "عشان أتأكد من التفاصيل دي، هحولك لفريق المحل وهيرد عليك في أقرب وقت."
TEMP_ERROR_REPLY = "حصلت مشكلة مؤقتة عندنا، ممكن تبعت رسالتك تاني بعد لحظات؟"

_client: OpenAI | None = None


class EmptyProviderResponse(RuntimeError):
    """The model provider answered without any choices (free models do this when the provider is overloaded)."""


def _log(trace: list | None, **event) -> None:
    """Records what happened (tool calls, guard actions, errors) so tests can inspect it. Does nothing when trace is None."""
    if trace is not None:
        trace.append(event)


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is missing in .env")
        _client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=60,
            max_retries=2,
        )
    return _client


def _chat(messages: list[dict]):
    """One LLM call. A reply with no choices is retried a couple of times before we give up."""
    problem = "no choices in the response"
    for attempt in range(3):
        response = get_client().chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=TOOLS,
            temperature=0,
            max_tokens=800,
        )
        if getattr(response, "choices", None):
            return response
        problem = str(getattr(response, "error", None) or problem)[:200]
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    raise EmptyProviderResponse(f"provider returned no answer: {problem}")


def _where(e: Exception) -> str:
    """The file and line where an exception happened, so a crash is easy to find."""
    frames = traceback.extract_tb(e.__traceback__)
    return f"{frames[-1].filename.split(chr(92))[-1].split('/')[-1]}:{frames[-1].lineno} in {frames[-1].name}" if frames else "?"


def _history(db: Session, conversation_id) -> list[dict]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    rows.reverse()
    return [
        {"role": "user" if m.direction == MessageDirection.IN else "assistant", "content": m.body}
        for m in rows
    ]


def _bad_numbers(db: Session, seller: Seller, conversation: Conversation, reply: str, tool_numbers: set[int]) -> list[int]:
    """Numbers in the reply that did not come from the shop's own data or from this turn's tool results."""
    state = conversation.state or {}
    shown = [m["price_egp"] for m in state.get("last_search", [])]
    fees = db.scalars(select(DeliveryZone.fee).where(DeliveryZone.seller_id == seller.id)).all()
    allowed = (
        allowed_numbers(shown, fees)
        | tool_numbers
        | numbers_in(json.dumps(state.get("last_order", {})))
        | numbers_in(json.dumps(state.get("order_preview", {}), ensure_ascii=False))  # the customer's own phone / address
    )
    return unsupported_numbers(reply, allowed)


def _save_reply(db: Session, conversation: Conversation, reply: str, tokens_in=0, tokens_out=0, started=None, model=None) -> None:
    db.add(Message(
        conversation_id=conversation.id,
        direction=MessageDirection.OUT,
        body=reply,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=int((time.time() - started) * 1000) if started else None,
    ))
    db.commit()


def handle_message(
    db: Session,
    seller: Seller,
    conversation: Conversation,
    user_text: str,
    debug: bool = False,
    trace: list | None = None,
) -> str:
    # 1. Save the customer's message
    db.add(Message(conversation_id=conversation.id, direction=MessageDirection.IN, body=user_text))
    conversation.last_customer_message_at = datetime.now(timezone.utc)
    db.commit()

    if conversation.status == ConversationStatus.HANDOFF:
        return ""  # a human has taken over; the bot stays silent

    blocked = check_input(user_text)
    if blocked:
        _log(trace, type="input_blocked")
        if debug:
            print("   [guard] input blocked before reaching the model")
        _save_reply(db, conversation, blocked)
        return blocked

    greeting = greeting_reply(user_text)
    if greeting:
        _save_reply(db, conversation, greeting)
        return greeting

    started = time.time()
    tokens_in = tokens_out = 0
    reply = ""
    corrected = False
    # Numbers the bot may repeat: produced by tools this turn (order totals etc.) or typed by the customer as a phone number
    tool_numbers: set[int] = {n for n in numbers_in(user_text) if n >= 10**8}

    try:
        messages = [{"role": "system", "content": build_system_prompt(db, seller, conversation)}]
        messages += _history(db, conversation.id)

        for _ in range(MAX_STEPS):
            response = _chat(messages)
            if response.usage:
                tokens_in += response.usage.prompt_tokens or 0
                tokens_out += response.usage.completion_tokens or 0

            message = response.choices[0].message

            if not message.tool_calls:  # text: this is the candidate answer
                candidate = (message.content or "").strip()
                bad = _bad_numbers(db, seller, conversation, candidate, tool_numbers) if candidate else []
                if bad and not corrected:  # 4. one automatic correction
                    corrected = True
                    _log(trace, type="number_correction", numbers=bad)
                    if debug:
                        print(f"   [guard] reply contained numbers not in the shop data: {bad}. Asking the model to fix it.")
                    messages.append({"role": "assistant", "content": candidate})
                    messages.append({
                        "role": "user",
                        "content": f"[automatic check] Your reply contained numbers that are not in the tool results: {bad}. "
                                   "Rewrite it using only prices from the search results, or call search_products.",
                    })
                    continue
                reply = "" if bad else candidate  # still wrong after the correction -> hand off below
                break

            # The LLM wants tools: remember its request, run each tool, give the results back
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in message.tool_calls
                ],
            })
            for call in message.tool_calls:
                result = run_tool(db, seller, conversation, call.function.name, call.function.arguments)
                _log(trace, type="tool", name=call.function.name, args=call.function.arguments, result=result)
                if call.function.name == "create_order":
                    tool_numbers |= numbers_in(call.function.arguments)  # the customer's phone and address
                if debug:
                    print(f"   [tool] {call.function.name}({call.function.arguments})")
                    print(f"          -> {json.dumps(result, ensure_ascii=False)[:400]}")
                result_text = json.dumps(result, ensure_ascii=False)
                tool_numbers |= numbers_in(result_text)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

        if not reply:  # no safe answer: give up safely and let a human continue
            _log(trace, type="guard_handoff")
            if debug:
                print("   [guard] no safe answer produced: handing off to a human")
            reply = HANDOFF_REPLY
            conversation.status = ConversationStatus.HANDOFF
            db.commit()
        else:
            reply = clean_output(reply)

    except Exception as e:  # network problem, rate limit on a free model, etc.
        db.rollback()
        _log(trace, type="error", error=f"{type(e).__name__}: {str(e)[:200]} [{_where(e)}]")
        if debug:
            print(f"   [error] {type(e).__name__}: {str(e)[:300]} [{_where(e)}]")
        reply = TEMP_ERROR_REPLY

    _save_reply(db, conversation, reply, tokens_in, tokens_out, started, settings.llm_model)
    return reply
