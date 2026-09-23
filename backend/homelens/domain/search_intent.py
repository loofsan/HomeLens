"""Strict model-to-search contract; model output never reaches SQL directly."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SuggestedFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    min_price: int | None = Field(ge=0, le=50_000_000)
    max_price: int | None = Field(ge=0, le=50_000_000)
    min_beds: float | None = Field(ge=0, le=20)
    min_baths: float | None = Field(ge=0, le=20)
    zip: str | None = Field(pattern=r"^\d{5}$")


class SearchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["ready", "clarify", "unsupported"]
    filters: SuggestedFilters
    question: str | None
    unsupported: list[str]
