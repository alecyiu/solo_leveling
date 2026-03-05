"""Pydantic models for Solo Leveling ML quiz app."""

from pydantic import BaseModel, field_validator

VALID_RANKS = {"E", "D", "C", "B", "A", "S"}


class Explanation(BaseModel):
    correct: str
    wrong: list[str]

    @field_validator("wrong")
    @classmethod
    def wrong_must_have_two(cls, v: list[str]) -> list[str]:
        if len(v) != 2:
            raise ValueError(f"explanation.wrong must have exactly 2 entries, got {len(v)}")
        return v


class Question(BaseModel):
    id: str
    rank: str
    week: int | None = None
    category: str | None = None
    question: str
    choices: list[str]
    correct: int
    explanation: Explanation

    @field_validator("choices")
    @classmethod
    def choices_must_have_three(cls, v: list[str]) -> list[str]:
        if len(v) != 3:
            raise ValueError(f"choices must have exactly 3 entries, got {len(v)}")
        return v

    @field_validator("correct")
    @classmethod
    def correct_in_range(cls, v: int) -> int:
        if v not in (0, 1, 2):
            raise ValueError(f"correct must be 0, 1, or 2, got {v}")
        return v

    @field_validator("rank")
    @classmethod
    def rank_must_be_valid(cls, v: str) -> str:
        if v not in VALID_RANKS:
            raise ValueError(f"rank must be one of {VALID_RANKS}, got {v!r}")
        return v


class GenerateRequest(BaseModel):
    focus_area: str
    rank: str = "B"
    count: int = 5

    @field_validator("rank")
    @classmethod
    def rank_must_be_valid(cls, v: str) -> str:
        if v not in VALID_RANKS:
            raise ValueError(f"rank must be one of {VALID_RANKS}, got {v!r}")
        return v

    @field_validator("count")
    @classmethod
    def count_in_range(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError(f"count must be between 1 and 20, got {v}")
        return v


class GenerateResponse(BaseModel):
    generated: int
    questions: list[Question]
