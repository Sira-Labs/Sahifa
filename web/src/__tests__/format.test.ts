import { describe, expect, it } from "vitest";
import {
  assetLabel,
  describeScore,
  formatFailedShare,
  formatIntervalRange,
  formatScoreInterval,
  scanFailureAdvice,
  scanSource,
  versionLine,
  sortFindings,
} from "../format";
import { makeFinding, makeScan } from "./helpers";

describe("interval display", () => {
  it("reads value · low–high, full read only when every row was read, and — without a score", () => {
    expect(formatScoreInterval(92.7, 92.3, 93.1)).toBe("92.7 · 92.3–93.1");
    expect(formatScoreInterval(92.7, 92.7, 92.7, "full")).toBe("92.7 · full read");
    // Bounds rounded to one decimal can be equal for a sample: never a full read then.
    expect(formatScoreInterval(92.7, 92.7, 92.7, "sampled")).toBe("92.7 · 92.7–92.7");
    expect(formatScoreInterval(92.7, 92.7, 92.7)).toBe("92.7 · 92.7–92.7");
    expect(formatScoreInterval(92.7, 92.3, 93.1, "full")).toBe("92.7 · 92.3–93.1");
    expect(formatScoreInterval(null, null, null)).toBe("—");
    expect(describeScore(99.0, 99.0, 99.0, "full")).toBe("99.0, every row read, no sampling interval");
    expect(describeScore(99.0, 99.0, 99.0, "sampled")).toBe("99.0, 95 % interval 99.0 to 99.0");
    expect(describeScore(99.0, 99.0, 99.0)).toBe("99.0, 95 % interval 99.0 to 99.0");
    expect(formatIntervalRange(99.0, 99.0, "full")).toBe("full read");
    expect(formatIntervalRange(99.0, 99.0, "sampled")).toBe("99.0–99.0");
  });

  it("turns a pass share and its interval into the failed share", () => {
    expect(formatFailedShare(0.9376, 0.931, 0.9437)).toBe("6.2 % · 5.6–6.9 %");
    expect(formatFailedShare(0.9, 0.9, 0.9)).toBe("10.0 % · full read");
  });
});

describe("helpers", () => {
  it("orders findings by severity, then failed share", () => {
    const out = sortFindings([
      makeFinding({ severity: "low", ratio: 0.5, summary: "l" }),
      makeFinding({ severity: "critical", ratio: 0.99, summary: "c-small" }),
      makeFinding({ severity: "critical", ratio: 0.8, summary: "c-big" }),
    ]);
    expect(out.map((f) => f.summary)).toEqual(["c-big", "c-small", "l"]);
  });

  it("writes the footer's version line, with the commit when the image knows it", () => {
    const version = { version: "0.1.0", schema_revision: "0011" };
    expect(versionLine({ ...version, commit: "edcf1717787a57d3678926cf562dd213a240b993" })).toBe("Sahifa 0.1.0 (edcf171) · schema 0011");
    expect(versionLine({ ...version, commit: "unknown" })).toBe("Sahifa 0.1.0 · schema 0011");
    expect(versionLine({ ...version, commit: "test" })).toBe("Sahifa 0.1.0 · schema 0011");
  });

  it("names the source of a scan", () => {
    expect(scanSource(makeScan())).toBe("shop");
    expect(scanSource(makeScan({ files: ["a.csv", "b.csv", "c.csv"] }))).toBe("Upload: 3 files");
    expect(scanSource(makeScan({ connection_name: "upload-5ca7", connection_kind: "upload", assets_count: null }))).toBe("Upload");
    expect(scanSource(makeScan({ demo: true, connection_kind: "upload", files: ["a.csv", "b.csv"] }))).toBe("Demo data");
  });

  it("says what to do about a failed scan by its reason", () => {
    const advice = (reason: string | null) => scanFailureAdvice(reason);
    expect(advice("connection shop has no source: set SAHIFA_CONN_SHOP")).toContain("is not set on the API");
    expect(advice("could not translate host name \"db\" to address")).toContain("cannot be reached");
    expect(advice("connection failed: timeout expired")).toContain("cannot be reached");
    expect(advice('FATAL: password authentication failed for user "reader"')).toContain("login was refused");
    expect(advice("permission denied for table orders")).toContain("SELECT rights");
    expect(advice("canceling statement due to statement timeout")).toContain("time limit");
    expect(advice("IO Error: No files found that match the pattern")).toContain("Upload them again");
    expect(advice("interrupted by a restart")).toBeNull();
    expect(advice(null)).toBeNull();
  });
});

describe("asset labels", () => {
  it("match the core: lossless when a part holds a dot or a quote", () => {
    expect(assetLabel({ namespace: "public", name: "orders", kind: "table" })).toBe("public.orders");
    expect(assetLabel({ namespace: "", name: "orders", kind: "file" })).toBe("orders");
    expect(assetLabel({ namespace: "a.b", name: "c", kind: "table" })).toBe('"a.b".c');
    expect(assetLabel({ namespace: "a", name: "b.c", kind: "table" })).toBe('a."b.c"');
    expect(assetLabel({ namespace: "", name: 'say "hi"', kind: "file" })).toBe('"say ""hi"""');
  });
});
