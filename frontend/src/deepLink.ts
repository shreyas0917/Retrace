/**
 * Deep links: `?execution=<id>` opens Investigate on that execution.
 *
 * The parameter survives the login screen because the app never rewrites the
 * URL while signed out; once authenticated, App reads the id it parsed at
 * start-up and opens it.
 */

/** Same character family the backend accepts for ids (uuid, ext-…, etc.). */
const ID_RE = /^[A-Za-z0-9._:-]{1,128}$/;

export function readExecutionParam(search: string): string | null {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return null;
  }
  const raw = params.get("execution");
  if (raw == null) return null;
  const id = raw.trim();
  return ID_RE.test(id) ? id : null;
}

/** Return `href` with `execution` set to `id`, or removed when `id` is empty. */
export function urlWithExecution(href: string, id: string | null | undefined): string {
  const url = new URL(href);
  if (id) url.searchParams.set("execution", id);
  else url.searchParams.delete("execution");
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Push (or replace) the current history entry so the URL names `id`. */
export function syncExecutionUrl(id: string | null | undefined, replace = false): void {
  if (typeof window === "undefined") return;
  const next = urlWithExecution(window.location.href, id);
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  if (replace) window.history.replaceState(null, "", next);
  else window.history.pushState(null, "", next);
}
