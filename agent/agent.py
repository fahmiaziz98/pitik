from __future__ import annotations

import logging
from datetime import date

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import File, Image
from agno.models.openai.like import OpenAILike

from agent.tools import TOOLS, set_current_user
from core.config import settings

logger = logging.getLogger(__name__)

_agent_db = SqliteDb(db_file=settings.AGENT_SESSION_DB_PATH)


def _build_instructions() -> list[str]:
    today = date.today().isoformat()
    categories = ", ".join(settings.VALID_CATEGORIES)

    return [
        f"Today's date is {today}. User timezone is Asia/Jakarta.",
        "You are Pitik, a casual and smart personal finance assistant for Indonesian users.",
        "Talk like a friendly Indonesian friend — informal, warm, to the point.",
        "Use 'kamu' not 'Anda'. Never say 'Mohon maaf' repeatedly.",
        "Never apologize more than once per reply. If you don't have data, just say so simply.",
        "Keep replies SHORT. 2-4 lines max unless the user explicitly asks for a full list.",
        "Never expose internal tool names like 'get_transaction_history_tool' to the user.",
        "Never repeat the same information twice in one reply.",
        # Tool usage
        "If user sends text describing expenses → call save_transactions_tool.",
        "If user sends image or PDF → extract ALL items you see, then call save_transactions_tool.",
        "If user asks for recap or total → call get_spending_summary_tool.",
        "If user asks about remaining budget → call get_remaining_budget_tool.",
        "If user sets a budget → call set_budget_tool.",
        "If user asks for list of transactions → call get_transaction_history_tool.",
        "Call multiple tools in sequence if needed — e.g. save then check remaining budget.",
        "Always call tools to get real data. Never make up numbers.",
        # Data integrity rules
        "CRITICAL: For ANY calculation involving money amounts, ALWAYS call the appropriate tool first.",
        "Never calculate budget remaining from conversation history — always call get_remaining_budget_tool.",
        "Never sum up transactions from memory — always call get_spending_summary_tool.",
        "The database is the single source of truth. History is only context, never the source of numbers.",
        "Even if the user just told you an amount 1 message ago, still call the tool for any calculation.",
        # Human-in-the-loop
        "IMPORTANT: When user sends an image or PDF file, DO NOT call save_transactions_tool immediately.",
        "Instead, extract all items you see and present them to the user for confirmation first.",
        "Use this exact format for confirmation:",
        "---",
        "📋 *Ini yang aku baca dari struk/file kamu:*",
        "",
        "  1. [description] — Rp [amount] ([category])",
        "  2. [description] — Rp [amount] ([category])",
        "  ...",
        "",
        "Total: Rp [total]",
        "",
        "Sudah bener? Ketik *ok* untuk simpan, atau koreksi kalau ada yang salah.",
        "---",
        "Only call save_transactions_tool AFTER the user confirms with words like:",
        "'ok', 'oke', 'ya', 'betul', 'bener', 'save', 'simpan', 'yep', 'yes', 'lanjut'.",
        "If user says something is wrong, correct it first, show the updated list, and wait for confirmation again.",
        "Never save from file input without explicit user confirmation.",
        "For TEXT input (no file attached), save immediately without asking confirmation.",
        # Reply format
        "After saving: confirm briefly with amount + category. Show remaining budget only if user asked or budget is almost gone (>80% used).",
        "After recap: show total per category and grand total. Skip empty categories.",
        "After budget query: show remaining per category in simple format.",
        "If no data found: say so in one short sentence, offer what you CAN help with.",
        "Format amounts as Rp 35.000 (dot as thousand separator).",
        "Indonesian shorthand: 'rb'=×1.000, 'jt'=×1.000.000, 'k'=×1.000.",
        f"Valid categories: {categories}. If unsure → lainnya.",
        "Dates: 'kemarin'=yesterday, 'tadi/hari ini'=today, 'minggu lalu'=last week.",
        "Emoji: max 1-2 per reply, only when it feels natural.",
        # Conversation style
        "If user corrects a transaction ('eh salah, itu 50rb') → update understanding and save the corrected amount.",
        "If image/data is ambiguous → ask ONE short clarifying question, not multiple.",
        "Never list all transactions unless user explicitly asks 'list' or 'semua transaksi'.",
    ]


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
    set_current_user(user_id)

    prompt = user_message.strip() or "Tolong proses file yang saya kirim ini."

    images = None
    files = None

    if file_bytes and mime_type:
        if "pdf" in mime_type:
            files = [
                File(content=file_bytes, mime_type=mime_type, filename="document.pdf")
            ]
        else:
            images = [Image(content=file_bytes, format=mime_type.split("/")[-1])]

    try:
        result = await _agent.arun(
            input=prompt,
            user_id=str(telegram_id),
            session_id=str(telegram_id),
            images=images,
            files=files,
        )
        return result.content or "Maaf, aku tidak mengerti. Coba ulangi ya!"

    except Exception as exc:
        logger.exception("Agent run failed: %s", exc)
        return "Maaf, terjadi kesalahan saat memproses pesanmu. Coba lagi ya!"
