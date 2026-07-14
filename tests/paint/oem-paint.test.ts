import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolveOemPaint, type OemPaint } from "../../src/lib/oem-paint-resolver";

const db = JSON.parse(readFileSync("data/oem-paints.json", "utf-8"));
const paints: OemPaint[] = db.paints;

describe("oem paint database", () => {
  it("loads the full user-provided database", () => {
    expect(paints.length).toBeGreaterThanOrEqual(270);
    for (const p of paints) {
      expect(p.manufacturer).toBeTruthy();
      expect(p.name).toBeTruthy();
      expect(p.dvlaColour).toMatch(/^[A-Z]+$/);
      expect(p.colourFamily).toBeTruthy();
    }
  });
});

describe("resolveOemPaint (workflow steps 4-8)", () => {
  it("filters by manufacturer then DVLA colour (steps 4-5)", () => {
    const r = resolveOemPaint("Audi", "GREY", paints);
    expect(r.status).toBe("candidates");
    expect(r.candidates.map((p) => p.name)).toContain("Nardo Grey");
    for (const p of r.candidates) {
      expect(p.manufacturer).toBe("Audi");
      expect(p.dvlaColour).toBe("GREY");
    }
  });

  it("is case/whitespace tolerant on inputs", () => {
    const r = resolveOemPaint("  audi ", " grey ", paints);
    expect(r.status).toBe("candidates");
  });

  it("returns unknown-make when the manufacturer is not in the database", () => {
    const r = resolveOemPaint("Koenigsegg", "GREY", paints);
    expect(r.status).toBe("unknown-make");
    expect(r.candidates).toHaveLength(0);
    expect(r.displayLine).toBeNull();
  });

  it("returns no-match when the make exists but not in that DVLA colour", () => {
    const someMake = paints[0].manufacturer;
    const coloursForMake = new Set(
      paints.filter((p) => p.manufacturer === someMake).map((p) => p.dvlaColour),
    );
    const missing = ["PINK", "TURQUOISE", "GOLD"].find((c) => !coloursForMake.has(c));
    if (!missing) return; // make covers everything — nothing to assert
    const r = resolveOemPaint(someMake, missing, paints);
    expect(r.status).toBe("no-match");
    expect(r.displayLine).toBeNull();
  });

  it("uses the rule-8 unconfirmed wording, never asserting the paint", () => {
    const r = resolveOemPaint("Audi", "GREY", paints);
    expect(r.displayLine).toMatch(/^Possible OEM colour: /);
    expect(r.confirmed).toBe(false);
  });

  it("image ranking reorders candidates but cannot add outsiders (step 6)", () => {
    const base = resolveOemPaint("Audi", "GREY", paints);
    const last = base.candidates[base.candidates.length - 1];
    const ranked = resolveOemPaint("Audi", "GREY", paints, [
      "Completely Made Up Paint",
      last.name,
    ]);
    expect(ranked.candidates[0].name).toBe(last.name);
    expect(ranked.candidates.map((p) => p.name).sort()).toEqual(
      base.candidates.map((p) => p.name).sort(),
    );
    expect(ranked.candidates.map((p) => p.name)).not.toContain("Completely Made Up Paint");
    expect(ranked.confirmed).toBe(false);
  });

  it("exposes the top candidate's colour family for the render palette", () => {
    const r = resolveOemPaint("Audi", "GREY", paints);
    expect(r.renderFamily).toBeTruthy();
    expect(r.candidates[0].colourFamily).toBe(r.renderFamily);
  });
});
