/** Generation-aware deterministic resolver.
 *
 *  Hard rules (non-negotiable, see docs/asset-quality-policy.md):
 *  - make + modelFamily are mandatory gates, never scored around
 *  - a confirmed generation conflict is an immediate rejection
 *  - year outside the asset's range by more than 1 year: rejection
 *  - body-style conflict: rejection
 *  - score < 75 -> unavailable ("no model" beats "wrong model")
 *  - never silently cross generations because make+model matched
 */
import type { VehicleIdentity, VehicleResolution, ResolutionType } from "../types/vehicle";
import type { VehicleAsset } from "../types/vehicle-asset";
import { slug, clean } from "./vehicle-normalisation";

export const DISCLOSURES: Record<ResolutionType | "approximate-generated", string> = {
  exact: "3D model matched to this vehicle specification.",
  "generation-correct":
    "3D model matched to this vehicle generation. Some trim details may differ.",
  representative:
    "Representative 3D model. Year, trim, wheels and styling details may differ.",
  "approximate-generated":
    "AI-generated representative model. Exterior details may differ from the real vehicle.",
  unavailable: "A reliable 3D model is not currently available for this vehicle.",
};

const UNAVAILABLE: VehicleResolution = {
  asset: null, score: 0, resolutionType: "unavailable",
  matchedFields: [], mismatchedFields: [], missingFields: [],
  disclosure: DISCLOSURES.unavailable,
};

type Scored = {
  asset: VehicleAsset; score: number;
  matched: string[]; mismatched: string[]; missing: string[];
  rejected?: string;
};

function modelFamilyMatches(asset: VehicleAsset, v: VehicleIdentity): boolean {
  if (slug(asset.modelFamily) === v.modelFamily) return true;
  return (asset.modelAliases ?? []).some((a) => slug(a) === v.modelFamily || slug(a) === v.model);
}

function generationMatches(asset: VehicleAsset, v: VehicleIdentity): boolean | undefined {
  if (!v.generation || !asset.generation) return undefined;   // unknowable
  if (slug(asset.generation) === slug(v.generation)) return true;
  return (asset.generationAliases ?? []).some((a) => slug(a) === slug(v.generation!));
}

export function scoreAsset(asset: VehicleAsset, v: VehicleIdentity): Scored {
  const matched: string[] = [];
  const mismatched: string[] = [];
  const missing: string[] = [];

  // ---- mandatory gates -----------------------------------------------
  if (slug(asset.make) !== v.make) return { asset, score: 0, matched, mismatched: ["make"], missing, rejected: "make" };
  matched.push("make");
  if (!modelFamilyMatches(asset, v)) return { asset, score: 0, matched, mismatched: ["modelFamily"], missing, rejected: "modelFamily" };
  matched.push("modelFamily");

  // ---- hard rejections -------------------------------------------------
  const gen = generationMatches(asset, v);
  if (gen === false) return { asset, score: 0, matched, mismatched: ["generation"], missing, rejected: "generation-conflict" };

  const y = v.manufactureYear ?? v.registrationYear;
  if (y && asset.yearStart != null) {
    const end = asset.yearEnd ?? 9999;
    if (y < asset.yearStart - 1 || y > end + 1) {
      return { asset, score: 0, matched, mismatched: ["year"], missing, rejected: "year-out-of-range" };
    }
  }
  if (v.bodyStyle && asset.bodyStyle && v.bodyStyle !== asset.bodyStyle) {
    return { asset, score: 0, matched, mismatched: ["bodyStyle"], missing, rejected: "body-style-conflict" };
  }

  // ---- scoring -----------------------------------------------------------
  let score = 40; // make + model family established
  if (gen === true) { score += 35; matched.push("generation"); }
  else if (gen === undefined && (v.generation || asset.generation)) missing.push("generation");

  if (y && asset.yearStart != null && y >= asset.yearStart && y <= (asset.yearEnd ?? 9999)) {
    score += 30; matched.push("year");
  } else if (y && asset.yearStart == null) missing.push("year-range");

  if (v.bodyStyle && asset.bodyStyle && v.bodyStyle === asset.bodyStyle) { score += 15; matched.push("bodyStyle"); }
  else if (!v.bodyStyle || !asset.bodyStyle) missing.push("bodyStyle");

  if (v.fuelType && (asset.compatibleFuelTypes ?? []).map(clean).includes(v.fuelType)) {
    score += 5; matched.push("fuel");
  }
  if (v.derivative && asset.exactDerivative && clean(asset.exactDerivative) === v.derivative) {
    score += 10; matched.push("derivative");
  }
  if (v.trim && (asset.compatibleTrimFamilies ?? []).map(clean).includes(v.trim)) {
    score += 5; matched.push("trim");
  }

  // ---- penalties --------------------------------------------------------
  if (asset.provenance === "generated-from-reference" || asset.accuracyGrade === "approximate") score -= 15;
  if (asset.qualityGrade === "C") score -= 20;

  return { asset, score: Math.max(0, Math.min(100, score)), matched, mismatched, missing };
}

export function resolveVehicle(
  v: VehicleIdentity,
  catalogue: VehicleAsset[],
  opts?: { minScore?: number },
): VehicleResolution {
  // Default 75 assumes generation/year-enriched asset metadata. The deployed
  // Edge Function passes 40 until enrichment lands (audit A1, 2026-07-15):
  // the hard rejections above still make wrong-generation serves impossible;
  // a conflict-free thin-metadata match serves as "representative" with its
  // honest disclosure instead of blanking the product.
  const minScore = opts?.minScore ?? 75;
  const candidates = catalogue
    .filter((a) => a.publicationStatus === "approved" && a.qualityGrade !== "rejected")
    .map((a) => scoreAsset(a, v))
    .filter((s: Scored) => !s.rejected);

  if (candidates.length === 0) return { ...UNAVAILABLE };
  candidates.sort((a: Scored, b: Scored) => b.score - a.score);
  const best = candidates[0];

  if (best.score < minScore) return { ...UNAVAILABLE };

  let resolutionType: ResolutionType;
  if (best.score >= 90) {
    resolutionType = best.asset.exactTrim && best.matched.includes("derivative")
      ? "exact" : "generation-correct";
  } else {
    resolutionType = "representative";
  }

  const disclosure = best.asset.provenance === "generated-from-reference"
    ? DISCLOSURES["approximate-generated"]
    : DISCLOSURES[resolutionType];

  return {
    asset: best.asset,
    score: best.score,
    resolutionType,
    matchedFields: best.matched,
    mismatchedFields: best.mismatched,
    missingFields: best.missing,
    disclosure,
  };
}
