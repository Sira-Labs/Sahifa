import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MAX_UPLOAD_FILES } from "../constants";
import { fetchedUrls, json, makeScan, renderApp, stubFetch } from "./helpers";

/** A file with a given size, without allocating it. */
function file(name: string, size = 1024): File {
  const f = new File(["x"], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
}

const setup = () => userEvent.setup({ applyAccept: false });

describe("NewScan upload", () => {
  it("rejects wrong extensions and oversized files before anything is sent", async () => {
    const fetchFn = stubFetch((url) => {
      throw new Error(`unexpected ${url}`);
    });
    const user = setup();
    renderApp("/scans/new");

    const input = await screen.findByLabelText("Choose files");
    await user.upload(input, [file("orders.csv"), file("setup.exe"), file("huge.parquet", 201 * 1024 * 1024)]);

    const list = screen.getByRole("list", { name: "Selected files" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]!.textContent).not.toMatch(/not a supported|too large/i);
    expect(items[1]!.textContent).toMatch(/not a supported file type/i);
    expect(items[2]!.textContent).toMatch(/too large: 201 MB; the limit is 200 MB/i);

    await user.click(screen.getByRole("button", { name: /scan 3 files/i }));
    expect(screen.getByText(/remove the files marked above/i)).toBeTruthy();
    expect(fetchedUrls(fetchFn)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Remove setup.exe" }));
    await user.click(screen.getByRole("button", { name: "Remove huge.parquet" }));
    expect(screen.queryByText(/remove the files marked above/i)).toBeNull();
  });

  it("refuses more than the maximum number of files", async () => {
    const fetchFn = stubFetch((url) => {
      throw new Error(`unexpected ${url}`);
    });
    const user = setup();
    renderApp("/scans/new");
    const input = await screen.findByLabelText("Choose files");
    await user.upload(input, Array.from({ length: MAX_UPLOAD_FILES + 1 }, (_, i) => file(`t${i}.csv`)));
    expect(screen.getByRole("alert").textContent).toMatch(/too many files: 21 selected, at most 20/i);
    await user.click(screen.getByRole("button", { name: /scan 21 files/i }));
    expect(fetchedUrls(fetchFn)).toEqual([]);
  });

  it("asks for a file when none is chosen", async () => {
    stubFetch(() => ({}));
    const user = setup();
    renderApp("/scans/new");
    await user.click(await screen.findByRole("button", { name: "Start scan" }));
    expect(screen.getByRole("alert").textContent).toMatch(/add at least one file/i);
  });

  it("posts the files and goes to the report on 202", async () => {
    const created = makeScan({ id: "new-scan", status: "queued", score: null, findings: null });
    const fetchFn = stubFetch((url) => {
      if (url === "/api/scans/upload") return json(created, 202);
      if (url === "/api/scans/new-scan") return created;
      throw new Error(`unexpected ${url}`);
    });
    const user = setup();
    const { router } = renderApp("/scans/new");

    const input = await screen.findByLabelText("Choose files");
    await user.upload(input, [file("orders.csv"), file("events.ndjson")]);
    await user.click(screen.getByLabelText("Read everything"));
    await user.click(screen.getByRole("button", { name: "Scan 2 files" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/scans/new-scan"));
    const call = fetchFn.mock.calls.find((c) => c[0] === "/api/scans/upload")!;
    const form = call[1]!.body as FormData;
    expect(call[1]!.method).toBe("POST");
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(["orders.csv", "events.ndjson"]);
    expect(form.get("sample_rows")).toBe("0");
    expect(await screen.findByText(/waiting for a free scan slot/i)).toBeTruthy();
  });

  it("shows the API's refusal with a retry", async () => {
    stubFetch(() => json({ detail: "upload exceeds 200 MB" }, 413));
    const user = setup();
    renderApp("/scans/new");
    await user.upload(await screen.findByLabelText("Choose files"), [file("orders.csv")]);
    await user.click(screen.getByRole("button", { name: "Start scan" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("upload exceeds 200 MB");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

describe("NewScan connection", () => {
  it("tests a connection and starts a scan of it", async () => {
    const created = makeScan({ id: "conn-scan", status: "queued" });
    const fetchFn = stubFetch((url, init) => {
      if (url === "/api/connections")
        return {
          items: [
            { id: "c1", name: "shop", kind: "postgres", config: {}, secret_ref: "SAHIFA_CONN_SHOP", available: true, created_at: "2026-10-01T00:00:00Z" },
            { id: "u1", name: "upload-x", kind: "upload", config: {}, secret_ref: null, available: true, created_at: "2026-10-01T00:00:00Z" },
          ],
        };
      if (url === "/api/connections/c1/test") return { ok: true, assets: ["public.orders", "public.customers", "public.events"], error: null };
      if (url === "/api/scans" && init?.method === "POST") return json(created, 202);
      if (url === "/api/scans/conn-scan") return created;
      throw new Error(`unexpected ${url}`);
    });
    const user = setup();
    const { router } = renderApp("/scans/new");

    await user.click(await screen.findByRole("tab", { name: "Connection" }));
    expect(router.state.location.search).toEqual({ tab: "connection" });
    expect(await screen.findByRole("radio", { name: /shop/ })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /upload-x/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Test shop" }));
    expect(await screen.findByText("sees 3 assets")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Start scan" }));
    expect(screen.getByRole("alert").textContent).toMatch(/pick a connection/i);

    await user.click(screen.getByRole("radio", { name: /shop/ }));
    await user.clear(screen.getByLabelText("Rows per table"));
    await user.type(screen.getByLabelText("Rows per table"), "5000");
    await user.click(screen.getByRole("button", { name: "Start scan" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/scans/conn-scan"));
    const call = fetchFn.mock.calls.find((c) => c[0] === "/api/scans" && c[1]?.method === "POST")!;
    expect(JSON.parse(call[1]!.body as string)).toEqual({ connection_id: "c1", sample_rows: 5000 });
  });
});
