from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from core.config import settings
from db.models import BudgetData, TransactionData

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


class DatabaseError(Exception):
    """Raised when a database operation fails."""


async def init_db() -> None:
    """
    Apply schema to the SQLite database if not already present.

    Should be called once on application startup.

    Raises:
        DatabaseError: If schema application fails.
    """
    try:
        schema_sql = _SCHEMA_PATH.read_text()
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.executescript(schema_sql)
            await db.commit()
        logger.info("Database schema ready at %s", settings.DATABASE_PATH)
    except Exception as exc:
        logger.error("init_db failed: %s", exc)
        raise DatabaseError("Fail initialize database.") from exc


async def get_or_create_user(telegram_id: int, name: str) -> dict[str, Any]:
    """
    Fetch an existing user or create a new one by Telegram ID.

    Args:
        telegram_id: The user's numeric Telegram ID.
        name: Display name from Telegram.

    Returns:
        User record dictionary.

    Raises:
        DatabaseError: On any database error.
    """
    try:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)

            new_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO users (id, telegram_id, name, created_at) VALUES (?, ?, ?, ?)",
                (new_id, telegram_id, name, datetime.utcnow().isoformat()),
            )
            await db.commit()
            logger.info(f"save user: {new_id}")
            return {
                "id": new_id,
                "telegram_id": telegram_id,
                "name": name,
                "created_at": datetime.utcnow().isoformat(),
            }

    except Exception as exc:
        logger.error("get_or_create_user failed: %s", exc)
        raise DatabaseError("Gagal menyimpan data user.") from exc


async def save_transactions(
    user_id: str,
    transactions: list[TransactionData],
    source: str,
    raw_input: str,
    confidence: str,
) -> list[dict[str, Any]]:
    """
    Persist one or more transactions for a user.

    Args:
        user_id: Internal UUID of the user.
        transactions: List of validated TransactionData objects.
        source: Input source — 'text', 'image', 'pdf', or 'agent'.
        raw_input: Original user message, truncated for storage.
        confidence: AI confidence level.

    Returns:
        List of inserted transaction records.

    Raises:
        DatabaseError: If the insert fails.
    """
    try:
        saved = []
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            for t in transactions:
                new_id = str(uuid.uuid4())
                row = {
                    "id": new_id,
                    "user_id": user_id,
                    "amount": t.amount,
                    "category": t.category,
                    "description": t.description,
                    "date": t.date.isoformat(),
                    "input_type": source,
                    "raw_input": raw_input[:500],
                    "confidence": confidence,
                    "created_at": datetime.utcnow().isoformat(),
                }
                await db.execute(
                    """INSERT INTO transactions
                       (id, user_id, amount, category, description, date,
                        input_type, raw_input, confidence, created_at)
                       VALUES (:id, :user_id, :amount, :category, :description, :date,
                               :input_type, :raw_input, :confidence, :created_at)""",
                    row,
                )
                saved.append(row)
            await db.commit()
        return saved

    except Exception as exc:
        logger.error("save_transactions failed: %s", exc)
        raise DatabaseError("Fail save transaction.") from exc


async def upsert_budgets(
    user_id: str,
    budgets: list[BudgetData],
) -> list[dict[str, Any]]:
    """
    Insert or update budget records.

    Args:
        user_id: Internal UUID of the user.
        budgets: List of validated BudgetData objects.

    Returns:
        List of upserted budget records.

    Raises:
        DatabaseError: If the upsert fails.
    """
    try:
        saved = []
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            for b in budgets:
                new_id = str(uuid.uuid4())
                await db.execute(
                    """INSERT INTO budgets (id, user_id, category, amount, month, year)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id, category, month, year)
                       DO UPDATE SET amount = excluded.amount""",
                    (new_id, user_id, b.category, b.amount, b.month, b.year),
                )
                saved.append(
                    {
                        "category": b.category,
                        "amount": b.amount,
                        "month": b.month,
                        "year": b.year,
                    }
                )
            await db.commit()
        return saved

    except Exception as exc:
        logger.error("upsert_budgets failed: %s", exc)
        raise DatabaseError("Fail save budget.") from exc


async def get_summary(
    user_id: str,
    start_date: date,
    end_date: date,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch aggregated spending for a user within a date range.

    Args:
        user_id: Internal UUID of the user.
        start_date: Inclusive start of the date range.
        end_date: Inclusive end of the date range.
        category: Optional category filter.

    Returns:
        List of records with keys: category, total.

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        query = """
            SELECT category, SUM(amount) as total
            FROM transactions
            WHERE user_id = ? AND date >= ? AND date <= ?
        """
        params: list[Any] = [user_id, start_date.isoformat(), end_date.isoformat()]

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " GROUP BY category ORDER BY category"

        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    except Exception as exc:
        logger.error("get_summary failed: %s", exc)
        raise DatabaseError("Fail fetch transaction summary.") from exc


async def get_budgets(
    user_id: str,
    month: int,
    year: int,
) -> list[dict[str, Any]]:
    """
    Fetch all budget records for a user in a given month.

    Args:
        user_id: Internal UUID of the user.
        month: Month number (1-12).
        year: Four-digit year.

    Returns:
        List of budget records.

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM budgets WHERE user_id = ? AND month = ? AND year = ?",
                (user_id, month, year),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    except Exception as exc:
        logger.error("get_budgets failed: %s", exc)
        raise DatabaseError("Fail get budget data.") from exc


async def get_transaction_history(
    user_id: str,
    start_date: date,
    end_date: date,
    category: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Fetch recent transactions for a user within a date range.

    Args:
        user_id: Internal UUID of the user.
        start_date: Inclusive start date.
        end_date: Inclusive end date.
        category: Optional category filter.
        limit: Max number of records to return.

    Returns:
        List of transaction records ordered by date descending.

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        query = """
            SELECT amount, category, description, date, input_type
            FROM transactions
            WHERE user_id = ? AND date >= ? AND date <= ?
        """
        params: list[Any] = [user_id, start_date.isoformat(), end_date.isoformat()]

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    except Exception as exc:
        logger.error("get_transaction_history failed: %s", exc)
        raise DatabaseError("Fail fetch transaction history.") from exc


async def upsert_total_budget(
    user_id: str,
    amount: int,
    month: int,
    year: int,
) -> dict[str, Any]:
    """
    Insert or update the overall monthly budget (not per-category).

    Args:
        user_id: Internal UUID of the user.
        amount: Total budget amount in IDR.
        month: Month number 1-12.
        year: Four-digit year.

    Returns:
        Upserted total budget record.

    Raises:
        DatabaseError: If the upsert fails.
    """
    try:
        new_id = str(uuid.uuid4())
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                """INSERT INTO total_budgets (id, user_id, amount, month, year)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, month, year)
                   DO UPDATE SET amount = excluded.amount""",
                (new_id, user_id, amount, month, year),
            )
            await db.commit()
        return {"user_id": user_id, "amount": amount, "month": month, "year": year}
    except Exception as exc:
        logger.error("upsert_total_budget failed: %s", exc)
        raise DatabaseError("Gagal menyimpan total budget.") from exc


async def get_total_budget(
    user_id: str,
    month: int,
    year: int,
) -> dict[str, Any] | None:
    """
    Fetch the overall monthly budget for a user.

    Returns:
        Budget record or None if not set.
    """
    try:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM total_budgets WHERE user_id = ? AND month = ? AND year = ?",
                (user_id, month, year),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.error("get_total_budget failed: %s", exc)
        raise DatabaseError("Gagal mengambil total budget.") from exc
