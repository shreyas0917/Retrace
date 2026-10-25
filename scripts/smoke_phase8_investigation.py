"""Smoke: generate → diagnose → investigation."""
from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm_client import LLMResult, set_llm_provider


class Fake:
    def complete(self, messages, *, model, timeout):
        return LLMResult(
            content="Full-time employees accrue 1.25 days of PTO per month.",
            model=model,
            latency_ms=5,
            prompt_tokens=10,
            completion_tokens=8,
            total_tokens=18,
        )


def main() -> None:
    set_llm_provider(Fake())
    client = TestClient(create_app())
    key = os.environ["API_KEY"]
    h = {"Authorization": f"Bearer {key}"}

    corpora_raw = client.get("/api/v1/corpora", headers=h).json()
    corpora = (
        corpora_raw["corpora"]
        if isinstance(corpora_raw, dict)
        else corpora_raw
    )
    vid = None
    for c in corpora:
        cid = c["id"] if isinstance(c, dict) else c
        d = client.get(f"/api/v1/corpora/{cid}", headers=h).json()
        for v in d.get("versions") or []:
            if v.get("status") == "READY":
                vid = v["id"]
                break
        if vid:
            break

    if not vid:
        cid = f"p8_{uuid.uuid4().hex[:8]}"
        assert client.post(
            "/api/v1/corpora", headers=h, json={"id": cid, "title": "P8"}
        ).status_code == 200
        r = client.post(
            f"/api/v1/corpora/{cid}/versions",
            headers=h,
            json={
                "documents": [
                    {
                        "id": "pto",
                        "text": (
                            "Full-time employees accrue 1.25 days of PTO per month. "
                            "Unused PTO may carry over."
                        ),
                        "source_name": "pto.md",
                    },
                    {
                        "id": "refund",
                        "text": "Refunds within 30 days.",
                        "source_name": "refund.md",
                    },
                ]
            },
        )
        assert r.status_code == 200, r.text
        vid = r.json()["id"]

    print("version", vid)
    gen = client.post(
        "/api/v1/generate",
        headers=h,
        json={
            "corpus_version_id": vid,
            "query": "How much PTO do full-time employees accrue per month?",
            "top_k": 3,
        },
    )
    print("generate", gen.status_code, gen.json().get("status"), gen.json().get("execution_id"))
    assert gen.status_code == 200, gen.text
    eid = gen.json()["execution_id"]

    diag = client.post("/api/v1/diagnose", headers=h, json={"execution_id": eid})
    print(
        "diagnose",
        diag.status_code,
        diag.json().get("failure_code"),
        diag.json().get("rule_id"),
    )
    assert diag.status_code == 200, diag.text

    inv = client.get(f"/api/v1/investigations/{eid}", headers=h)
    body = inv.json()
    print("investigation", inv.status_code)
    print(
        "failure",
        (body.get("diagnosis") or {}).get("failure_code"),
        "rule",
        (body.get("rule") or {}).get("rule_id"),
    )
    print(
        "chunks",
        len((body.get("retrieval") or {}).get("chunks") or []),
        "judges",
        len(body.get("judges") or []),
        "evidence",
        len(body.get("evidence") or []),
        "timeline",
        len(body.get("timeline") or []),
    )
    assert inv.status_code == 200
    assert body["execution"]["execution_id"] == eid
    assert body["diagnosis"] is not None
    assert body["rule"] is not None
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
