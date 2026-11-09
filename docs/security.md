# Security

Retrace is a single-operator tool: one API key identifies "the operator", and
every authenticated caller has the same privileges. This document describes
how that credential is protected in v1.0, which abuse controls exist, how
untrusted retrieved text is handled, and what is deliberately out of scope.

## Threat model

| Threat | Vector | Control (v1.0) | Where |
| --- | --- | --- | --- |
| API key disclosure via the browser bundle | `VITE_API_KEY` baked into the React build; anyone who can load the console can read the key | Removed. The console never receives the key at build time; the operator types it once into a login panel and the server returns an HttpOnly session cookie | `frontend/src/views/LoginView.tsx`, `frontend/Dockerfile`, `docker-compose.yml` |
| Session theft via script injection | A script running on the console origin reading the credential | Cookie is `HttpOnly`; the key is cleared from React state after submission and never written to `localStorage` | `backend/app/api/routes_auth.py` |
| Cross-site request forgery | A hostile page makes the browser send a state-changing request with the session cookie attached | `SameSite=Lax` cookie plus a required `X-Requested-With: retrace-console` header on every non-GET cookie-authenticated request; missing header gives `403 CSRF_REJECTED`. CORS only allows origins listed in `CORS_ORIGINS` | `backend/app/core/security.py` |
| Session token forgery or replay after expiry | Crafting or editing a cookie value | Tokens are HMAC-SHA256 signed with `SESSION_SECRET` (or a key derived from `API_KEY`), compared in constant time, and carry an absolute expiry (`SESSION_TTL_MINUTES`) | `backend/app/core/security.py` |
| Credential brute force | Repeated `POST /api/v1/auth/session` attempts | Constant-time comparison; per-IP limit `AUTH_RATE_LIMIT_PER_MINUTE` (default 10) returning `429 RATE_LIMITED` with `Retry-After` | `backend/app/core/ratelimit.py` |
| Resource exhaustion | Request floods, giant bodies, giant queries, giant documents | Per-credential sliding-window limit `RATE_LIMIT_PER_MINUTE` (default 120); `MAX_REQUEST_BYTES` (default 1 MiB) gives `413 PAYLOAD_TOO_LARGE`; `MAX_QUERY_CHARS` (default 4000); 2,000,000-character cap per corpus document; `top_k` capped at 50 | `ratelimit.py`, `hardening.py`, `schemas/corpus.py`, `schemas/generate.py` |
| Injection through identifiers | Corpus or document ids used in URLs, Chroma collection names and log fields | Ids must match `^[A-Za-z0-9._-]+$` | `schemas/corpus.py` |
| Control characters in queries | Terminal escape sequences or NUL bytes reaching logs, prompts or the UI | C0/C1 control characters (except tab, CR, LF) are stripped before validation; a query that is empty afterwards is rejected with `400 INVALID_REQUEST` | `schemas/corpus.py` |
| Indirect prompt injection | A corpus document instructing the model to ignore its rules or leak secrets | Retrieved text is always wrapped in `<retrieved_context>` inside the **user** message; the system prompt is constant and tells the model to treat it as data. A conservative scanner flags suspicious chunks (`injection_flags`), increments `retrieval.injection_suspected` and logs a warning without the chunk text | `services/prompts.py`, `core/injection.py`, `services/retrieval.py` |
| Secret leakage through logs | Authorization headers, API keys, model keys in structured logs | structlog redaction processor replaces sensitive keys (any casing, nested dicts and lists) with `[REDACTED]`; error envelopes never echo the presented credential | `core/redaction.py`, `core/logging.py` |
| Clickjacking, MIME sniffing, referrer leakage | Browser-side attacks on the console or API responses | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, a minimal `Permissions-Policy`, and `Cache-Control: no-store` on `/api/v1/*` | `core/hardening.py` |

## Authentication

Two credentials are accepted. Both resolve to the same operator identity and
are checked by one dependency, `require_auth` (aliased as `require_api_key`
so existing routers are unchanged).

### Bearer API key (CLI, scripts, CI, tests)

```http
GET /api/v1/status
Authorization: Bearer <API_KEY>
```

The key is compared with `hmac.compare_digest`. Nothing else is required: a
Bearer caller is not a browser, so the CSRF header is not enforced. When a
Bearer header is present it wins; an invalid Bearer value is a `401` even if a
valid cookie is also sent.

### Session cookie (console)

```text
POST /api/v1/auth/session   {"api_key": "..."}
  -> 200 {"authenticated": true, "expires_at": "...Z", "ttl_seconds": 28800}
     Set-Cookie: retrace_session=<payload>.<hmac>; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800[; Secure]
  -> 401 UNAUTHORIZED on a wrong key (rate limited per IP)

GET  /api/v1/auth/me        -> {"authenticated": bool, "method": "session"|"bearer"|null, "expires_at": ...}
POST /api/v1/auth/logout    -> clears the cookie
```

The token is stateless: `base64url(JSON{iat, exp, nonce}) + "." + HMAC-SHA256`.
There is no server-side session table, so logout only clears the cookie; a
copied token stays valid until `exp`. Keep `SESSION_TTL_MINUTES` short for
shared machines. The signing key is `SESSION_SECRET`, falling back to
`sha256("retrace-session:" + API_KEY)` so development works out of the box.
Set an independent `SESSION_SECRET` in production; rotating it invalidates all
sessions at once without rotating the API key.

The console flow (`frontend/src/App.tsx`):

1. On load, `GET /api/v1/auth/me` with `credentials: "include"`.
2. If not authenticated, render `LoginView`; the key is posted once and
   dropped from state.
3. All fetches send `credentials: "include"` and
   `X-Requested-With: retrace-console`; `Authorization` is only added when a
   caller passes a non-empty key (the console passes `""`).
4. "Log out" in the sidebar calls `POST /api/v1/auth/logout`.

### CSRF rationale

A cookie is attached automatically by the browser, so a third-party page could
otherwise trigger `POST /api/v1/generate` or `POST /api/v1/experiments` with
the operator's session. Two independent controls apply:

* `SameSite=Lax` stops the cookie being sent on cross-site POSTs in modern
  browsers.
* A custom header (`X-Requested-With: retrace-console`) can only be set by
  script running on an origin that passed the CORS preflight, so cross-site
  forms cannot add it. Cookie-authenticated `POST/PUT/PATCH/DELETE` without it
  are rejected with `403 CSRF_REJECTED`. `GET/HEAD/OPTIONS` are exempt because
  the API has no state-changing GETs.

Because `SameSite=Lax` is scoped to the site, serve the console and the API
under the same registrable domain (ports may differ, as in the default
`localhost:3000` / `localhost:8000`) or behind one reverse proxy.

## Rate limiting

`RateLimitMiddleware` keeps a sliding 60-second window per bucket key in
process memory:

| Request | Key | Limit |
| --- | --- | --- |
| `POST /api/v1/auth/session` | `auth:ip:<addr>` | `AUTH_RATE_LIMIT_PER_MINUTE` (10) |
| Any other `/api/v1/*` with a Bearer header | `key:<sha256(key)[:16]>` | `RATE_LIMIT_PER_MINUTE` (120) |
| Any other `/api/v1/*` with a session cookie | `session:<sha256(cookie)[:16]>` | `RATE_LIMIT_PER_MINUTE` |
| Anonymous `/api/v1/*` | `ip:<addr>` (first `X-Forwarded-For` entry when present) | `RATE_LIMIT_PER_MINUTE` |

Exempt: everything outside `/api/v1`, `/api/v1/health`, `/api/v1/ready`,
`/api/v1/metrics`, `GET /api/v1/runbooks*`, and `OPTIONS` preflights. Over
budget returns `429` with the standard envelope (`code: RATE_LIMITED`,
`details.retry_after_seconds`) and a `Retry-After` header. Set
`RATE_LIMIT_ENABLED=false` to disable. The limiter is single-process: with
several replicas each one enforces its own budget, and the counters reset on
restart. Trusting `X-Forwarded-For` assumes a reverse proxy that overwrites it.

## Input validation and request hardening

* `MAX_REQUEST_BYTES` is enforced from `Content-Length` before the route runs
  and, for chunked uploads, by counting bytes as they stream; both return
  `413 PAYLOAD_TOO_LARGE`.
* Queries (`/retrieve`, `/generate`): control characters stripped, trimmed,
  non-empty, at most `MAX_QUERY_CHARS`; `top_k` in `[1, 50]`.
* Corpus / document ids: `^[A-Za-z0-9._-]+$`, lengths 128 / 256. Document
  text at most 2,000,000 characters.
* Validation failures use the existing `400 INVALID_REQUEST` envelope with
  pydantic error details.
* Security headers are added to every response, including errors and `429`s.

## External traces (`/api/v1/traces`)

`POST /api/v1/traces` (one trace) and `POST /api/v1/traces/batch` (a JSON
array or JSON Lines) accept data from outside Retrace, so they are validated
more tightly than internal routes. Code: `api/routes_traces.py`,
`schemas/traces.py`, `services/external_traces.py`; tests:
`tests/test_external_traces.py`.

| Control | Rule |
| --- | --- |
| Authentication | Both routes depend on `require_api_key` (Bearer key or console session); without one they return `401`. |
| Request size | `MAX_REQUEST_BYTES` (1 MiB by default) applies before the route runs; larger bodies get `413 PAYLOAD_TOO_LARGE`. |
| Chunk count | At most `MAX_TRACE_CHUNKS` (50) retrieved chunks per trace; `chunk_id` values must be unique. |
| Chunk text | Non-empty after cleaning, at most `MAX_TRACE_CHUNK_CHARS` (8,000) characters each. |
| Answer | At most `MAX_TRACE_ANSWER_CHARS` (20,000) characters. |
| Query | Same rule as other queries: trimmed, non-empty, at most `MAX_QUERY_CHARS`. |
| Chunk and document ids | `^[A-Za-z0-9._:/#-]+$`, at most 256 characters. Unlike corpus ids, `:`, `/` and `#` are allowed so ids from other systems (`doc:c001`, `kb/page#3`) pass unchanged. The same rule applies to `gold_chunk_ids` (at most 50). |
| Control characters | C0/C1 control characters (except tab, newline and carriage return) are stripped from the query, every chunk text and the answer before anything is stored or judged. |
| Metadata | Optional `metadata` object of at most 50 keys and 8 KB serialized; stored in `trace_metadata`, never interpreted. |
| Prompt injection | Every chunk goes through the same scanner as retrieval (below). Matches come back in the response as `injection_flags` (chunk id → pattern names) with a warning, are stored with the chunk snapshot, and do not block diagnosis. |
| Rate limits | The normal `/api/v1` budget (`RATE_LIMIT_PER_MINUTE`, 120 per credential per minute); a batch counts as one request. |
| Batch cap | At most `MAX_TRACE_BATCH` (25) traces per batch request; more is rejected with a pointer to `retrace diagnose --batch`, which has no cap. Each trace is validated and diagnosed independently, so one bad trace never fails the batch. |

External traces are stored with `source = 'external'` and no corpus version
(migration `008_external_traces`), and Retrace never reads its own corpus to
diagnose them: only the chunks in the request are judged.

## Prompt-injection detection

`app/core/injection.py` is a detector, not a filter. Each retrieved chunk is
scanned against a short, documented list of patterns (instruction overrides,
role tags such as `<system>` or `<|im_start|>`, "reveal the API key"-style
exfiltration requests, "developer mode", hidden-instruction phrasing, and long
base64 blobs). Matches are returned as `injection_flags` on each result in
`/api/v1/retrieve` and `/api/v1/generate`, stored with the execution's chunk
snapshot, counted in `retrieval.injection_suspected`, and logged with chunk ids
and pattern names only. Flagged chunks are still passed to the model: the
defence is the prompt structure (constant system prompt, retrieved text inside
`<retrieved_context>` in the user turn, abstention when context is
insufficient), and `tests/test_security.py` asserts that an injected chunk
never alters the system message. Patterns are intentionally narrow; ordinary
documentation sentences such as "follow the instructions in the previous
section" do not match.

## Sensitive-data redaction

The structlog pipeline runs `redact_event_dict` before rendering. Any key that
equals or contains `authorization`, `api_key`, `password`, `secret`, `token`,
`credentials`, `bearer`, `private_key` (case- and separator-insensitive) is
replaced with `[REDACTED]`, recursively through dicts and lists. The
`retrieval_injection_suspected` warning deliberately omits chunk text, and the
`401` envelope never echoes the presented credential.

## Not covered in v1.0

* **Multi-user accounts, roles or RBAC.** One key, one identity, full access.
* **Key rotation UI.** Rotate by changing `API_KEY` (and optionally
  `SESSION_SECRET`) and restarting; there is no overlap period.
* **Server-side session revocation.** Tokens are stateless; logout clears the
  cookie but a copied token remains valid until expiry.
* **Distributed rate limiting.** Counters are per process.
* **Content Security Policy for the console.** The nginx image serves static
  files without a CSP header.
* **Encryption at rest, network policy, TLS termination.** Delegated to the
  deployment (reverse proxy, database configuration).
* **LLM provider key handling beyond redaction.** `MODEL_API_KEY` is read from
  the environment and never logged, but is otherwise the provider's concern.
* **Semantic prompt-injection classification.** The scanner is regex-based
  and will miss paraphrased or multilingual attacks; it is an operator signal,
  not a guarantee.
