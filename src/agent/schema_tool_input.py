from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field


class TransactionInput(BaseModel):
    """A single financial transaction."""

    amount: int = Field(description="The transaction amount")
    category: str = Field(description="The transaction category")
    description: str = Field(description="The transaction description")
    date: str = Field(description="The transaction date")


class SetBudgetInput(BaseModel):
    """Set budget input."""

    amount: int = Field(description="Budget amount in Rupiah.")
    month: int = Field(description="Month number (1-12).")
    year: int = Field(description="Four digit year.")
    category: Optional[str] = Field(
        default=None,
        description="Expense category. Leave null to set the total monthly budget.",
    )


class GetSpendingSummaryInput(BaseModel):
    """Get spending summary input."""

    scope: Literal["today", "current_week", "current_month", "last_month"] = Field(
        description="The time range scope for the spending summary. Must be a literal string."
    )
    category: Optional[str] = Field(
        default=None, description="Filter spending by specific category name."
    )


class GetTransactionHistoryInput(BaseModel):
    """Get transaction history input."""

    scope: Literal["today", "current_week", "current_month", "last_month"] = Field(
        description="The time range scope for retrieving history. Must be a literal string."
    )
    category: Optional[str] = Field(
        default=None, description="Filter history by category name."
    )
    limit: int = Field(
        default=10, description="Maximum number of transactions to return."
    )
