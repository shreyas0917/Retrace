"""Load and validate versioned gold/planted JSONL suites (PRD §5.3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.services.diagnosis.taxonomy import FAILURE_CODES
from app.services.eval.schemas import GoldCase

# Known diagnosis rules that may appear as expected_rule_id
KNOWN_RULE_IDS = {
    "R00",
    "R01",
    "R02",
    "R10",
    "R11",
    "R12",
    "R14",
    "R20",
    "R21",
    "R30",
    "R31",
    "R33",
    "R34",
    "R40",
    "R99",
}


class SuiteValidationError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="SUITE_VALIDATION_ERROR",
            message=message,
            status_code=400,
            details=details or {},
        )


def default_suites_root() -> Path:
    """Resolve suites directory inside the backend package tree."""
    # backend/app/services/eval/suite_loader.py → backend/datasets/suites
    here = Path(__file__).resolve()
    candidate = here.parents[3] / "datasets" / "suites"
    if candidate.is_dir():
        return candidate
    # Docker / alternate: /datasets/suites
    alt = Path("/datasets/suites")
    if alt.is_dir():
        return alt
    return candidate


def suite_dir(suite_id: str, suite_version: str, root: Path | None = None) -> Path:
    root = root or default_suites_root()
    return root / suite_id / f"v{suite_version}"


def compute_suite_hash(raw_lines: list[str]) -> str:
    """SHA-256 over canonical JSONL (normalized JSON objects, one per line)."""
    canonical_lines: list[str] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        canonical_lines.append(
            json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
    payload = "\n".join(canonical_lines) + ("\n" if canonical_lines else "")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _validate_case(case: GoldCase, *, require_chunk_refs: bool) -> None:
    if case.expected_rule_id and case.expected_rule_id not in KNOWN_RULE_IDS:
        raise SuiteValidationError(
            f"invalid expected_rule_id: {case.expected_rule_id}",
            {"case_id": case.case_id},
        )
    if case.failure_label not in case.acceptable_primary_codes:
        raise SuiteValidationError(
            "failure_label must appear in acceptable_primary_codes",
            {"case_id": case.case_id},
        )
    if require_chunk_refs:
        for cid in case.relevant_chunk_ids:
            if not cid or ":" not in cid:
                raise SuiteValidationError(
                    f"invalid chunk id format: {cid}",
                    {"case_id": case.case_id},
                )


def load_suite(
    suite_id: str,
    suite_version: str,
    *,
    root: Path | None = None,
) -> tuple[list[GoldCase], str, dict[str, Any]]:
    """Load cases.jsonl + optional manifest. Returns (cases, suite_hash, meta)."""
    directory = suite_dir(suite_id, suite_version, root=root)
    cases_path = directory / "cases.jsonl"
    if not cases_path.is_file():
        raise SuiteValidationError(
            f"suite file not found: {cases_path}",
            {"suite_id": suite_id, "suite_version": suite_version},
        )

    raw_lines = cases_path.read_text(encoding="utf-8").splitlines()
    cases: list[GoldCase] = []
    seen: set[str] = set()

    for i, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuiteValidationError(
                f"invalid JSON on line {i}: {exc}",
                {"path": str(cases_path)},
            ) from exc
        try:
            case = GoldCase.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise SuiteValidationError(
                f"invalid case on line {i}: {exc}",
                {"path": str(cases_path)},
            ) from exc

        if case.suite_id != suite_id or case.suite_version != suite_version:
            raise SuiteValidationError(
                "case suite_id/version mismatch with path",
                {"case_id": case.case_id, "line": i},
            )
        if case.case_id in seen:
            raise SuiteValidationError(
                f"duplicate case_id: {case.case_id}",
                {"suite_id": suite_id},
            )
        seen.add(case.case_id)
        _validate_case(case, require_chunk_refs=True)
        cases.append(case)

    if not cases:
        raise SuiteValidationError("suite has no cases", {"suite_id": suite_id})

    suite_hash = compute_suite_hash(raw_lines)

    manifest_path = directory / "manifest.json"
    meta: dict[str, Any] = {
        "suite_id": suite_id,
        "suite_version": suite_version,
        "suite_hash": suite_hash,
        "case_count": len(cases),
        "path": str(cases_path),
    }
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("suite_hash")
        if expected and expected != suite_hash:
            raise SuiteValidationError(
                "manifest suite_hash does not match cases.jsonl",
                {"expected": expected, "actual": suite_hash},
            )
        meta["manifest"] = manifest

    # Reserved codes must not be primary failure_label unless marked reserved intentionally
    for case in cases:
        entry = FAILURE_CODES[case.failure_label]
        if entry.reserved:
            raise SuiteValidationError(
                f"reserved failure_label not allowed in suite: {case.failure_label}",
                {"case_id": case.case_id},
            )

    return cases, suite_hash, meta


def write_manifest(
    suite_id: str,
    suite_version: str,
    suite_hash: str,
    *,
    root: Path | None = None,
    case_count: int | None = None,
) -> Path:
    directory = suite_dir(suite_id, suite_version, root=root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    payload = {
        "suite_id": suite_id,
        "suite_version": suite_version,
        "suite_hash": suite_hash,
        "case_count": case_count,
        "taxonomy_version": "1.0",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
