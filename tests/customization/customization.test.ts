import { describe, it, expect } from "vitest";
import {
  buildCustomization, colourOptionsForAsset, type OemPaintRow,
} from "../../src/lib/customization-builder";
import type { VehicleAsset } from "../../src/types/vehicle-asset";

function asset(over: Partial<VehicleAsset>): VehicleAsset {
  return {
    schemaVersion: 2, assetId: "test-asset-v1",
    make: "volkswagen", model: "golf", modelFamily: "golf",
    provenance: "sourced", sourceTitle: "test",
    accuracyGrade: "representative", qualityGrade: "B",
    technicalStatus: "passed", visualStatus: "passed",
    publicationStatus: "approved", hasInterior: false, interiorMode: "none",
    supportsOpenableParts: false, defaultColourFamily: "grey",
    desktopGlbUrl: "https://example.com/x.glb", ...over,
  };
}

const paints: OemPaintRow[] = [
  { manufacturer: "Volkswagen", name: "Pure White", dvlaColour: "WHITE", colourFamily: "White", finish: "Solid" },
  { manufacturer: "Volkswagen", name: "Atlantic Blue", dvlaColour: "BLUE", colourFamily: "Dark Blue", finish: "Metallic" },
  { manufacturer: "Audi", name: "Nardo Grey", dvlaColour: "GREY", colourFamily: "Gunmetal Grey", finish: "Solid" },
];

describe("colourOptionsForAsset", () => {
  it("keeps only the asset make's paints and maps family + finish", () => {
    const opts = colourOptionsForAsset(asset({ make: "volkswagen" }), paints);
    expect(opts).toHaveLength(2);                       // Audi paint excluded
    expect(opts.map((o) => o.label).sort()).toEqual(["Atlantic Blue", "Pure White"]);
    const blue = opts.find((o) => o.label === "Atlantic Blue")!;
    expect(blue.family).toBe("blue");
    expect(blue.finish).toBe("metallic");
    expect(blue.oemPaintName).toBe("Atlantic Blue");
  });
});

describe("buildCustomization", () => {
  it("marks configuratorReady when a real paint material + swaps exist", () => {
    const c = buildCustomization(
      asset({ paintMaterialNames: ["Car_Paint"] }),
      { paints, wheelSets: [{ id: "oem-18", label: "18\" OEM", glbUrl: "https://e/w.glb", isDefault: true }] },
    );
    expect(c.configuratorReady).toBe(true);
    expect(c.colourOptions).toHaveLength(2);
    expect(c.wheelSets).toHaveLength(1);
  });

  it("refuses configuratorReady on a fused shell with no paint material", () => {
    const c = buildCustomization(asset({ paintMaterialNames: [] }), { paints });
    expect(c.configuratorReady).toBe(false);            // no real paint -> no live config
    expect(c.colourOptions).toHaveLength(2);            // options still listed for render-side use
  });

  it("refuses configuratorReady on a rejected/quarantined asset", () => {
    const c = buildCustomization(
      asset({ paintMaterialNames: ["Car_Paint"], publicationStatus: "quarantined" }),
      { paints, wheelSets: [{ id: "a", label: "A", glbUrl: "https://e/w.glb" }] },
    );
    expect(c.configuratorReady).toBe(false);
  });
});
