from __future__ import annotations

from datetime import date

import structlog
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import File, Image
from agno.models.openai.like import OpenAILike

from agent.tools import TOOLS, set_current_user
from core.config import settings

logger = structlog.get_logger(__name__)

_agent_db = SqliteDb(db_file=settings.AGENT_SESSION_DB_PATH)


_SYSTEM_PROMPT_TEMPLATE = """
# Identity
You are Pitik, a casual and smart personal finance assistant for Indonesian users.
Today's date: {today}. Timezone: Asia/Jakarta.

# Personality
- Talk like a friendly Indonesian friend — informal, warm, to the point
- Use "kamu" not "Anda". Never say "Mohon maaf" repeatedly
- Keep replies SHORT — 2-4 lines max unless user explicitly asks for detail
- Never expose internal tool names (e.g. never say "get_remaining_budget")
- Never repeat the same information twice in one reply

# Tool Rules

## CRITICAL — Always use tools for any numbers, never use conversation memory
- Any expense/income mentioned → save_transactions
- Any image or PDF sent → extract ALL items you see, show for confirmation, DO NOT save yet
- Budget question → get_remaining_budget
- Recap/summary → get_spending_summary
- List of transactions → get_transaction_history
- Setting a budget → set_budget
- Chain tools when needed (e.g. save → then check remaining)

## Human-in-the-loop for file inputs
When user sends an image or PDF:
1. Extract all line items you can see
2. Show them in this format and ask for confirmation — do NOT call save yet:

📋 Ini yang aku baca:

  1. [description] — Rp [amount] ([category])
  2. [description] — Rp [amount] ([category])

Total: Rp [total]

Udah bener? Ketik *ok* untuk simpan.

3. Only call save_transactions_tool after user confirms

## Amount parsing
- "rb" or "ribu" → ×1.000 (e.g. 35rb = 35000)
- "jt" or "juta" → ×1.000.000 (e.g. 1.5jt = 1500000)
- "k" → ×1.000 (e.g. 45k = 45000)

## Date parsing
- "hari ini" or "tadi" → today
- "kemarin" → yesterday
- "minggu lalu" → last week

## Valid categories
{categories}
When unsure → use "lainnya"

# Reply Format
- After saving: confirm briefly — amount + category. Show remaining budget only if asked or >80% used
- After recap: total per category + grand total. Skip empty categories
- After budget query: remaining per category, simple format
- No data found: one short sentence, offer what you can help with
- Amounts: always Rp 35.000 format (dot as thousand separator)
- Emoji: max 1-2 per reply, only when natural
"""


def _build_instructions() -> str:
    """Render system prompt with today's date and valid categories."""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        today=date.today().isoformat(),
        categories=", ".join(settings.VALID_CATEGORIES),
    )


def _build_agent() -> Agent:
    """
    Construct the Agno Agent with the configured LLM provider, tools,
    and SQLite-backed session storage.

    Returns:
        Configured Agent instance.

    """

    model = OpenAILike(
        id=settings.MODEL_ID,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    return Agent(
        name="Pitik",
        model=model,
        db=_agent_db,
        tools=TOOLS,
        instructions=_build_instructions(),
        add_history_to_context=True,
        num_history_runs=5,
        markdown=False,
        telemetry=False,
    )


_agent = _build_agent()


async def run(
    user_message: str,
    user_id: str,
    telegram_id: int,
    file_bytes: bytes | None = None,
    mime_type: str | None = None,
) -> str:
    """
    Run the Pitik agent for one user turn.

    Args:
        user_message: The user's text input. Pass an empty string if
            the user only sent a file with no caption.
        user_id: Internal DB user UUID, used to scope tool calls to
            the correct user's data.
        telegram_id: The user's Telegram ID, used as the Agno
            session_id so conversation history persists per-user
            across restarts.
        file_bytes: Optional raw bytes of an image or PDF.
        mime_type: MIME type of the file, e.g. 'image/jpeg' or
            'application/pdf'. Required if file_bytes is provided.

    Returns:
        The agent's final text reply, ready to send to the user.

    Example:
        >>> reply = await run("makan siang 35rb", user_id="abc-123", telegram_id=987654)
        >>> print(reply)
        '✅ Tercatat! 🍽️ makanan: -Rp 35.000'
    """
    log = logger.bind(user_id=user_id, telegram_id=telegram_id)

    set_current_user(user_id)

    prompt = user_message.strip() or "Tolong proses file yang saya kirim ini."

    images = None
    files = None

    if file_bytes and mime_type:
        if "pdf" in mime_type:
            files = [
                File(content=file_bytes, mime_type=mime_type, filename="document.pdf")
            ]
            log.info(
                "agent_input", type="pdf", size_kb=round(len(file_bytes) / 1024, 1)
            )
        else:
            images = [Image(content=file_bytes, format=mime_type.split("/")[-1])]
            log.info(
                "agent_input", type="image", size_kb=round(len(file_bytes) / 1024, 1)
            )

    try:
        result = await _agent.arun(
            input=prompt,
            user_id=str(telegram_id),
            session_id=str(telegram_id),
            images=images,
            files=files,
        )
        reply = result.content or "Maaf, aku tidak mengerti. Coba ulangi ya!"
        log.info("agent_reply", preview=reply[:80])
        return reply

    except Exception as exc:
        log.error("agent_run_failed", error=str(exc), exc_info=True)
        return "Maaf, terjadi kesalahan saat memproses pesanmu. Coba lagi ya!"
