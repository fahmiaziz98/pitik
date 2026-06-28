from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from core.utils import get_date_range
from db.client import (
    get_budgets,
    get_summary,
    get_total_budget,
    get_transaction_history,
    upsert_budgets,
    upsert_total_budget,
)
from db.client import (
    save_transactions as db_save_transactions,
)
from db.models import BudgetData, TransactionData, TransactionInput

_current_user_id: str = ""
logger = logging.getLogger(__name__)


def set_current_user(user_id: str) -> None:
    """Set the active user context for the next tool calls."""
    global _current_user_id
    _current_user_id = user_id


async def save_transactions_tool(transactions: list[TransactionInput]) -> dict:
    """
    Save one or more financial transactions to the database.

    Call this whenever you've identified expense or income data from
    the user's message, an uploaded image, or a PDF — even if there
    are multiple line items in a single receipt or message.

    Args:
        transactions: List of transactions to save. Each must have:
            amount (int): Amount in IDR e.g. 35000,
            category (str): One of makanan, transport, tagihan,
                kesehatan, belanja, hiburan, tabungan, pemasukan, lainnya,
            description (str): Short description e.g. makan siang,
            date (str): Date in YYYY-MM-DD format.
    """
    if not _current_user_id:
        return {"error": "No user context set."}
    try:
        parsed = [
            TransactionData(
                amount=t.amount,
                category=t.category,
                description=t.description,
                date=t.date,
            )
            for t in transactions
        ]
        saved = await db_save_transactions(
            user_id=_current_user_id,
            transactions=parsed,
            source="agent",
            raw_input=str([t.model_dump() for t in transactions])[:500],
            confidence="high",
        )
        logger.info("success save_transactions_tool")
        return {"saved_count": len(saved), "transactions": saved}
    except Exception as exc:
        logger.error("failed using save_transactions_tool")
        return {"error": f"Failed to save transactions: {exc}"}


async def set_budget_tool(
    amount: int,
    month: int,
    year: int,
    category: Optional[str] = None,
) -> dict:
    """
    Set or update a budget. Supports two modes:

    1. TOTAL BUDGET (recommended): when user says 'budget bulan ini 3.5jt'
       without mentioning a specific category — set category=None.
       This sets the overall monthly spending limit.

    2. CATEGORY BUDGET: when user says 'budget makan 1.5jt' —
       set category to the specific category name.

    Args:
        amount: Budget amount in IDR.
        month: Month number 1-12.
        year: Four-digit year.
        category: Optional. If None, sets total monthly budget.
            If specified, sets budget for that category only.
    """
    if not _current_user_id:
        return {"error": "No user context set."}

    try:
        if not category:
            # Total budget mode
            logger.info("using set_total_budget")
            saved = await upsert_total_budget(_current_user_id, amount, month, year)
            return {"type": "total_budget", "saved": saved}
        else:
            # Per-category budget mode
            logger.info("using total_budget_category")
            parsed = [
                BudgetData(category=category, amount=amount, month=month, year=year)
            ]
            saved = await upsert_budgets(_current_user_id, parsed)
            return {"type": "category_budget", "saved": saved}
    except Exception as exc:
        logger.error("failed using set_budget_tool")
        return {"error": f"Failed to set budget: {exc}"}


async def get_spending_summary_tool(
    scope: str,
    category: Optional[str] = None,
) -> dict:
    """
    Get the user's aggregated spending for a time period.

    Call this when the user asks for a recap or total spending
    e.g. 'rekap minggu ini', 'total pengeluaran bulan ini'.

    Args:
        scope: Time period — today, current_week, current_month, last_month.
        category: Optional. Limit results to a single category.
    """
    if not _current_user_id:
        return {"error": "No user context set."}
    logger.info("using get_spending_summary_tool")
    today = date.today()
    start, end = get_date_range(scope)
    spending = await get_summary(_current_user_id, start, end, category)
    budgets = await get_budgets(_current_user_id, today.month, today.year)
    return {
        "scope": scope,
        "spending": spending,
        "budgets": budgets,
        "total": sum(s["total"] for s in spending),
    }


async def get_remaining_budget_tool(
    category: Optional[str] = None,
) -> dict:
    """
    Get remaining budget vs actual spending for the current month.

    Checks total budget first. If total budget is set, compares against
    total spending across ALL categories. If per-category budget is set,
    compares per category.

    Call this when user asks 'sisa budget', 'masih ada berapa',
    'budget tinggal berapa'.

    Args:
        category: Optional. Check specific category only.
            If None, checks total budget or all category budgets.
    """
    if not _current_user_id:
        return {"error": "No user context set."}

    logger.info("using get_remaining_budget_tool")
    today = date.today()
    start, end = get_date_range("current_month")

    spending = await get_summary(_current_user_id, start, end)
    total_spent = sum(s["total"] for s in spending)

    total_budget = await get_total_budget(_current_user_id, today.month, today.year)
    if total_budget and not category:
        remaining = total_budget["amount"] - total_spent
        return {
            "mode": "total",
            "budget": total_budget["amount"],
            "spent": total_spent,
            "remaining": remaining,
            "breakdown": spending,  # per-category breakdown
            "note": "These numbers are live from database. Use these exact figures in your reply.",
            "as_of": date.today().isoformat(),
        }

    budgets = await get_budgets(_current_user_id, today.month, today.year)
    budget_map = {b["category"]: b["amount"] for b in budgets}
    spent_map = {s["category"]: s["total"] for s in spending}

    result = {}
    for cat, budget_amt in budget_map.items():
        if category and cat != category:
            continue
        spent = spent_map.get(cat, 0)
        result[cat] = {
            "budget": budget_amt,
            "spent": spent,
            "remaining": budget_amt - spent,
        }

    return {"mode": "per_category", "remaining_budget": result}


async def get_transaction_history_tool(
    scope: str,
    category: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """
    Get a list of recent individual transactions.

    Call this when the user wants to see specific transactions
    e.g. 'transaksi apa aja kemarin', 'list pengeluaran minggu ini'.

    Args:
        scope: Time period — today, current_week, current_month, last_month.
        category: Optional. Filter by category.
        limit: Max transactions to return, default 10.
    """
    if not _current_user_id:
        return {"error": "No user context set."}
    start, end = get_date_range(scope)
    history = await get_transaction_history(
        _current_user_id, start, end, category, limit
    )
    logger.info("using get_transaction_history_tool")
    return {"transactions": history}


TOOLS = [
    save_transactions_tool,
    set_budget_tool,
    get_spending_summary_tool,
    get_remaining_budget_tool,
    get_transaction_history_tool,
]
