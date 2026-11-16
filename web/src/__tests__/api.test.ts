import { describe, expect, it } from "vitest";
import { ApiError, api, errorAdvice, errorMessage, errorReference, normalizeFinding, query, statusMessage } from "../api";
import { json, makeFinding, stubFetch } from "./helpers";

/** The error a call rejects with. */
async function failure(p: Promise<unknown>): Promise<ApiError> {
  const err = await p.catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  return err as ApiError;
}

describe("error mapping", () => {
  it("uses JSON detail, validation lists, short plain text, and the fallback for HTML or empty bodies", () => {
    expect(errorMessage(JSON.stringify({ detail: "scan not found" }), "404")).toBe("scan not found");
    expect(errorMessage(JSON.stringify({ detail: [{ loc: ["body", "files"], msg: "Field required" }] }), "422")).toBe(
      "files: Field required",
    );
    expect(errorMessage(JSON.stringify({ detail: { message: "busy" } }), "503")).toBe("busy");
    expect(errorMessage("upstream timed out\n", "504")).toBe("upstream timed out");
    expect(errorMessage("<html><body>Bad gateway</body></html>", "fallback")).toBe("fallback");
    expect(errorMessage("", "fallback")).toBe("fallback");
  });

  it("carries the API's detail and status", async () => {
    stubFetch(() => json({ detail: "file type .exe is not accepted" }, 415));
    const err = await failure(api.uploadScan([new File(["x"], "a.exe")]));
    expect(err.status).toBe(415);
    expect(err.message).toBe("file type .exe is not accepted");
    expect(err.body).toEqual({ detail: "file type .exe is not accepted" });
  });

  it("names the status when the body says nothing useful", async () => {
    stubFetch(() => new Response("<html>413</html>", { status: 413, statusText: "Payload Too Large" }));
    expect((await failure(api.getScan("s"))).message).toBe("The upload is too large (413)");
    stubFetch(() => new Response("", { status: 409 }));
    expect((await failure(api.getReport("s"))).message).toBe("The report is not ready yet (409)");
    expect(statusMessage(418, "I'm a teapot")).toBe("418 I'm a teapot");
  });

  it("shows the security limits' own sentences (spec 012)", async () => {
    const limited = { detail: "rate_limited", retry_after: 30, message: "Too many requests, try again in 30 s." };
    stubFetch(() => json(limited, 429));
    const err = await failure(api.createScan({ connection_id: "c" }));
    expect(err.status).toBe(429);
    expect(err.message).toBe("Too many requests, try again in 30 s.");
    stubFetch(() => json({ detail: { code: "content_mismatch", file: "a.parquet", message: "a.parquet does not look like a PARQUET file. Text files must be UTF-8." } }, 415));
    expect((await failure(api.uploadScan([new File(["x"], "a.parquet")]))).message).toMatch(/does not look like a PARQUET file/);
    stubFetch(() => json({ detail: "too_large", limit_mb: 1024, message: "The request is larger than 1024 MB." }, 413));
    expect((await failure(api.uploadScan([new File(["x"], "a.csv")]))).message).toBe("The request is larger than 1024 MB.");
    // Without a usable body, as from a proxy in front.
    expect(statusMessage(429)).toBe("Too many requests; wait a moment and try again (429)");
    expect(statusMessage(507)).toBe("The server is low on disk space (507)");
  });

  it("maps a network failure to status 0", async () => {
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const err = await failure(api.listScans());
    expect(err.status).toBe(0);
    expect(err.message).toMatch(/cannot reach the sahifa api/i);
  });
});

describe("error reference (spec 023)", () => {
  const answer = (status: number, id?: string) =>
    new Response(JSON.stringify({ detail: "internal_error", message: "Sahifa hit an error it did not expect." }), {
      status,
      headers: id ? { "Content-Type": "application/json", "X-Request-ID": id } : { "Content-Type": "application/json" },
    });

  it("is on the error of a failed call, and null without the header", async () => {
    stubFetch((url) => answer(500, url === "/healthz" ? "0123456789abcdef0123456789abcdef" : undefined));
    expect((await failure(api.health())).requestId).toBe("0123456789abcdef0123456789abcdef");
    expect((await failure(api.getScan("s1"))).requestId).toBeNull();
  });

  it("is shown for 500 and above only", () => {
    const error = (status: number) => new ApiError(status, "x", null, "ref-12345678");
    for (const status of [500, 502, 503, 504, 507]) expect(errorReference(error(status))).toBe("ref-12345678");
    for (const status of [0, 400, 403, 404, 413, 429]) expect(errorReference(error(status))).toBeNull();
    expect(errorReference(new ApiError(500, "x"))).toBeNull();
    expect(errorReference(new Error("x"))).toBeNull();
  });
});

describe("error advice", () => {
  it("says what to do where the status says it", () => {
    const advice = (status: number) => errorAdvice(new ApiError(status, "x"));
    expect(advice(0)).toContain("docker compose ps");
    expect(advice(403)).toContain("editor role");
    expect(advice(413)).toContain("SAHIFA_MAX_UPLOAD_MB");
    expect(advice(415)).toContain("CSV, TSV, Parquet and JSON lines");
    expect(advice(429)).toContain("Wait a minute");
    expect(advice(500)).toContain("API's log");
    for (const status of [502, 503, 504]) expect(advice(status)).toContain("starting or down");
    expect(advice(507)).toContain("SAHIFA_UPLOAD_TTL_DAYS");
  });

  it("adds nothing where the message says it all", () => {
    for (const status of [400, 401, 404, 409, 422]) expect(errorAdvice(new ApiError(status, "x"))).toBeNull();
    expect(errorAdvice(new Error("x"))).toBeNull();
  });
});

describe("requests", () => {
  it("builds list, report and findings URLs", async () => {
    const fetchFn = stubFetch((url) => (url.includes("findings") ? { items: [] } : { items: [], next_cursor: null }));
    await api.listScans();
    await api.listScans("c1", 10);
    await api.listFindings("a/b", { severity: "high", asset: "public.orders" });
    expect(fetchFn.mock.calls.map((c) => c[0])).toEqual([
      "/api/scans?limit=25",
      "/api/scans?limit=10&cursor=c1",
      "/api/scans/a%2Fb/findings?severity=high&asset=public.orders",
    ]);
    expect(query({ a: undefined, b: "", c: 0 })).toBe("?c=0");
  });

  it("posts a scan as JSON and an upload as multipart", async () => {
    const fetchFn = stubFetch(() => json({ id: "s1", status: "queued" }, 202));
    await api.createScan({ connection_id: "c1", sample_rows: 0 });
    let init = fetchFn.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ connection_id: "c1", sample_rows: 0 });

    await api.uploadScan([new File(["a,b"], "orders.csv"), new File(["{}"], "events.jsonl")], 500);
    init = fetchFn.mock.calls[1]![1]!;
    const form = init.body as FormData;
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(["orders.csv", "events.jsonl"]);
    expect(form.get("sample_rows")).toBe("500");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("posts a connection test", async () => {
    const fetchFn = stubFetch(() => ({ ok: true, assets: 5, error: null }));
    expect(await api.testConnection("c 1")).toEqual({ ok: true, assets: 5, error: null });
    expect(fetchFn.mock.calls[0]![0]).toBe("/api/connections/c%201/test");
    expect(fetchFn.mock.calls[0]![1]!.method).toBe("POST");
  });
});

describe("normalizeFinding", () => {
  it("accepts the stored row shape with column_name and evidence", () => {
    const f = makeFinding();
    const row = { ...f, column: undefined, column_name: "customer_id", examples: undefined, sql: undefined, evidence: { examples: f.examples, sql: "SELECT 2" } };
    const out = normalizeFinding(row);
    expect(out.column).toBe("customer_id");
    expect(out.examples).toEqual(f.examples);
    expect(out.sql).toBe("SELECT 2");
  });
});
