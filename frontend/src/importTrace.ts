/**
 * Client-side checks for "Import a trace" (POST /api/v1/traces).
 *
 * These catch obvious mistakes before a request is sent. The backend schema
 * (backend/app/schemas/traces.py) stays the authority: anything that passes
 * here can still be rejected by the API, and those errors are shown too.
 */
import { ApiError } from "./api";

export type TraceValidation =
  | { ok: true; trace: Record<string, unknown> }
  | { ok: false; errors: string[] };

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function nonEmptyString(v: unknown): boolean {
  return typeof v === "string" && v.trim().length > 0;
}

export function validateTraceText(text: string): TraceValidation {
  if (!text.trim()) {
    return { ok: false, errors: ["Paste a trace as JSON first."] };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return { ok: false, errors: [`This is not valid JSON: ${detail}`] };
  }
  if (!isObject(parsed)) {
    return {
      ok: false,
      errors: ["The trace must be a JSON object, for example {\"query\": …}."],
    };
  }

  const errors: string[] = [];
  if (!("query" in parsed)) {
    errors.push("Missing \"query\": the question the user asked.");
  } else if (!nonEmptyString(parsed.query)) {
    errors.push("\"query\" must be a non-empty string.");
  }

  if (!("answer" in parsed)) {
    errors.push(
      "Missing \"answer\": the text your model returned (use null if it produced none).",
    );
  } else if (parsed.answer !== null && typeof parsed.answer !== "string") {
    errors.push("\"answer\" must be a string or null.");
  }

  if (!("retrieved_chunks" in parsed)) {
    errors.push(
      "Missing \"retrieved_chunks\": the passages your retriever returned (use [] if none).",
    );
  } else if (!Array.isArray(parsed.retrieved_chunks)) {
    errors.push("\"retrieved_chunks\" must be a list.");
  } else {
    parsed.retrieved_chunks.forEach((chunk, i) => {
      const where = `Chunk ${i + 1}`;
      if (!isObject(chunk)) {
        errors.push(`${where} must be an object with "chunk_id" and "text".`);
        return;
      }
      if (!nonEmptyString(chunk.chunk_id)) {
        errors.push(`${where} is missing "chunk_id".`);
      }
      if (!nonEmptyString(chunk.text)) {
        errors.push(`${where} is missing "text".`);
      }
    });
  }

  return errors.length ? { ok: false, errors } : { ok: true, trace: parsed };
}

type FieldError = { loc?: unknown[]; msg?: string; message?: string };

function formatLoc(loc: unknown[] | undefined): string {
  if (!loc || loc.length === 0) return "";
  const parts = loc.filter((p) => p !== "body").map((p) =>
    typeof p === "number" ? `[${p}]` : String(p),
  );
  return parts.join(".").replace(/\.\[/g, "[");
}

/**
 * Turn an API failure into readable lines. Understands FastAPI's default
 * `{detail: [{loc, msg}]}` (422) and Retrace's envelope
 * `{error: {message, details: {errors: [{loc, msg}]}}}` (400).
 */
export function apiErrorLines(err: unknown): { summary: string; fields: string[] } {
  if (!(err instanceof ApiError)) {
    return {
      summary: err instanceof Error ? err.message : "The request failed.",
      fields: [],
    };
  }
  const body = err.body as
    | {
        detail?: unknown;
        error?: { message?: string; details?: { errors?: unknown } | null };
      }
    | null;
  let list: unknown = null;
  if (body && Array.isArray(body.detail)) list = body.detail;
  else if (body?.error?.details && Array.isArray(body.error.details.errors)) {
    list = body.error.details.errors;
  }
  const fields = Array.isArray(list)
    ? (list as FieldError[]).map((e) => {
        const where = formatLoc(e.loc);
        const msg = e.msg || e.message || "invalid";
        return where ? `${where}: ${msg}` : msg;
      })
    : [];
  let summary =
    body?.error?.message ||
    (typeof body?.detail === "string" ? body.detail : "") ||
    err.message ||
    `HTTP ${err.status}`;
  if (err.status === 401) summary = "Your session has expired. Sign in again.";
  return { summary: `${summary} (HTTP ${err.status})`, fields };
}
