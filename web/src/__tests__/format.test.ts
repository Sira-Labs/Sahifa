import { describe, expect, it } from "vitest";
import { assetLabel, formatFailedShare, formatScoreInterval, scanSource, sortFindings } from "../format";
import { makeFinding, makeScan } from "./helpers";

describe("interval display", () => {
  it("reads value · low–high, full read at zero width, and — without a score", () => {
    expect(formatScoreInterval(92.7, 92.3, 93.1)).toBe("92.7 · 92.3–93.1");
    expect(formatScoreInterval(92.7, 92.7, 92.7)).toBe("92.7 · full read");
    expect(formatScoreInterval(null, null, null)).toBe("—");
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

  it("names the source of a scan", () => {
    expect(scanSource(makeScan())).toBe("shop");
    expect(scanSource(makeScan({ files: ["a.csv", "b.csv", "c.csv"] }))).toBe("Upload: 3 files");
    expect(scanSource(makeScan({ connection_name: "upload-5ca7", connection_kind: "upload", assets_count: null }))).toBe("Upload");
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
