"""Gold / planted case schemas (PRD §5)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.diagnosis.taxonomy import FAILURE_CODES


class PlantedFailure(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class OfflineExecution(BaseModel):
    """Deterministic retrieve+answer fixture for offline suite mode."""

    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    answer: str | None = None
    abstained: bool = False
    status: str = "COMPLETED"
    error_code: str | None = None
    judge_scripts: dict[str, list[str]] | None = None


class GoldCase(BaseModel):
    case_id: str
    suite_id: str
    suite_version: str
    corpus_id: str
    corpus_version_pin: str
    query: str
    expected_answer: str | None = None
    expected_abstention: bool
    relevant_chunk_ids: list[str]
    failure_label: str
    acceptable_primary_codes: list[str]
    planted_failure: PlantedFailure | None = None
    notes: str | None = None
    annotator: str
    annotation_date: str
    taxonomy_version: str = "1.0"
    tags: list[str] = Field(default_factory=list)
    # Phase 5 extensions for rule accuracy + offline execution
    expected_rule_id: str | None = None
    expected_evidence_chunk_ids: list[str] | None = None
    offline_execution: OfflineExecution | None = None

    @field_validator("failure_label")
    @classmethod
    def _known_failure_label(cls, value: str) -> str:
        if value not in FAILURE_CODES:
            raise ValueError(f"unknown failure_label: {value}")
        return value

    @field_validator("acceptable_primary_codes")
    @classmethod
    def _known_acceptable(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("acceptable_primary_codes must be non-empty")
        for code in values:
            if code not in FAILURE_CODES:
                raise ValueError(f"unknown acceptable code: {code}")
        return values
