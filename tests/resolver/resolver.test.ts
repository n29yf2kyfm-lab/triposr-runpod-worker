import { describe, it, expect } from "vitest";
import { normaliseVehicle, normaliseMake, normaliseModel, normaliseColourFamily } from "../../src/lib/vehicle-normalisation";
import { resolveVehicle, DISCLOSURES } from "../../src/lib/vehicle-resolver";
import type { VehicleAsset } from "../../src/types/vehicle-asset";

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
    if (r.asset) expect(r.disclosure).toBe(DISCLOSURES["approximate-generated"]);
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
