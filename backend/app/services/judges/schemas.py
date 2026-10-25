"""Pydantic schemas for judge structured outputs (PRD §11–12)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RelevanceItem(BaseModel):
    chunk_id: str
    relevant: bool
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class RelevanceJudgeResult(BaseModel):
    items: list[RelevanceItem]
    context_sufficient: bool


class ClaimSupport(BaseModel):
    claim: str
    supported: bool
    supporting_chunk_ids: list[str] = Field(default_factory=list)


class FaithfulnessJudgeResult(BaseModel):
    faithfulness_score: float = Field(ge=0.0, le=1.0)
    claims: list[ClaimSupport]


class ContradictionJudgeResult(BaseModel):
    contradicts: bool
    explanation: str = ""
    chunk_ids: list[str] = Field(default_factory=list)
