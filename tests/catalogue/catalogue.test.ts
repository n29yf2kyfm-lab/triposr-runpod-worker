import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import type { VehicleAsset } from "../../src/types/vehicle-asset";

const cat: VehicleAsset[] = JSON.parse(
  readFileSync(new URL("../../platform/catalogue/catalogue.v2.json", import.meta.url), "utf-8"),
);

const MOJIBAKE = ["â€”", "â€“", "Â·", "Ã—", "ðŸ", "â†’", "â‰¤"];

describe("catalogue v2 integrity", () => {
  it("has entries", () => expect(cat.length).toBeGreaterThan(150));

  it("has no duplicate assetIds", () => {
    const ids = cat.map((e) => e.assetId);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every entry has a verbatim source title", () => {
    for (const e of cat) expect(e.sourceTitle.length, e.assetId).toBeGreaterThan(0);
  });

  it("contains no mojibake sequences anywhere", () => {
    const raw = JSON.stringify(cat);
    for (const m of MOJIBAKE) expect(raw.includes(m), `found ${m}`).toBe(false);
  });

  it("approved entries have https GLB URLs and are not rejected quality", () => {
    for (const e of cat.filter((e) => e.publicationStatus === "approved")) {
      expect(e.desktopGlbUrl.startsWith("https://"), e.assetId).toBe(true);
      expect(e.qualityGrade).not.toBe("rejected");
    }
  });

  it("no approved entry claims openable parts without separate geometry", () => {
    for (const e of cat.filter((e) => e.publicationStatus === "approved")) {
      if (e.supportsOpenableParts) {
        expect(e.hasSeparateDoors || e.hasSeparateBonnet || e.hasSeparateBoot, e.assetId).toBe(true);
      }
    }
  });

  it("no entry claims a verified OEM paint without a code", () => {
    for (const e of cat) {
      if (e.oemPaintVerified) expect(e.oemPaintCode, e.assetId).toBeTruthy();
    }
  });

  it("generated entries are graded approximate and cannot claim exact trim", () => {
    for (const e of cat.filter((e) => e.provenance === "generated-from-reference")) {
      expect(e.accuracyGrade, e.assetId).toBe("approximate");
      expect(e.exactTrim, e.assetId).toBe(false);
    }
  });

  it("year ranges are ordered", () => {
    for (const e of cat) {
      if (e.yearStart && e.yearEnd) expect(e.yearEnd, e.assetId).toBeGreaterThanOrEqual(e.yearStart);
    }
  });

  it("known stubs are quarantined", () => {
    for (const [make, model] of [["dacia", "logan"], ["skoda", "octavia"], ["suzuki", "jimny"], ["kia", "ceed"], ["mini", "countryman"]]) {
      const e = cat.find((e) => e.make === make && e.model === model);
      expect(e?.publicationStatus, `${make}/${model}`).toBe("quarantined");
    }
  });
});
