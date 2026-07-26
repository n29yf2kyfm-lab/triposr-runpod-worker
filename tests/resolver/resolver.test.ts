import { describe, it, expect } from "vitest";
import { normaliseVehicle, normaliseMake, normaliseModel, normaliseColourFamily } from "../../src/lib/vehicle-normalisation";
import { resolveVehicle, scoreAsset, DISCLOSURES } from "../../src/lib/vehicle-resolver";
import type { VehicleAsset } from "../../src/types/vehicle-asset";
import type { VehicleIdentity } from "../../src/types/vehicle";

/** Build a VehicleIdentity directly so tests control generation/year without
 *  the year->generation inference confounding a boundary case. */
function vid(over: Partial<VehicleIdentity>): VehicleIdentity {
  return {
    make: "volkswagen", model: "golf", modelFamily: "golf",
    sourceConfidence: { make: 1, model: 1, year: 0, generation: 0, bodyStyle: 0, derivative: 0, colour: 0 },
    ...over,
  };
}

/** Minimal valid asset factory — real fields, no shortcuts. */
function asset(over: Partial<VehicleAsset>): VehicleAsset {
  return {
    schemaVersion: 2,
    assetId: "test-asset-v1",
    make: "volkswagen",
    model: "golf",
    modelFamily: "golf",
    provenance: "sourced",
    sourceTitle: "test",
    accuracyGrade: "representative",
    qualityGrade: "B",
    technicalStatus: "passed",
    visualStatus: "passed",
    publicationStatus: "approved",
    hasInterior: false,
    interiorMode: "none",
    supportsOpenableParts: false,
    defaultColourFamily: "grey",
    desktopGlbUrl: "https://example.com/x.glb",
    ...over,
  };
}

const golfMk7 = asset({
  assetId: "volkswagen-golf-mk7-hatch-2012-2017-v1",
  generation: "mk7", yearStart: 2012, yearEnd: 2017, bodyStyle: "hatchback",
});
const golfMk8 = asset({
  assetId: "volkswagen-golf-mk8-hatch-2020-2024-v1",
  generation: "mk8", yearStart: 2020, yearEnd: 2024, bodyStyle: "hatchback",
  modelAliases: ["golf gti", "golf gte", "golf r"],
  compatibleFuelTypes: ["petrol", "diesel", "hybrid"],
});
const a3_8p = asset({
  assetId: "audi-a3-8p-hatch-2003-2012-v1",
  make: "audi", model: "a3", modelFamily: "a3",
  generation: "8p", yearStart: 2003, yearEnd: 2012, bodyStyle: "hatchback",
});
const cClassW204 = asset({
  assetId: "mercedes-benz-c-class-w204-saloon-2007-2014-v1",
  make: "mercedes-benz", model: "c-class", modelFamily: "c-class",
  generation: "w204", yearStart: 2007, yearEnd: 2014, bodyStyle: "saloon",
});
const tiguanSuv = asset({
  assetId: "volkswagen-tiguan-mk2-suv-2016-2024-v1",
  model: "tiguan", modelFamily: "tiguan",
  generation: "mk2", yearStart: 2016, yearEnd: 2024, bodyStyle: "suv",
});
const passatEstate = asset({
  assetId: "volkswagen-passat-b8-estate-2014-2023-v1",
  model: "passat", modelFamily: "passat",
  generation: "b8", yearStart: 2014, yearEnd: 2023, bodyStyle: "estate",
});

describe("normalisation", () => {
  it("aliases makes", () => {
    expect(normaliseMake("VW")).toBe("volkswagen");
    expect(normaliseMake("Mercedes")).toBe("mercedes-benz");
    expect(normaliseMake("Opel")).toBe("vauxhall");
    expect(normaliseMake("Land Rover")).toBe("land-rover");
  });
  it("maps trims to model families", () => {
    expect(normaliseModel("VW", "Golf GTE")).toBe("golf");
    expect(normaliseModel("BMW", "320d")).toBe("3-series");
    expect(normaliseModel("Mercedes", "C220")).toBe("c-class");
    expect(normaliseModel("Mazda", "Mazda 6")).toBe("6");
    expect(normaliseModel("Peugeot", "2008")).toBe("2008");
  });
  it("treats DVLA colour as a family", () => {
    expect(normaliseColourFamily("GREY")).toBe("grey");
    expect(normaliseColourFamily("Metallic Blue")).toBe("blue");
    expect(normaliseColourFamily("Nardo")).toBe("unknown");
    expect(normaliseColourFamily("MULTI-COLOUR")).toBe("multicolour"); // hyphen tolerated
  });
  it("model fallback strips trailing trim words to the family (first token)", () => {
    // no alias table for an unknown make -> exercises the fallback directly
    expect(normaliseModel("Acme", "Widget Sport")).toBe("widget");
  });
  it("infers generation from year tables", () => {
    const v = normaliseVehicle({ make: "VW", model: "Golf GTE", manufactureYear: 2023 });
    expect(v.modelFamily).toBe("golf");
    expect(v.generation).toBe("mk8");
  });
});

describe("generation-aware resolver — mandated cases", () => {
  it("2023 Golf GTE must not resolve to Golf Mk7", () => {
    const v = normaliseVehicle({ make: "Volkswagen", model: "Golf GTE", manufactureYear: 2023, fuelType: "Hybrid Electric" });
    const r = resolveVehicle(v, [golfMk7]);
    expect(r.resolutionType).toBe("unavailable");
    expect(r.asset).toBeNull();
  });
  it("2023 Golf GTE resolves to Mk8 as generation-correct", () => {
    const v = normaliseVehicle({ make: "VW", model: "Golf GTE", manufactureYear: 2023, bodyStyle: "hatchback", fuelType: "Hybrid Electric" });
    const r = resolveVehicle(v, [golfMk7, golfMk8]);
    expect(r.asset?.assetId).toBe(golfMk8.assetId);
    expect(r.resolutionType).toBe("generation-correct");
    expect(r.score).toBeGreaterThanOrEqual(90);
  });
  it("modern Audi A3 must not resolve to 8P", () => {
    const v = normaliseVehicle({ make: "Audi", model: "A3", manufactureYear: 2022 });
    const r = resolveVehicle(v, [a3_8p]);
    expect(r.resolutionType).toBe("unavailable");
  });
  it("modern Mercedes C-Class must not resolve to W204", () => {
    const v = normaliseVehicle({ make: "Mercedes", model: "C220", manufactureYear: 2022 });
    const r = resolveVehicle(v, [cClassW204]);
    expect(r.resolutionType).toBe("unavailable");
  });
  it("SUV must not resolve to saloon", () => {
    const v = normaliseVehicle({ make: "Mercedes", model: "C-Class", manufactureYear: 2010, bodyStyle: "SUV" });
    const r = resolveVehicle(v, [cClassW204]);
    expect(r.resolutionType).toBe("unavailable");
  });
  it("hatchback must not resolve to estate", () => {
    const v = normaliseVehicle({ make: "VW", model: "Passat", manufactureYear: 2018, bodyStyle: "Hatchback" });
    const r = resolveVehicle(v, [passatEstate]);
    expect(r.resolutionType).toBe("unavailable");
  });
  it("correct generation with uncertain trim resolves as representative or better, with disclosure", () => {
    const v = normaliseVehicle({ make: "VW", model: "Golf", manufactureYear: 2021, trim: "Style" });
    const r = resolveVehicle(v, [golfMk8]);
    expect(r.asset?.assetId).toBe(golfMk8.assetId);
    expect(["representative", "generation-correct"]).toContain(r.resolutionType);
    expect(r.disclosure.length).toBeGreaterThan(10);
  });
  it("a wrong generation must return unavailable — never a cross-generation fallback", () => {
    const v = normaliseVehicle({ make: "VW", model: "Golf", manufactureYear: 2010 }); // mk6 era
    const r = resolveVehicle(v, [golfMk8]);
    expect(r.resolutionType).toBe("unavailable");
  });
});

describe("resolver policies", () => {
  it("quarantined assets never resolve", () => {
    const q = asset({ ...golfMk8, publicationStatus: "quarantined" });
    const v = normaliseVehicle({ make: "VW", model: "Golf", manufactureYear: 2021 });
    expect(resolveVehicle(v, [q]).resolutionType).toBe("unavailable");
  });
  it("generated assets carry the AI disclosure", () => {
    const gen = asset({
      ...golfMk8, assetId: "volkswagen-golf-gen-v1",
      provenance: "generated-from-reference", accuracyGrade: "approximate",
    });
    const v = normaliseVehicle({ make: "VW", model: "Golf", manufactureYear: 2021, bodyStyle: "hatchback" });
    const r = resolveVehicle(v, [gen]);
    expect(r.asset).not.toBeNull();          // assert resolution first — no vacuous pass
    expect(r.disclosure).toBe(DISCLOSURES["approximate-generated"]);
  });
  it("no year + no generation stays below the exact band (representative at best)", () => {
    const v = normaliseVehicle({ make: "VW", model: "Golf" });
    const r = resolveVehicle(v, [golfMk8]);
    expect(r.resolutionType === "unavailable" || r.resolutionType === "representative").toBe(true);
  });
  it("SUV asset accepted for SUV lookup (sanity)", () => {
    const v = normaliseVehicle({ make: "VW", model: "Tiguan Allspace", manufactureYear: 2022, bodyStyle: "SUV" });
    const r = resolveVehicle(v, [tiguanSuv]);
    expect(r.asset?.assetId).toBe(tiguanSuv.assetId);
  });
});

// A thin-metadata asset (no generation, no yearStart) is exactly the pre-
// enrichment shape that made the deployed minScore:40 path risky.
const golfThin = asset({ assetId: "vw-golf-thin-v1" }); // no generation, no yearStart
// A clean asset with a year range but no generation, for year-gate boundaries.
const golfYearOnly = asset({
  assetId: "vw-golf-yearonly-v1", yearStart: 2020, yearEnd: 2024, bodyStyle: "hatchback",
});

describe("deployed thin-metadata path (minScore 40)", () => {
  it("refuses a make+model-only match when the caller gave a year we cannot confirm", () => {
    // caller supplies a year (a discriminator) but the asset can't confirm it —
    // must not serve a possibly-wrong-generation shell.
    const v = vid({ manufactureYear: 2005 });
    const r = resolveVehicle(v, [golfThin], { minScore: 40 });
    expect(r.resolutionType).toBe("unavailable");
  });
  it("serves a representative when the caller gave NO discriminator to violate", () => {
    const v = vid({}); // make + model only, no year, no generation
    const r = resolveVehicle(v, [golfThin], { minScore: 40 });
    expect(r.resolutionType).toBe("representative");
    expect(r.asset?.assetId).toBe(golfThin.assetId);
  });
  it("serves when the year positively matches, even on thin generation metadata", () => {
    const v = vid({ manufactureYear: 2022 });
    const r = resolveVehicle(v, [golfYearOnly], { minScore: 40 });
    expect(r.asset?.assetId).toBe(golfYearOnly.assetId);
    expect(r.matchedFields).toContain("year");
  });
});

describe("year gate boundaries (±1 year tolerance)", () => {
  it("rejects a year 2+ before the range", () => {
    expect(scoreAsset(golfYearOnly, vid({ manufactureYear: 2018 })).rejected).toBe("year-out-of-range");
  });
  it("accepts the year at range start minus 1", () => {
    expect(scoreAsset(golfYearOnly, vid({ manufactureYear: 2019 })).rejected).toBeUndefined();
  });
  it("accepts the year at range end plus 1", () => {
    expect(scoreAsset(golfYearOnly, vid({ manufactureYear: 2025 })).rejected).toBeUndefined();
  });
  it("rejects a year 2+ after the range", () => {
    expect(scoreAsset(golfYearOnly, vid({ manufactureYear: 2026 })).rejected).toBe("year-out-of-range");
  });
});

describe("exact tier + deterministic tie-break", () => {
  it("an exact-derivative asset resolves as 'exact'", () => {
    const gti = asset({
      assetId: "vw-golf-gti-exact-v1", generation: "mk8", yearStart: 2020, yearEnd: 2024,
      bodyStyle: "hatchback", exactTrim: true, exactDerivative: "gti", qualityGrade: "A",
    });
    const v = vid({ generation: "mk8", manufactureYear: 2022, bodyStyle: "hatchback", derivative: "gti" });
    const r = resolveVehicle(v, [gti]);
    expect(r.resolutionType).toBe("exact");
    expect(r.disclosure).toBe(DISCLOSURES.exact);
  });
  it("breaks equal-score ties by accuracy/quality, not array order", () => {
    const worse = asset({
      assetId: "tie-worse", generation: "mk8", yearStart: 2020, yearEnd: 2024,
      bodyStyle: "hatchback", qualityGrade: "B", accuracyGrade: "representative",
    });
    const better = asset({
      assetId: "tie-better", generation: "mk8", yearStart: 2020, yearEnd: 2024,
      bodyStyle: "hatchback", qualityGrade: "A", accuracyGrade: "generation-correct",
    });
    const v = vid({ generation: "mk8", manufactureYear: 2022, bodyStyle: "hatchback" });
    expect(resolveVehicle(v, [worse, better]).asset?.assetId).toBe("tie-better");
    expect(resolveVehicle(v, [better, worse]).asset?.assetId).toBe("tie-better");
  });
});
