// Thin fetch wrapper with one typed function per route of specs 004 and 007. Every non-2xx answer
// becomes an ApiError carrying the API's `detail` as its message. Every request carries the
// CSRF header and the session cookie; a 401 sends the user to /login (spec 006).
import type {
  Asset,
  CheckAction,
  Connection,
  ConnectionCreate,
  ConnectionTest,
  Finding,
  FindingFilters,
  Health,
  Page,
  Scan,
  ScanCreate,
  ScanReport,
  StoredCheck,
  ValueCount,
  Version,
} from "./types";

const HEADERS = { Accept: "application/json", "X-Sahifa-Request": "1" };

// Called on any 401: the router sends the user to /login with the current path (spec 006).
let onUnauthorized: (() => void) | null = null;

/** Register what happens when the session is missing or expired. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** A failed request. `status` is 0 when the API could not be reached at all. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Parsed JSON of a body, or null. */
function parseJson(body: string): unknown {
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

/** The server's `detail` as one line: a string, or FastAPI's validation list as `field: msg`. */
export function detailText(detail: unknown): string | null {
  if (typeof detail === "string") return detail || null;
  if (Array.isArray(detail)) {
    const parts = (detail as ValidationItem[]).map((item) => {
      const field = item.loc?.filter((p) => p !== "body").join(".");
      return field ? `${field}: ${item.msg ?? "invalid"}` : (item.msg ?? "invalid");
    });
    return parts.length ? parts.join("; ") : null;
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return null;
}

// What to say when the API answered without a usable `detail`.
const STATUS_TEXT: Record<number, string> = {
  400: "The request was not accepted",
  401: "Your session has ended; sign in again",
  403: "This account has no access",
  404: "Not found",
  409: "The report is not ready yet",
  413: "The upload is too large",
  415: "This file type is not accepted",
  422: "The request was not valid",
  500: "The API failed while answering",
  502: "The API is not reachable behind the proxy",
  503: "The API is unavailable",
  504: "The API took too long to answer",
};

/** Fallback message for a status without a usable body. */
export function statusMessage(status: number, statusText = ""): string {
  const known = STATUS_TEXT[status];
  return known ? `${known} (${status})` : `${status} ${statusText}`.trim();
}

/** Error text from a response body: a JSON `message` for people (403 `no_access`), else its
 * `detail`, else short plain text; HTML pages keep the fallback. */
export function errorMessage(body: string, fallback: string): string {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown; message?: unknown } | null;
    if (typeof parsed?.message === "string" && parsed.message) return parsed.message;
    return detailText(parsed?.detail) ?? fallback;
  } catch {
    const text = body.trim();
    return text && !text.startsWith("<") ? text.slice(0, 300) : fallback;
  }
}

/** Fetch JSON; throws ApiError with the server's detail. A 401 also triggers the unauthorized
 * handler; 204 resolves to undefined. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", ...init, headers: { ...HEADERS, ...init.headers } });
  } catch {
    throw new ApiError(0, "Cannot reach the Sahifa API. Check your connection and try again.");
  }
  if (!res.ok) {
    const body = await res.text();
    if (res.status === 401) onUnauthorized?.();
    throw new ApiError(res.status, errorMessage(body, statusMessage(res.status, res.statusText)), parseJson(body));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** GET a JSON resource. */
export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

/** Send a JSON body with an unsafe method. */
export function apiSend<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Query string from the defined parameters, with a leading `?` or empty. */
export function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== "") q.set(key, String(value));
  const s = q.toString();
  return s ? `?${s}` : "";
}

const enc = encodeURIComponent;

type RawFinding = Partial<Finding> & {
  column_name?: string | null;
  evidence?: { examples?: ValueCount[]; sql?: string | null; check_id?: string; title?: string } | null;
};

/** A finding row as the page expects it. The findings table stores `column_name` and an
 * `evidence` object; the report embeds the core `Finding`. Both shapes are accepted. */
export function normalizeFinding(raw: RawFinding): Finding {
  const evidence = raw.evidence ?? {};
  const checkType = raw.check_type ?? "";
  return {
    id: raw.id,
    check_id: raw.check_id ?? evidence.check_id ?? checkType,
    check_type: checkType,
    title: raw.title ?? evidence.title ?? checkType,
    asset: raw.asset ?? "",
    column: raw.column ?? raw.column_name ?? null,
    dimension: raw.dimension ?? "validity",
    severity: raw.severity ?? "low",
    evaluated: raw.evaluated ?? 0,
    failed: raw.failed ?? 0,
    ratio: raw.ratio ?? 1,
    low: raw.low ?? raw.ratio ?? 1,
    high: raw.high ?? raw.ratio ?? 1,
    summary: raw.summary ?? "",
    next_step: raw.next_step ?? "",
    examples: raw.examples ?? evidence.examples ?? [],
    sql: raw.sql ?? evidence.sql ?? null,
  };
}

/** Multipart body of an upload scan. */
export function uploadForm(files: File[], sampleRows?: number): FormData {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  if (sampleRows !== undefined) form.append("sample_rows", String(sampleRows));
  return form;
}

export const api = {
  health: () => apiGet<Health>("/healthz"),
  version: () => apiGet<Version>("/api/version"),

  listConnections: () => apiGet<{ items: Connection[] }>("/api/connections"),
  getConnection: (id: string) => apiGet<Connection>(`/api/connections/${enc(id)}`),
  createConnection: (body: ConnectionCreate) => apiSend<Connection>("POST", "/api/connections", body),
  testConnection: (id: string) => apiSend<ConnectionTest>("POST", `/api/connections/${enc(id)}/test`),

  createScan: (body: ScanCreate) => apiSend<Scan>("POST", "/api/scans", body),
  uploadScan: (files: File[], sampleRows?: number) =>
    request<Scan>("/api/scans/upload", { method: "POST", body: uploadForm(files, sampleRows) }),
  listScans: (cursor?: string, limit = 25) => apiGet<Page<Scan>>(`/api/scans${query({ limit, cursor })}`),
  getScan: (id: string) => apiGet<Scan>(`/api/scans/${enc(id)}`),
  getReport: (id: string) => apiGet<ScanReport>(`/api/scans/${enc(id)}/report`),
  listFindings: async (id: string, filters: FindingFilters = {}) => {
    const page = await apiGet<{ items: RawFinding[] }>(
      `/api/scans/${enc(id)}/findings${query({ severity: filters.severity, dimension: filters.dimension, asset: filters.asset })}`,
    );
    return { items: page.items.map(normalizeFinding) };
  },

  listAssets: (connectionId: string, cursor?: string, limit = 200) =>
    apiGet<Page<Asset>>(`/api/assets${query({ connection_id: connectionId, limit, cursor })}`),
  /** The stored asset of a connection with this label, or null; walks the pages. */
  findAsset: async (connectionId: string, label: string): Promise<Asset | null> => {
    let cursor: string | undefined;
    do {
      const page = await api.listAssets(connectionId, cursor);
      const found = page.items.find((a) => a.label === label);
      if (found) return found;
      cursor = page.next_cursor ?? undefined;
    } while (cursor);
    return null;
  },
  listChecks: (assetId: string) => apiGet<StoredCheck[]>(`/api/checks${query({ asset_id: assetId })}`),
  changeCheck: (check: Pick<StoredCheck, "id" | "version">, action: CheckAction) =>
    apiSend<StoredCheck>("POST", `/api/checks/${enc(check.id)}/${action}`, { version: check.version }),
};
