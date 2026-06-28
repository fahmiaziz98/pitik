from __future__ import annotations

from datetime import date

from pydantic import BaseModel, field_validator


class TransactionInput(BaseModel):
    """A single financial transaction."""

    amount: int
    category: str
    description: str
    date: str  # YYYY-MM-DD


class TransactionData(BaseModel):
    """Single financial transaction extracted by AI."""

    amount: int
    category: str
    description: str
    date: date

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: int) -> int:
        """Ensure extracted amount is always a positive integer."""
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v

    @field_validator("category")
    @classmethod
    def category_must_be_valid(cls, v: str) -> str:
        """Normalise and validate category against allowed list."""
        from core.config import settings

        v = v.lower().strip()
        if v not in settings.VALID_CATEGORIES:
            return "lainnya"
        return v


class BudgetData(BaseModel):
    """Budget setting for a specific category and month."""

    category: str
    amount: int
    month: int
    year: int

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("budget amount must be greater than 0")
        return v

    @field_validator("month")
    @classmethod
    def month_must_be_valid(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError("month must be between 1 and 12")
        return v
