from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import structlog

from agent.schema_tool_input import (
    GetSpendingSummaryInput,
    GetTransactionHistoryInput,
    SetBudgetInput,
    TransactionInput,
)
from core.utils import get_date_range
from db.client import (
    get_budgets,
    get_summary,
    get_total_budget,
    upsert_budgets,
    upsert_total_budget,
)
from db.client import (
    get_transaction_history as db_get_transaction_history,
)
from db.client import save_transactions as db_save_transactions
from db.models import BudgetData, TransactionData

logger = structlog.getLogger(__name__)

_current_user_id: str = ""


def set_current_user(user_id: str) -> None:
    """Set the active user for subsequent tool calls."""
    global _current_user_id
    _current_user_id = user_id


async def save_transactions(
    transactions: list[TransactionInput],
) -> dict:
    """
    Save one or more financial transactions.

    Use this tool ONLY when the user wants to RECORD a new transaction.

    Examples:
    - I spent Rp50.000 on lunch.
    - Record my salary of Rp8.000.000.
    - I paid electricity yesterday.
    - Save these expenses.

    Do NOT use this tool for:
    - viewing transaction history
    - checking remaining budget
    - spending summaries
    - setting budgets

    """

    if not _current_user_id:
        return {"ok": False, "error": "No user context set."}

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

        logger.info(
            "transactions_saved",
            user_id=_current_user_id,
            count=len(saved),
        )

        return {
            "ok": True,
            "saved": len(saved),
        }

    except Exception as exc:
        logger.exception("save_transactions_failed")

        return {
            "ok": False,
            "error": str(exc),
        }


async def set_budget(args: SetBudgetInput) -> dict:
    """
    Create or update a monthly budget.

    Use this tool ONLY when the user wants to create or change a budget.

    Examples:
    - Set my monthly budget to 5 million.
    - Food budget is 1 million.
    - Transportation budget is 500 thousand.

    Do NOT use this tool for:
    - recording expenses
    - checking remaining budget
    - viewing summaries
    """
    amount = args.amount
    month = args.month
    year = args.year
    category = args.category

    if not _current_user_id:
        return {"ok": False, "error": "No user context."}

    try:
        if category is None:
            await upsert_total_budget(
                _current_user_id,
                amount,
                month,
                year,
            )

            logger.info(
                "total_budget_set",
                amount=amount,
                month=month,
                year=year,
            )

            return {
                "ok": True,
                "type": "total",
                "amount": amount,
            }

        await upsert_budgets(
            _current_user_id,
            [
                BudgetData(
                    category=category,
                    amount=amount,
                    month=month,
                    year=year,
                )
            ],
        )

        logger.info(
            "category_budget_set",
            category=category,
            amount=amount,
        )

        return {
            "ok": True,
            "type": "category",
            "category": category,
            "amount": amount,
        }

    except Exception as exc:
        logger.error("set_budget_failed", exc_info=exc)

        return {
            "ok": False,
            "error": str(exc),
        }


async def get_spending_summary(args: GetSpendingSummaryInput) -> dict:
    """
    Get aggregated spending for a time period.

    Use this tool ONLY when the user asks questions like:

    - How much did I spend this month?
    - Spending summary
    - Total food expense this week
    - Monthly spending

    Do NOT use this tool for:
    - remaining budget
    - transaction history
    - adding expenses
    """
    scope = args.scope
    category = args.category

    if not _current_user_id:
        return {"ok": False, "error": "No user context."}

    today = date.today()

    start, end = get_date_range(scope)

    spending = await get_summary(
        _current_user_id,
        start,
        end,
        category,
    )

    budgets = await get_budgets(
        _current_user_id,
        today.month,
        today.year,
    )

    total = sum(item["total"] for item in spending)

    logger.info(
        "summary_fetched",
        scope=scope,
        total=total,
    )

    return {
        "scope": scope,
        "total": total,
        "spending": spending,
        "budgets": budgets,
    }


async def get_remaining_budget(
    category: str | None = None,
) -> dict:
    """
    Get remaining budget after deducting current spending.

    Use this tool ONLY when the user asks:

    - Remaining budget
    - Budget left
    - How much money is left?
    - Can I still spend?

    Do NOT use this tool for:
    - transaction history
    - spending summaries
    """

    if not _current_user_id:
        return {"ok": False, "error": "No user context."}

    today = date.today()

    start, end = get_date_range("current_month")

    spending = await get_summary(
        _current_user_id,
        start,
        end,
    )

    total_spent = sum(s["total"] for s in spending)

    total_budget = await get_total_budget(
        _current_user_id,
        today.month,
        today.year,
    )

    if total_budget and category is None:
        remaining = total_budget["amount"] - total_spent

        return {
            "mode": "total",
            "budget": total_budget["amount"],
            "spent": total_spent,
            "remaining": remaining,
            "breakdown": spending,
            "as_of": today.isoformat(),
        }

    budgets = await get_budgets(
        _current_user_id,
        today.month,
        today.year,
    )

    budget_map = {b["category"]: b["amount"] for b in budgets}

    spent_map = {s["category"]: s["total"] for s in spending}

    result = {}

    for category_name, budget in budget_map.items():
        if category and category != category_name:
            continue

        spent = spent_map.get(category_name, 0)

        result[category_name] = {
            "budget": budget,
            "spent": spent,
            "remaining": budget - spent,
        }

    return {
        "mode": "per_category",
        "remaining_budget": result,
    }


async def get_transaction_history(args: GetTransactionHistoryInput) -> dict:
    """
    Retrieve transaction history.

    Use this tool ONLY when the user asks:

    - Show my recent transactions.
    - What did I spend yesterday?
    - Transaction history.
    - Last 20 expenses.

    Do NOT use this tool for:
    - summaries
    - remaining budget
    - setting budgets

    """
    scope = args.scope
    category = args.category
    limit = args.limit

    if not _current_user_id:
        return {"ok": False, "error": "No user context."}

    start, end = get_date_range(scope)

    history = await db_get_transaction_history(
        _current_user_id,
        start,
        end,
        category,
        limit,
    )

    logger.info(
        "history_fetched",
        scope=scope,
        count=len(history),
    )

    return {
        "transactions": history,
    }


TOOLS = [
    save_transactions,
    set_budget,
    get_spending_summary,
    get_remaining_budget,
    get_transaction_history,
]
