/**
 * customization-builder.ts — assemble an asset's Customization block (Tier A
 * configurator) from data and components WE OWN.
 *
 * The component taxonomy (wheels / wraps / colour options) follows the proven
 * shape used across the 3D-car-configurator market; the DATA is entirely ours:
 *   - colourOptions  ← the OEM paint DB (data/oem-paints.json), filtered to the
 *                       asset's make, mapped to render-palette families
 *   - wheelSets      ← GLBs produced by pipeline/blender/wheel_replace.py
 *   - wraps          ← wrap textures/GLBs from our own recolour pipeline
 *
 * configuratorReady is only set when the asset can actually support live
 * component swaps — a real body-paint material (so colour lands cleanly) and
 * at least one swappable set. Fused scan meshes never qualify.
 */
import { normaliseMake } from "./vehicle-normalisation";
import type { Customization, PaintFinish, WrapFinish, VehicleAsset } from "../types/vehicle-asset";
import type { ColourFamily } from "../types/vehicle";

// Valid wrap colour families (ColourFamily minus "unknown" — a wrap with an
// unknown family cannot be palette-resolved) and wrap finishes.
const WRAP_FAMILIES: ColourFamily[] = [
  "black", "white", "grey", "silver", "blue", "red", "green", "yellow",
  "orange", "brown", "beige", "purple", "gold", "bronze", "multicolour",
];
const WRAP_FINISHES: WrapFinish[] = ["gloss", "matte", "satin", "metallic", "pearl", "chrome"];

const toWrapFamily = (v: string): ColourFamily | null => {
  const c = (v ?? "").toLowerCase().trim();
  return (WRAP_FAMILIES as string[]).includes(c) ? (c as ColourFamily) : null;
};
const toWrapFinish = (v?: string): WrapFinish => {
  const c = (v ?? "").toLowerCase().trim();
  return (WRAP_FINISHES as string[]).includes(c) ? (c as WrapFinish) : "gloss";
};

export interface OemPaintRow {
  manufacturer: string;
  name: string;
  dvlaColour: string;
  colourFamily: string;
  finish: string;
}

export interface WheelSetInput {
  id: string; label: string; glbUrl: string;
  thumbnailUrl?: string | null; isDefault?: boolean;
}
export interface WrapInput {
  id: string; label: string; family: string;
  finish?: string; glbUrl?: string | null;
  textureUrl?: string | null; thumbnailUrl?: string | null;
}

const FINISH_MAP: Record<string, PaintFinish> = {
  solid: "solid", metallic: "metallic", pearl: "pearl", mica: "mica",
  "multi-coat": "multi-coat", "multicoat": "multi-coat",
  "tri-coat": "tri-coat", "tricoat": "tri-coat", matte: "matte",
  crystal: "crystal",
};

const normFinish = (f: string): PaintFinish =>
  FINISH_MAP[(f ?? "").toLowerCase().replace(/\s+/g, "-")] ?? "solid";

/** DVLA broad-colour string -> render-palette family slug. */
const FAMILY_MAP: Record<string, string> = {
  black: "black", white: "white", grey: "grey", gray: "grey",
  silver: "silver", blue: "blue", red: "red", green: "green",
  yellow: "yellow", orange: "orange", brown: "brown", beige: "beige",
  purple: "purple", gold: "gold", bronze: "bronze",
};
const familyFromDvla = (dvla: string): string =>
  FAMILY_MAP[(dvla ?? "").toLowerCase()] ?? "unknown";

/**
 * Build the colourOptions list for an asset from the OEM paint DB.
 * Only paints valid for the asset's manufacturer are included (the same
 * make-filter the OEM resolver enforces); each carries its family, display
 * name, and finish. Hex/GLB are left null here — the render worker resolves
 * the family to a palette RGB, and per-colour GLBs are attached later if
 * pre-tinted variants are baked.
 */
export function colourOptionsForAsset(
  asset: Pick<VehicleAsset, "make">,
  paints: OemPaintRow[],
): NonNullable<Customization["colourOptions"]> {
  const wantMake = normaliseMake(asset.make ?? "");
  const seen = new Set<string>();
  const out: NonNullable<Customization["colourOptions"]> = [];
  for (const p of paints) {
    if (normaliseMake(p.manufacturer) !== wantMake) continue;
    const key = `${p.name}|${p.colourFamily}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      family: familyFromDvla(p.dvlaColour),
      label: p.name,
      hex: null,
      finish: normFinish(p.finish),
      oemPaintName: p.name,
      glbUrl: null,
    });
  }
  return out;
}

/**
 * Assemble the full Customization block. configuratorReady requires a real
 * body-paint material (so recolour is clean, not a geometry guess) AND at
 * least one swappable dimension — otherwise the app must not offer live
 * customization for this asset.
 */
export function buildCustomization(
  asset: VehicleAsset,
  opts: {
    paints?: OemPaintRow[];
    wheelSets?: WheelSetInput[];
    wraps?: WrapInput[];
    componentPipelineVersion?: string;
  } = {},
): Customization {
  const colourOptions = opts.paints ? colourOptionsForAsset(asset, opts.paints) : [];
  const wheelSets = opts.wheelSets ?? [];
  // Validate each wrap against the ColourFamily/WrapFinish unions rather than
  // casting: an unknown family (e.g. "burgundy") can't be palette-resolved, so
  // drop it instead of laundering it through the type as if it were valid.
  const wraps: NonNullable<Customization["wraps"]> = [];
  for (const w of opts.wraps ?? []) {
    const family = toWrapFamily(w.family);
    if (family === null) continue;
    wraps.push({
      id: w.id, label: w.label, family, finish: toWrapFinish(w.finish),
      glbUrl: w.glbUrl ?? null, textureUrl: w.textureUrl ?? null,
      thumbnailUrl: w.thumbnailUrl ?? null,
    });
  }

  const hasRealPaint = (asset.paintMaterialNames?.length ?? 0) > 0;
  const hasSwaps =
    colourOptions.length > 0 || wheelSets.length > 0 || wraps.length > 0;

  return {
    configuratorReady: hasRealPaint && hasSwaps && asset.qualityGrade !== "rejected"
      && asset.publicationStatus === "approved",
    componentPipelineVersion: opts.componentPipelineVersion ?? null,
    wheelSets,
    wraps,
    colourOptions,
  };
}
