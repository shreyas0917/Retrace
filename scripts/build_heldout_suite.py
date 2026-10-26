#!/usr/bin/env python3
"""Generate the held-out (`heldout_v1`) and calibration (`calib_v1`) suites.

Why a generator
---------------
The planted suite has 12 hand-written scenarios, one per failure class. That
is enough to prove the rule engine is wired correctly, but not enough to
estimate precision/recall per class or to calibrate confidence. This script
produces a larger, seeded, reproducible set of offline execution fixtures
whose labels come from *scenario semantics* (what actually went wrong in the
simulated RAG run), not from the rule code. Roughly 15% of cases are "boundary"
cases whose judge scores sit at or near decision thresholds; those are where
the engine is expected to make mistakes or defer.

Honesty notes
-------------
* Chunk texts, answers and judge outputs are synthetic fixtures scripted to
  match the scenario. They are NOT live-LLM outputs and the suite does not
  prove live-model robustness. See docs/benchmarks/heldout_v1.md.
* Labels were authored by the generator's scenario templates (annotator
  `synthetic_generator_v1`), reviewed by the project author.
* `heldout_v1` and `calib_v1` use different seeds and are disjoint by
  construction (different case ids, different sampled parameters).

Usage (host or container; stdlib only):
    python scripts/build_heldout_suite.py            # writes both suites
    python scripts/build_heldout_suite.py --check    # verify hashes only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "heldout_generator.v1"
ABSTENTION_ANSWER = "INSUFFICIENT_CONTEXT"
ANNOTATION_DATE = "2026-10-26"

ROOT = Path(__file__).resolve().parents[1]
SUITES_ROOT = ROOT / "backend" / "datasets" / "suites"


# --------------------------------------------------------------------------
# Fact bank: each fact has a gold sentence (answers the query), a related
# sentence from the same document that does NOT answer it, the correct
# answer, a contradicting answer, an invented (unsupported, non-contradicting)
# answer and an extra unsupported claim used to build partially grounded
# answers.
# --------------------------------------------------------------------------
FACTS: list[dict[str, str]] = [
    {
        "doc": "employee_handbook",
        "q": "How much PTO do full-time employees accrue per month?",
        "gold": "Full-time employees accrue 1.25 days of PTO per month, for a total of 15 days per year.",
        "related": "PTO requests must be submitted through the HR portal at least two weeks in advance.",
        "answer": "Full-time employees accrue 1.25 days of PTO per month.",
        "wrong": "Full-time employees accrue 3 days of PTO per month.",
        "invented": "Full-time employees receive an additional PTO bonus week after five years of service.",
        "extra": "Unused PTO is paid out at double rate in December.",
    },
    {
        "doc": "employee_handbook",
        "q": "How long is the probation period for new hires?",
        "gold": "New hires complete a 90-day probation period with a review at day 45 and day 90.",
        "related": "During onboarding, new hires meet their assigned buddy in the first week.",
        "answer": "The probation period is 90 days with reviews at day 45 and day 90.",
        "wrong": "The probation period is six months.",
        "invented": "New hires receive a signing bonus at the end of probation.",
        "extra": "Probation can be extended indefinitely by any manager.",
    },
    {
        "doc": "refund_policy",
        "q": "Within how many days can a customer request a full refund for a physical product?",
        "gold": "Customers may request a full refund within 30 days of purchase if the product is unused and in original packaging.",
        "related": "Approved refunds are issued to the original payment method within 5 to 10 business days.",
        "answer": "A full refund can be requested within 30 days of purchase for unused products in original packaging.",
        "wrong": "A full refund can be requested within 90 days of purchase.",
        "invented": "Refunds are also available for products damaged by the customer.",
        "extra": "Store credit is issued at 110% of the purchase price.",
    },
    {
        "doc": "refund_policy",
        "q": "What is the refund window for digital goods?",
        "gold": "Digital goods are eligible for refund only within 14 days and only if the download was never completed.",
        "related": "Submit a refund request through the support portal and include the order ID.",
        "answer": "Digital goods can be refunded within 14 days if the download was never completed.",
        "wrong": "Digital goods can be refunded within 30 days regardless of download status.",
        "invented": "Digital goods refunds require a notarised statement.",
        "extra": "Partially downloaded files qualify for a 50% refund.",
    },
    {
        "doc": "refund_policy",
        "q": "How long does it take for an approved refund to reach the customer?",
        "gold": "Approved refunds are issued to the original payment method within 5 to 10 business days.",
        "related": "Chargebacks initiated without contacting support first may result in account suspension.",
        "answer": "Approved refunds reach the original payment method within 5 to 10 business days.",
        "wrong": "Approved refunds are issued within 24 hours.",
        "invented": "Refunds above $500 are issued by cheque.",
        "extra": "Customers may choose cryptocurrency as the refund method.",
    },
    {
        "doc": "security_policy",
        "q": "Is multi-factor authentication mandatory for company accounts?",
        "gold": "All employees must enable multi-factor authentication on company accounts within 7 days of account creation.",
        "related": "Security training is mandatory every 12 months for all staff.",
        "answer": "Yes, MFA must be enabled on company accounts within 7 days of account creation.",
        "wrong": "MFA is optional for company accounts.",
        "invented": "Hardware keys are shipped to every employee automatically.",
        "extra": "SMS codes are the only approved second factor.",
    },
    {
        "doc": "security_policy",
        "q": "How often must passwords be rotated?",
        "gold": "Passwords for privileged accounts must be rotated every 90 days; standard accounts rotate every 180 days.",
        "related": "Report lost or stolen devices to the security team immediately.",
        "answer": "Privileged account passwords rotate every 90 days and standard accounts every 180 days.",
        "wrong": "All passwords must be rotated every 30 days.",
        "invented": "Password managers are prohibited on company devices.",
        "extra": "Passwords may be shared within a team via email.",
    },
    {
        "doc": "remote_work_policy",
        "q": "How many days per week can employees work remotely?",
        "gold": "Eligible employees may work remotely up to 3 days per week with manager approval.",
        "related": "Remote workers must be reachable on company chat during core hours of 10:00 to 16:00.",
        "answer": "Eligible employees can work remotely up to 3 days per week with manager approval.",
        "wrong": "Employees can work remotely 5 days per week without approval.",
        "invented": "Remote workers receive a $200 monthly internet stipend.",
        "extra": "Remote days must be Mondays and Fridays only.",
    },
    {
        "doc": "remote_work_policy",
        "q": "What are the core hours for remote workers?",
        "gold": "Remote workers must be reachable on company chat during core hours of 10:00 to 16:00 local time.",
        "related": "Requests to work remotely from another country require HR approval 30 days in advance.",
        "answer": "Core hours for remote workers are 10:00 to 16:00 local time.",
        "wrong": "Core hours are 08:00 to 18:00.",
        "invented": "Remote workers must install time-tracking software.",
        "extra": "Core hours are waived on Fridays.",
    },
    {
        "doc": "expense_reimbursement",
        "q": "Above what amount do expenses require an itemised receipt?",
        "gold": "Expenses above $25 require an itemised receipt attached to the claim.",
        "related": "Expense claims are paid with the next payroll cycle after approval.",
        "answer": "Expenses above $25 require an itemised receipt.",
        "wrong": "Receipts are only required above $100.",
        "invented": "Alcohol is reimbursable up to $50 per person.",
        "extra": "Claims without receipts are approved automatically under $200.",
    },
    {
        "doc": "expense_reimbursement",
        "q": "What is the deadline for submitting an expense claim?",
        "gold": "Expense claims must be submitted within 30 days of the expense date; late claims require director approval.",
        "related": "Use the Concur portal to submit claims and attach receipts as PDF or image files.",
        "answer": "Expense claims must be submitted within 30 days of the expense date.",
        "wrong": "Expense claims can be submitted at any time within the fiscal year.",
        "invented": "Late claims incur a 10% processing fee.",
        "extra": "Claims are reimbursed in cash at reception.",
    },
    {
        "doc": "it_acceptable_use",
        "q": "Can personal USB drives be used on company laptops?",
        "gold": "Personal USB storage devices are prohibited on company laptops; use the approved encrypted drives issued by IT.",
        "related": "Software may only be installed from the company application catalogue.",
        "answer": "No, personal USB drives are prohibited; only IT-issued encrypted drives may be used.",
        "wrong": "Personal USB drives are allowed if scanned by antivirus first.",
        "invented": "IT issues two encrypted drives to every new employee.",
        "extra": "Encrypted drives can be purchased with personal funds and expensed.",
    },
    {
        "doc": "data_retention",
        "q": "How long are application logs retained?",
        "gold": "Application logs are retained for 13 months and then permanently deleted.",
        "related": "Customer records are retained for 7 years after contract termination to satisfy audit requirements.",
        "answer": "Application logs are retained for 13 months.",
        "wrong": "Application logs are retained for 5 years.",
        "invented": "Logs are archived to tape after 30 days.",
        "extra": "Engineers may request indefinite retention for any log.",
    },
    {
        "doc": "data_retention",
        "q": "How long are customer records kept after a contract ends?",
        "gold": "Customer records are retained for 7 years after contract termination to satisfy audit requirements.",
        "related": "Deletion requests from customers are processed within 30 days.",
        "answer": "Customer records are kept for 7 years after contract termination.",
        "wrong": "Customer records are deleted 90 days after contract termination.",
        "invented": "Customer records are stored in a Swiss data centre.",
        "extra": "Records older than 7 years are sold to data brokers.",
    },
    {
        "doc": "incident_response",
        "q": "Within what time must a suspected security incident be reported?",
        "gold": "Any suspected security incident must be reported to the on-call security engineer within 1 hour of discovery.",
        "related": "Severity 1 incidents require a written post-mortem within 5 business days.",
        "answer": "Suspected security incidents must be reported within 1 hour of discovery.",
        "wrong": "Incidents must be reported within 48 hours.",
        "invented": "Reporters of incidents receive a $100 gift card.",
        "extra": "Reports can be delayed until the next business day.",
    },
    {
        "doc": "incident_response",
        "q": "When is a post-mortem required after a severity 1 incident?",
        "gold": "Severity 1 incidents require a written post-mortem within 5 business days of resolution.",
        "related": "The incident commander is the on-call engineer unless a manager takes over explicitly.",
        "answer": "A written post-mortem is required within 5 business days of resolving a severity 1 incident.",
        "wrong": "Post-mortems are optional for severity 1 incidents.",
        "invented": "Post-mortems are presented to the board of directors.",
        "extra": "Post-mortems must name the individual at fault.",
    },
    {
        "doc": "onboarding_checklist",
        "q": "When should a new hire receive their laptop?",
        "gold": "IT ships the new hire's laptop so that it arrives at least 2 business days before the start date.",
        "related": "New hires complete the security awareness module during their first week.",
        "answer": "The laptop arrives at least 2 business days before the start date.",
        "wrong": "The laptop is handed over on the first day of work.",
        "invented": "New hires may choose between a laptop and a desktop workstation.",
        "extra": "Laptops are replaced every 12 months.",
    },
    {
        "doc": "travel_policy",
        "q": "What is the daily meal per diem for domestic travel?",
        "gold": "The domestic meal per diem is $75 per day; international travel uses the published GSA rate for the destination.",
        "related": "Flights longer than 6 hours may be booked in premium economy.",
        "answer": "The domestic meal per diem is $75 per day.",
        "wrong": "The domestic meal per diem is $120 per day.",
        "invented": "Per diem is doubled on weekends.",
        "extra": "Per diem also covers hotel minibar purchases.",
    },
    {
        "doc": "travel_policy",
        "q": "When can employees book premium economy flights?",
        "gold": "Flights longer than 6 hours may be booked in premium economy; business class requires VP approval.",
        "related": "Book all travel through the corporate travel tool to ensure insurance coverage.",
        "answer": "Premium economy is allowed for flights longer than 6 hours.",
        "wrong": "Premium economy is allowed for any flight over 2 hours.",
        "invented": "Frequent flyer upgrades must be surrendered to the company.",
        "extra": "Business class is automatic for directors.",
    },
    {
        "doc": "benefits_overview",
        "q": "What is the company 401(k) match?",
        "gold": "The company matches 100% of 401(k) contributions up to 4% of base salary, vesting immediately.",
        "related": "Open enrollment for health plans runs from 1 November to 15 November each year.",
        "answer": "The company matches 100% of contributions up to 4% of base salary with immediate vesting.",
        "wrong": "The company matches 50% of contributions up to 6% of salary.",
        "invented": "Employees also receive company stock every quarter.",
        "extra": "The match increases to 8% after ten years.",
    },
    {
        "doc": "benefits_overview",
        "q": "When is open enrollment for health plans?",
        "gold": "Open enrollment for health plans runs from 1 November to 15 November each year.",
        "related": "Dental and vision coverage are included in all medical plan tiers.",
        "answer": "Open enrollment runs from 1 November to 15 November.",
        "wrong": "Open enrollment runs throughout January.",
        "invented": "Employees can switch plans at any time during the year.",
        "extra": "Enrollment is handled by phone only.",
    },
    {
        "doc": "procurement_policy",
        "q": "When are three competitive quotes required for a purchase?",
        "gold": "Purchases above $10,000 require three competitive quotes and a signed vendor evaluation form.",
        "related": "Preferred vendors are listed in the procurement catalogue and reviewed annually.",
        "answer": "Three competitive quotes are required for purchases above $10,000.",
        "wrong": "Three quotes are required for any purchase above $1,000.",
        "invented": "Quotes must be obtained from vendors in three different countries.",
        "extra": "Single-source purchases are allowed with a verbal approval.",
    },
    {
        "doc": "performance_reviews",
        "q": "How often are formal performance reviews held?",
        "gold": "Formal performance reviews are held twice a year, in June and December, with a self-assessment due two weeks before.",
        "related": "Managers hold informal one-on-one check-ins at least every two weeks.",
        "answer": "Formal performance reviews happen twice a year, in June and December.",
        "wrong": "Formal performance reviews are held once a year in March.",
        "invented": "Reviews are conducted by an external consultancy.",
        "extra": "Ratings are published company-wide.",
    },
    {
        "doc": "it_acceptable_use",
        "q": "Where can employees install software from?",
        "gold": "Software may only be installed from the company application catalogue; other installs require an IT exception ticket.",
        "related": "Company laptops must lock automatically after 5 minutes of inactivity.",
        "answer": "Software must come from the company application catalogue unless IT grants an exception.",
        "wrong": "Employees may install any software with a valid licence.",
        "invented": "The catalogue includes a free game library.",
        "extra": "Exception tickets are approved within one hour.",
    },
    {
        "doc": "onboarding_checklist",
        "q": "When must the security awareness module be completed?",
        "gold": "New hires complete the security awareness module during their first week, before receiving production access.",
        "related": "Managers schedule a 30-60-90 day plan conversation in the first fortnight.",
        "answer": "The security awareness module must be completed in the first week, before production access.",
        "wrong": "The security awareness module is due within the first 90 days.",
        "invented": "Completion earns a certificate signed by the CEO.",
        "extra": "The module can be skipped by senior hires.",
    },
    {
        "doc": "security_policy",
        "q": "How often is security training required?",
        "gold": "Security training is mandatory every 12 months for all staff and contractors.",
        "related": "Visitors must be escorted at all times inside the office.",
        "answer": "Security training is mandatory every 12 months.",
        "wrong": "Security training is only required once at hiring.",
        "invented": "Training is delivered in person at headquarters.",
        "extra": "Contractors are exempt from the annual training.",
    },
]

GENERIC_DISTRACTORS: list[tuple[str, str]] = [
    ("facilities", "The cafeteria serves lunch from noon to 14:00 on weekdays."),
    ("facilities", "Parking permits are issued by the front desk on request."),
    ("facilities", "Meeting rooms can be booked up to 30 days in advance."),
    ("company_news", "The quarterly all-hands will be streamed to all offices."),
    ("company_news", "The design team moved to the fourth floor last month."),
    ("style_guide", "Use sentence case for headings in customer-facing documents."),
    ("style_guide", "Dates in documents follow the ISO 8601 format."),
    ("holidays", "The office is closed on national public holidays."),
    ("holidays", "Floating holidays must be used within the calendar year."),
    ("wellness", "The wellness programme reimburses gym membership up to $40 per month."),
]


def _sha_suite(raw_lines: list[str]) -> str:
    canonical = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        canonical.append(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    payload = "\n".join(canonical) + ("\n" if canonical else "")
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Fixture helpers (schemas mirror app.services.eval.fakes)
# --------------------------------------------------------------------------
def relevance_json(ids: list[str], *, sufficient: bool, scores: list[float]) -> str:
    items = [
        {"chunk_id": cid, "relevant": s >= 0.5, "score": round(s, 3), "rationale": "fixture"}
        for cid, s in zip(ids, scores)
    ]
    return json.dumps({"items": items, "context_sufficient": sufficient})


def faithfulness_json(*, score: float, supported: int, unsupported: int, support_ids: list[str]) -> str:
    claims = [
        {"claim": f"supported claim {i}", "supported": True, "supporting_chunk_ids": support_ids}
        for i in range(supported)
    ] + [
        {"claim": f"unsupported claim {i}", "supported": False, "supporting_chunk_ids": []}
        for i in range(unsupported)
    ]
    return json.dumps({"faithfulness_score": round(score, 3), "claims": claims})


def contradiction_json(contradicts: bool, ids: list[str]) -> str:
    return json.dumps(
        {"contradicts": contradicts, "explanation": "fixture", "chunk_ids": ids if contradicts else []}
    )


class Builder:
    def __init__(self, suite_id: str, seed: int) -> None:
        self.suite_id = suite_id
        self.rng = random.Random(seed)
        self.counter = 0

    # -- primitives ---------------------------------------------------------
    def chunk(self, doc: str, text: str, *, score: float, rank: int, ordinal: int | None = None) -> dict[str, Any]:
        ordinal = self.rng.randint(0, 9) if ordinal is None else ordinal
        return {
            "chunk_id": f"{doc}:c{ordinal:03d}",
            "document_id": doc,
            "text": text,
            "rank": rank,
            "retrieval_score": round(score, 4),
            "source_name": f"{doc}.md",
        }

    def distractors(self, exclude_doc: str, n: int) -> list[tuple[str, str]]:
        pool: list[tuple[str, str]] = [
            (f["doc"], f["related"]) for f in FACTS if f["doc"] != exclude_doc
        ] + GENERIC_DISTRACTORS
        self.rng.shuffle(pool)
        return pool[:n]

    def assemble(self, fact: dict[str, str], *, gold_text: str | None, n_distractors: int,
                 gold_score: float) -> tuple[list[dict[str, Any]], str | None]:
        """Return chunk list (unique ids, gold at random rank) and the gold chunk id."""
        items: list[tuple[str, str, float]] = []
        if gold_text is not None:
            items.append((fact["doc"], gold_text, gold_score))
        for doc, text in self.distractors(fact["doc"], n_distractors):
            items.append((doc, text, self.rng.uniform(0.05, 0.45)))
        self.rng.shuffle(items)
        # sort by score descending to make ranks consistent with scores
        items.sort(key=lambda t: t[2], reverse=True)
        chunks: list[dict[str, Any]] = []
        used: set[str] = set()
        gold_id: str | None = None
        for rank, (doc, text, score) in enumerate(items, start=1):
            c = self.chunk(doc, text, score=score, rank=rank)
            while c["chunk_id"] in used:
                c = self.chunk(doc, text, score=score, rank=rank)
            used.add(c["chunk_id"])
            chunks.append(c)
            if text == gold_text and doc == fact["doc"]:
                gold_id = c["chunk_id"]
        return chunks, gold_id

    def rel_scores(self, chunks: list[dict[str, Any]], relevant_ids: set[str], *, boundary: bool,
                   weak: bool = False) -> list[float]:
        scores = []
        for c in chunks:
            if c["chunk_id"] in relevant_ids:
                if weak:
                    scores.append(self.rng.uniform(0.5, 0.65))
                elif boundary:
                    scores.append(self.rng.uniform(0.5, 0.6))
                else:
                    scores.append(self.rng.uniform(0.72, 0.98))
            else:
                scores.append(self.rng.uniform(0.4, 0.49) if boundary else self.rng.uniform(0.02, 0.35))
        return scores

    def next_id(self) -> str:
        self.counter += 1
        prefix = "H" if self.suite_id.startswith("heldout") else "C"
        return f"{prefix}{self.counter:03d}"

    # -- case shell ---------------------------------------------------------
    def case(self, fact: dict[str, str], *, label: str, acceptable: list[str], rule: str,
             expected_abstention: bool, relevant_ids: list[str], chunks: list[dict[str, Any]],
             answer: str | None, abstained: bool, status: str, judge_scripts: dict[str, list[str]],
             error_code: str | None = None, evidence: list[str] | None = None,
             tags: list[str] | None = None, notes: str = "") -> dict[str, Any]:
        if label not in acceptable:
            acceptable = [label] + acceptable
        return {
            "case_id": self.next_id(),
            "suite_id": self.suite_id,
            "suite_version": "1.0.0",
            "corpus_id": "demo",
            "corpus_version_pin": "offline_fixture",
            "query": fact["q"],
            "expected_answer": fact["answer"] if not expected_abstention else None,
            "expected_abstention": expected_abstention,
            "relevant_chunk_ids": relevant_ids,
            "failure_label": label,
            "acceptable_primary_codes": acceptable,
            "planted_failure": None,
            "notes": notes,
            "annotator": "synthetic_generator_v1",
            "annotation_date": ANNOTATION_DATE,
            "taxonomy_version": "1.0",
            "tags": ["heldout", fact["doc"]] + list(tags or []),
            "expected_rule_id": rule,
            "expected_evidence_chunk_ids": evidence,
            "offline_execution": {
                "retrieved_chunks": chunks,
                "answer": answer,
                "abstained": abstained,
                "status": status,
                "error_code": error_code,
                "judge_scripts": judge_scripts,
            },
        }

    # -- scenario generators ------------------------------------------------
    def retrieval_empty(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        gold_id = f"{f['doc']}:c{self.rng.randint(0, 9):03d}"
        return self.case(
            f, label="RETRIEVAL_EMPTY", acceptable=["RETRIEVAL_EMPTY"], rule="R10",
            expected_abstention=True, relevant_ids=[gold_id], chunks=[],
            answer=ABSTENTION_ANSWER, abstained=True, status="ABSTAINED", judge_scripts={},
            evidence=None, tags=["retrieval"], notes="Index returned nothing for the query.",
        )

    def retrieval_miss(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        n = self.rng.randint(1, 5)
        chunks, _ = self.assemble(f, gold_text=None, n_distractors=n, gold_score=0)
        gold_id = f"{f['doc']}:c{self.rng.randint(0, 9):03d}"
        while any(c["chunk_id"] == gold_id for c in chunks):
            gold_id = f"{f['doc']}:c{self.rng.randint(0, 9):03d}"
        abstain = self.rng.random() < 0.6
        return self.case(
            f, label="RETRIEVAL_MISS", acceptable=["RETRIEVAL_MISS"], rule="R11",
            expected_abstention=True, relevant_ids=[gold_id], chunks=chunks,
            answer=ABSTENTION_ANSWER if abstain else f["wrong"], abstained=abstain,
            status="ABSTAINED" if abstain else "COMPLETED", judge_scripts={},
            evidence=[gold_id], tags=["retrieval", "abstained" if abstain else "answered"],
            notes="Gold chunk exists in the corpus but was not retrieved in top-k.",
        )

    def distractor_dominant(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        if boundary:
            # 2 of 3 irrelevant (0.667 < 0.70): genuinely ambiguous with correct abstention
            chunks, weak_id = self.assemble(f, gold_text=f["related"], n_distractors=2, gold_score=0.5)
            ids = [c["chunk_id"] for c in chunks]
            scores = self.rel_scores(chunks, {weak_id}, boundary=False, weak=True)
            acceptable = ["RETRIEVAL_DISTRACTOR_DOMINANT", "OK_CORRECT_ABSTENTION"]
            tags = ["retrieval", "boundary"]
        else:
            n = self.rng.choice([4, 5])
            with_weak = self.rng.random() < 0.4
            chunks, weak_id = self.assemble(
                f, gold_text=f["related"] if with_weak else None, n_distractors=n - (1 if with_weak else 0),
                gold_score=0.5,
            )
            ids = [c["chunk_id"] for c in chunks]
            scores = self.rel_scores(chunks, {weak_id} if weak_id else set(), boundary=False, weak=True)
            acceptable = ["RETRIEVAL_DISTRACTOR_DOMINANT"]
            tags = ["retrieval"]
        return self.case(
            f, label="RETRIEVAL_DISTRACTOR_DOMINANT", acceptable=acceptable, rule="R12",
            expected_abstention=True, relevant_ids=[], chunks=chunks,
            answer=ABSTENTION_ANSWER, abstained=True, status="ABSTAINED",
            judge_scripts={"relevance": [relevance_json(ids, sufficient=False, scores=scores)]},
            evidence=None, tags=tags,
            notes="Top-k dominated by off-topic chunks; system abstained; no gold labels available.",
        )

    def correct_abstention(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        n_d = 3 if boundary else self.rng.randint(1, 2)
        chunks, weak_id = self.assemble(f, gold_text=f["related"], n_distractors=n_d, gold_score=0.55)
        ids = [c["chunk_id"] for c in chunks]
        scores = self.rel_scores(chunks, {weak_id}, boundary=False, weak=True)
        acceptable = ["OK_CORRECT_ABSTENTION"] + (["RETRIEVAL_DISTRACTOR_DOMINANT"] if boundary else [])
        return self.case(
            f, label="OK_CORRECT_ABSTENTION", acceptable=acceptable, rule="R14",
            expected_abstention=True, relevant_ids=[weak_id], chunks=chunks,
            answer=ABSTENTION_ANSWER, abstained=True, status="ABSTAINED",
            judge_scripts={"relevance": [relevance_json(ids, sufficient=False, scores=scores)]},
            evidence=None, tags=["abstention"] + (["boundary"] if boundary else []),
            notes="Only a related-but-insufficient chunk retrieved; abstaining was correct.",
        )

    def abstention_false_negative(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        with_weak = self.rng.random() < 0.5
        n_d = self.rng.randint(1, 4) if not with_weak else self.rng.randint(1, 3)
        chunks, weak_id = self.assemble(f, gold_text=f["related"] if with_weak else None,
                                        n_distractors=n_d, gold_score=0.55)
        ids = [c["chunk_id"] for c in chunks]
        scores = self.rel_scores(chunks, {weak_id} if weak_id else set(), boundary=boundary, weak=True)
        answer = self.rng.choice([f["invented"], f["wrong"]])
        return self.case(
            f, label="ABSTENTION_FALSE_NEGATIVE", acceptable=["ABSTENTION_FALSE_NEGATIVE"], rule="R20",
            expected_abstention=True, relevant_ids=[weak_id] if weak_id else [], chunks=chunks,
            answer=answer, abstained=False, status="COMPLETED",
            judge_scripts={"relevance": [relevance_json(ids, sufficient=False, scores=scores)]},
            evidence=None, tags=["abstention"] + (["boundary"] if boundary else []),
            notes="Context insufficient but the generator answered anyway.",
        )

    def abstention_false_positive(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id = self.assemble(f, gold_text=f["gold"], n_distractors=self.rng.randint(0, 3),
                                        gold_score=self.rng.uniform(0.75, 0.95))
        ids = [c["chunk_id"] for c in chunks]
        scores = self.rel_scores(chunks, {gold_id}, boundary=boundary)
        return self.case(
            f, label="ABSTENTION_FALSE_POSITIVE", acceptable=["ABSTENTION_FALSE_POSITIVE"], rule="R21",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=ABSTENTION_ANSWER, abstained=True, status="ABSTAINED",
            judge_scripts={"relevance": [relevance_json(ids, sufficient=True, scores=scores)]},
            evidence=[gold_id], tags=["abstention"] + (["boundary"] if boundary else []),
            notes="Gold chunk retrieved and sufficient, yet the system abstained.",
        )

    def _grounding_base(self, f: dict[str, str], boundary: bool):
        chunks, gold_id = self.assemble(f, gold_text=f["gold"], n_distractors=self.rng.randint(0, 3),
                                        gold_score=self.rng.uniform(0.75, 0.97))
        ids = [c["chunk_id"] for c in chunks]
        scores = self.rel_scores(chunks, {gold_id}, boundary=boundary)
        return chunks, gold_id, ids, scores

    def contradiction(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id, ids, scores = self._grounding_base(f, boundary)
        supported = 1 if self.rng.random() < 0.4 else 0
        unsupported = self.rng.randint(1, 2)
        faith = self.rng.uniform(0.0, 0.5) if not supported else self.rng.uniform(0.3, 0.6)
        return self.case(
            f, label="GENERATION_CONTRADICTION", acceptable=["GENERATION_CONTRADICTION"], rule="R30",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=f["wrong"], abstained=False, status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json(ids, sufficient=True, scores=scores)],
                "faithfulness": [faithfulness_json(score=faith, supported=supported, unsupported=unsupported,
                                                   support_ids=[gold_id])],
                "contradiction": [contradiction_json(True, [gold_id])],
            },
            evidence=[gold_id], tags=["generation"] + (["boundary"] if boundary else []),
            notes="Answer states a value that conflicts with the retrieved gold chunk.",
        )

    def hallucination(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id, ids, scores = self._grounding_base(f, boundary)
        unsupported = self.rng.randint(1, 3)
        faith = self.rng.uniform(0.45, 0.6) if boundary else self.rng.uniform(0.0, 0.4)
        return self.case(
            f, label="GENERATION_HALLUCINATION",
            acceptable=["GENERATION_HALLUCINATION", "GROUNDING_UNSUPPORTED"], rule="R31",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=f["invented"], abstained=False, status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json(ids, sufficient=True, scores=scores)],
                "faithfulness": [faithfulness_json(score=faith, supported=0, unsupported=unsupported,
                                                   support_ids=[gold_id])],
                "contradiction": [contradiction_json(False, [])],
            },
            evidence=[gold_id], tags=["generation"] + (["boundary"] if boundary else []),
            notes="Context sufficient; answer invents content absent from the context.",
        )

    def partial(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id, ids, scores = self._grounding_base(f, boundary)
        supported = self.rng.randint(1, 3)
        unsupported = self.rng.randint(1, 2)
        if boundary:
            faith = self.rng.uniform(0.80, 0.84)
        else:
            base = supported / (supported + unsupported)
            faith = min(0.79, max(0.3, base + self.rng.uniform(-0.05, 0.05)))
        return self.case(
            f, label="GROUNDING_PARTIAL", acceptable=["GROUNDING_PARTIAL"], rule="R33",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=f["answer"] + " " + f["extra"], abstained=False, status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json(ids, sufficient=True, scores=scores)],
                "faithfulness": [faithfulness_json(score=faith, supported=supported, unsupported=unsupported,
                                                   support_ids=[gold_id])],
                "contradiction": [contradiction_json(False, [])],
            },
            evidence=[gold_id], tags=["grounding"] + (["boundary"] if boundary else []),
            notes="Answer mixes a supported claim with an unsupported extra claim.",
        )

    def ok_grounded(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id, ids, scores = self._grounding_base(f, boundary=False)
        supported = self.rng.randint(1, 4)
        if boundary:
            faith = self.rng.uniform(0.80, 0.84)  # judge under-scores a fully supported answer
            tags = ["none", "boundary"]
            notes = "All claims supported but the faithfulness score sits just under the threshold."
        else:
            faith = 1.0 if self.rng.random() < 0.7 else self.rng.uniform(0.86, 0.97)
            tags = ["none"]
            notes = "Answer fully grounded in the retrieved gold chunk."
        return self.case(
            f, label="OK_GROUNDED", acceptable=["OK_GROUNDED"], rule="R40",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=f["answer"], abstained=False, status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json(ids, sufficient=True, scores=scores)],
                "faithfulness": [faithfulness_json(score=faith, supported=supported, unsupported=0,
                                                   support_ids=[gold_id])],
                "contradiction": [contradiction_json(False, [])],
            },
            evidence=[gold_id], tags=tags, notes=notes,
        )

    def timeout(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id = self.assemble(f, gold_text=f["gold"], n_distractors=self.rng.randint(0, 2),
                                        gold_score=0.9)
        return self.case(
            f, label="EVAL_MODEL_TIMEOUT", acceptable=["EVAL_MODEL_TIMEOUT"], rule="R00",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=None, abstained=False, status="GENERATION_TIMEOUT", error_code="GENERATION_TIMEOUT",
            judge_scripts={}, evidence=None, tags=["infra"],
            notes="Generator timed out before answering.",
        )

    def judge_malformed(self, f: dict[str, str], boundary: bool) -> dict[str, Any]:
        chunks, gold_id, ids, scores = self._grounding_base(f, boundary=False)
        if self.rng.random() < 0.5:
            scripts = {"relevance": ["NOT_JSON", "{\"items\": \"still bad\"}"]}
            which = "relevance"
        else:
            scripts = {
                "relevance": [relevance_json(ids, sufficient=True, scores=scores)],
                "faithfulness": ["<html>error</html>", "{\"faithfulness_score\": 7}"],
            }
            which = "faithfulness"
        return self.case(
            f, label="EVAL_JUDGE_MALFORMED", acceptable=["EVAL_JUDGE_MALFORMED"], rule="R01",
            expected_abstention=False, relevant_ids=[gold_id], chunks=chunks,
            answer=f["answer"], abstained=False, status="COMPLETED", judge_scripts=scripts,
            evidence=None, tags=["infra", f"malformed:{which}"],
            notes=f"The {which} judge returned invalid output twice.",
        )


DISTRIBUTION_HELDOUT: dict[str, int] = {
    "retrieval_empty": 10,
    "retrieval_miss": 20,
    "distractor_dominant": 12,
    "correct_abstention": 18,
    "abstention_false_negative": 16,
    "abstention_false_positive": 12,
    "contradiction": 16,
    "hallucination": 16,
    "partial": 14,
    "ok_grounded": 18,
    "timeout": 4,
    "judge_malformed": 4,
}
DISTRIBUTION_CALIB: dict[str, int] = {k: max(2, v // 2) for k, v in DISTRIBUTION_HELDOUT.items()}


def build(suite_id: str, seed: int, distribution: dict[str, int], boundary_rate: float) -> list[dict[str, Any]]:
    b = Builder(suite_id, seed)
    plan: list[str] = []
    for name, count in distribution.items():
        plan.extend([name] * count)
    b.rng.shuffle(plan)
    facts = list(FACTS)
    cases: list[dict[str, Any]] = []
    for i, name in enumerate(plan):
        f = facts[i % len(facts)] if i < len(facts) else b.rng.choice(facts)
        boundary = b.rng.random() < boundary_rate and name not in {
            "retrieval_empty", "retrieval_miss", "timeout", "judge_malformed"
        }
        cases.append(getattr(b, name)(f, boundary))
    # ids are sequential in generation order; keep that order (shuffled plan).
    return cases


def write_suite(suite_id: str, cases: list[dict[str, Any]], *, seed: int) -> tuple[Path, str]:
    directory = SUITES_ROOT / suite_id / "v1.0.0"
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(c, ensure_ascii=False) for c in cases]
    cases_path = directory / "cases.jsonl"
    cases_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    suite_hash = _sha_suite(lines)
    labels: dict[str, int] = {}
    boundary = 0
    for c in cases:
        labels[c["failure_label"]] = labels.get(c["failure_label"], 0) + 1
        if "boundary" in c["tags"]:
            boundary += 1
    manifest = {
        "suite_id": suite_id,
        "suite_version": "1.0.0",
        "suite_hash": suite_hash,
        "case_count": len(cases),
        "taxonomy_version": "1.0",
        "generator": {"script": "scripts/build_heldout_suite.py", "version": GENERATOR_VERSION, "seed": seed},
        "label_distribution": dict(sorted(labels.items())),
        "boundary_cases": boundary,
        "notes": (
            "Synthetic offline fixtures with scripted judge outputs; labels derive from scenario "
            "semantics, not from the rule engine. Not evidence of live-LLM robustness."
        ),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return cases_path, suite_hash


def check(suite_id: str) -> bool:
    directory = SUITES_ROOT / suite_id / "v1.0.0"
    lines = (directory / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    ok = manifest["suite_hash"] == _sha_suite(lines)
    print(f"{suite_id}: {'OK' if ok else 'HASH MISMATCH'} ({len([l for l in lines if l.strip()])} cases)")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify manifests match cases.jsonl")
    parser.add_argument("--heldout-seed", type=int, default=20261026)
    parser.add_argument("--calib-seed", type=int, default=7031)
    parser.add_argument("--boundary-rate", type=float, default=0.15)
    args = parser.parse_args(argv)

    if args.check:
        return 0 if all(check(s) for s in ("heldout_v1", "calib_v1")) else 1

    for suite_id, seed, dist in (
        ("heldout_v1", args.heldout_seed, DISTRIBUTION_HELDOUT),
        ("calib_v1", args.calib_seed, DISTRIBUTION_CALIB),
    ):
        cases = build(suite_id, seed, dist, args.boundary_rate)
        path, suite_hash = write_suite(suite_id, cases, seed=seed)
        print(f"wrote {path} ({len(cases)} cases) {suite_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
