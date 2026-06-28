from __future__ import annotations

import logging
from io import BytesIO

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent.agent import run as agent_run
from core.config import settings
from db.client import DatabaseError, get_or_create_user

logger = logging.getLogger(__name__)

_pending_confirmations: dict[int, str] = {}

CONFIRM_KEYWORDS = {
    "ok",
    "oke",
    "ya",
    "yep",
    "yes",
    "betul",
    "bener",
    "save",
    "simpan",
    "lanjut",
    "iya",
}
REJECT_KEYWORDS = {"batal", "cancel", "gak", "tidak", "no", "hapus"}


async def _resolve_user(update: Update) -> dict | None:
    """
    Ensure the Telegram user exists in the database.

    Args:
        update: Incoming Telegram update.

    Returns:
        User record dict, or None if resolution fails.
    """
    tg_user = update.effective_user
    if not tg_user:
        return None
    name = tg_user.first_name or tg_user.username or "User"
    try:
        return await get_or_create_user(tg_user.id, name)
    except DatabaseError as exc:
        logger.error("User resolution failed: %s", exc)
        return None


async def _reply(update: Update, text: str) -> None:
    """Send a plain-text reply to the user."""
    await update.message.reply_text(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command — greet the user."""
    name = update.effective_user.first_name if update.effective_user else "kamu"
    await _reply(
        update,
        f"Halo {name}! Aku Pitik, asisten keuanganmu.\n\n"
        "Apa yang bisa aku bantu?\n\n"
        "Ketik pengeluaran:\n"
        "  → 'makan siang 35rb'\n"
        "  → 'belanja bahan pokok 256rb, transport 20rb'\n\n"
        "Kirim foto struk atau PDF invoice\n\n"
        "Set budget:\n"
        "  → 'budget makan 1.5jt, transport 500rb'\n\n"
        "Lihat rekap:\n"
        "  → 'rekap minggu ini'\n"
        "  → 'sisa budget makan'\n\n"
        "/help untuk panduan lengkap",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command — display usage guide."""
    await _reply(
        update,
        "Panduan Pitik\n\n"
        "CATAT PENGELUARAN\n"
        "  'beli kopi 35rb'\n"
        "  'makan 50k, ojek 15k'\n"
        "  kirim foto struk / PDF\n\n"
        "SET BUDGET\n"
        "  'budget makan bulan ini 1.5 juta'\n"
        "  'budget bulanan 5jt'\n\n"
        "CEK SALDO\n"
        "  'sisa budget'\n"
        "  'rekap hari ini'\n"
        "  'rekap bulan ini'\n"
        "  'transaksi minggu ini'\n\n"
        "Kategori: makanan, transport, tagihan,\n"
        "kesehatan, belanja, hiburan, tabungan, lainnya\n\n"
        "Pitik mengingat percakapanmu, jadi kamu bisa\n"
        "kirim koreksi seperti 'eh salah, itu 50rb' ya!",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text — including confirmation replies for pending file extractions."""
    user = await _resolve_user(update)
    if not user:
        await _reply(update, "Gagal mengenali user. Coba /start dulu ya!")
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    tg_id = update.effective_user.id
    await update.message.chat.send_action("typing")

    if tg_id in _pending_confirmations:
        first_word = text.lower().split()[0] if text else ""

        if first_word in CONFIRM_KEYWORDS:
            pending_context = _pending_confirmations.pop(tg_id)
            reply = await agent_run(
                user_message=f"User confirmed. Please save these transactions now: {pending_context}",
                user_id=user["id"],
                telegram_id=tg_id,
            )
            await _reply(update, reply)
            return

        elif first_word in REJECT_KEYWORDS:
            _pending_confirmations.pop(tg_id)
            await _reply(update, "Oke, dibatalin ya! Kirimin ulang kalau mau dicatat.")
            return

        else:
            pending_context = _pending_confirmations.pop(tg_id)
            reply = await agent_run(
                user_message=(
                    f"User wants to correct this: {text}. "
                    f"Original extracted data was: {pending_context}. "
                    f"Show the corrected list and ask for confirmation again before saving."
                ),
                user_id=user["id"],
                telegram_id=tg_id,
            )
            _pending_confirmations[tg_id] = reply
            await _reply(update, reply)
            return

    reply = await agent_run(
        user_message=text,
        user_id=user["id"],
        telegram_id=tg_id,
    )
    await _reply(update, reply)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo — extract, show to user, wait for confirmation."""
    user = await _resolve_user(update)
    if not user:
        await _reply(update, "Gagal mengenali user. Coba /start dulu ya!")
        return

    await update.message.chat.send_action("typing")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = BytesIO()
        await file.download_to_memory(buf)
        file_bytes = buf.getvalue()

        caption = update.message.caption or ""
        tg_id = update.effective_user.id

        reply = await agent_run(
            user_message=caption,
            user_id=user["id"],
            telegram_id=tg_id,
            file_bytes=file_bytes,
            mime_type="image/jpeg",
        )

        _pending_confirmations[tg_id] = reply
        await _reply(update, reply)

    except Exception as exc:
        logger.exception("handle_photo error: %s", exc)
        await _reply(update, "Gagal memproses foto. Pastikan foto terlihat jelas ya!")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document — extract, show to user, wait for confirmation."""
    user = await _resolve_user(update)
    if not user:
        await _reply(update, "Gagal mengenali user. Coba /start dulu ya!")
        return

    doc = update.message.document
    if not doc:
        return

    mime = doc.mime_type or ""
    allowed = settings.SUPPORTED_IMAGE_TYPES | settings.SUPPORTED_DOC_TYPES

    if mime not in allowed:
        await _reply(
            update, f"Format tidak didukung: {mime}\nKirim JPG, PNG, atau PDF ya!"
        )
        return

    if doc.file_size and doc.file_size > settings.MAX_FILE_SIZE_BYTES:
        await _reply(
            update, f"File terlalu besar (maks {settings.MAX_FILE_SIZE_MB}MB)."
        )
        return

    await update.message.chat.send_action("typing")

    try:
        file = await context.bot.get_file(doc.file_id)
        buf = BytesIO()
        await file.download_to_memory(buf)
        file_bytes = buf.getvalue()

        caption = update.message.caption or ""
        tg_id = update.effective_user.id

        reply = await agent_run(
            user_message=caption,
            user_id=user["id"],
            telegram_id=tg_id,
            file_bytes=file_bytes,
            mime_type=mime,
        )

        _pending_confirmations[tg_id] = reply
        await _reply(update, reply)

    except Exception as exc:
        logger.exception("handle_document error: %s", exc)
        await _reply(update, "Gagal memproses file. Coba lagi ya!")


def build_app() -> Application:
    """
    Construct and configure the Telegram Application with all handlers.

    Returns:
        Configured Application instance, ready to run.
    """
    app = Application.builder().token(settings.telegram_api_key).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    return app
