/** Normalisation: raw DVLA/DVSA strings -> canonical VehicleIdentity fields.
 *  All alias data lives in data/*.json — no aliases hardcoded here. */
import type { VehicleIdentity, ColourFamily } from "../types/vehicle";
import makeAliases from "../../data/make-aliases.json" with { type: "json" };
import modelAliases from "../../data/model-aliases.json" with { type: "json" };
import generationAliases from "../../data/generation-aliases.json" with { type: "json" };
import bodyStyleAliases from "../../data/body-style-aliases.json" with { type: "json" };
import fuelAliases from "../../data/fuel-aliases.json" with { type: "json" };

const COLOUR_FAMILIES: ColourFamily[] = [
  "black", "white", "grey", "silver", "blue", "red", "green", "yellow",
  "orange", "brown", "beige", "purple", "gold", "bronze", "multicolour",
];

/** lowercase, collapse whitespace, strip punctuation except internal hyphens */
export function clean(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")      // accents
    .replace(/[._/]+/g, " ")
    .replace(/[^a-z0-9 -]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** canonical slug: spaces -> hyphens */
export function slug(s: string): string {
  return clean(s).replace(/ /g, "-").replace(/-+/g, "-").replace(/(^-|-$)/g, "");
}

export function normaliseMake(raw: string): string {
  const c = clean(raw);
  const aliased = (makeAliases as Record<string, string>)[c] ?? c;
  return slug(aliased);
}

/** Returns the canonical model-family slug for a make + raw model string.
 *  Tries the longest alias match first (e.g. "golf gte" before "golf"). */
export function normaliseModel(make: string, raw: string): string {
  const mk = normaliseMake(make);
  const c = clean(raw);
  const table = (modelAliases as Record<string, Record<string, string>>)[mk] ?? {};
  if (table[c]) return slug(table[c]);
  // longest-prefix alias ("golf gte dsg" -> "golf gte" -> golf)
  const keys = Object.keys(table).sort((a, b) => b.length - a.length);
  for (const k of keys) {
    if (c === k || c.startsWith(k + " ")) return slug(table[k]);
  }
  // fall back: first token run that isn't a trim word
  return slug(c);
}

export function normaliseBodyStyle(raw?: string | null): string | undefined {
  if (!raw) return undefined;
  const c = clean(raw);
  const direct = (bodyStyleAliases as Record<string, string>)[c];
  if (direct) return direct;
  for (const [k, v] of Object.entries(bodyStyleAliases as Record<string, string>)) {
    if (c.includes(k)) return v;
  }
  return undefined;
}

export function normaliseFuel(raw?: string | null): string | undefined {
  if (!raw) return undefined;
  const c = clean(raw);
  return (fuelAliases as Record<string, string>)[c]
    ?? Object.entries(fuelAliases as Record<string, string>).find(([k]) => c.includes(k))?.[1];
}

/** DVLA colour is a FAMILY, never an exact paint. */
export function normaliseColourFamily(raw?: string | null): ColourFamily {
  if (!raw) return "unknown";
  const c = clean(raw);
  return (COLOUR_FAMILIES.find((f) => c === f || c.includes(f)) ?? "unknown") as ColourFamily;
}

type GenInfo = { yearStart: number; yearEnd: number | null; aliases: string[] };

/** Infer generation from make/modelFamily + year using data tables.
 *  Returns undefined when the tables can't say — never guesses. */
export function inferGeneration(
  make: string, modelFamily: string, year?: number,
): { generation?: string; yearStart?: number; yearEnd?: number } {
  if (!year) return {};
  const key = `${normaliseMake(make)}/${slug(modelFamily)}`;
  const gens = (generationAliases as Record<string, Record<string, GenInfo>>)[key];
  if (!gens) return {};
  for (const [gen, info] of Object.entries(gens)) {
    const end = info.yearEnd ?? 9999;
    if (year >= info.yearStart && year <= end) {
      return { generation: gen, yearStart: info.yearStart, yearEnd: info.yearEnd ?? undefined };
    }
  }
  return {};
}

export type RawLookup = {
  registration?: string;
  make?: string; model?: string; colour?: string; fuelType?: string;
  bodyStyle?: string; manufactureYear?: number; registrationYear?: number;
  trim?: string; derivative?: string; transmission?: string;
};

/** Full raw-lookup -> VehicleIdentity normalisation. */
export function normaliseVehicle(raw: RawLookup): VehicleIdentity {
  const make = normaliseMake(raw.make ?? "");
  const modelFamily = normaliseModel(raw.make ?? "", raw.model ?? "");
  const year = raw.manufactureYear ?? raw.registrationYear;
  const gen = inferGeneration(make, modelFamily, year);
  return {
    registration: raw.registration,
    make,
    model: slug(raw.model ?? ""),
    modelFamily,
    generation: gen.generation,
    manufactureYear: raw.manufactureYear,
    registrationYear: raw.registrationYear,
    yearStart: gen.yearStart,
    yearEnd: gen.yearEnd,
    bodyStyle: normaliseBodyStyle(raw.bodyStyle),
    fuelType: normaliseFuel(raw.fuelType),
    transmission: raw.transmission ? clean(raw.transmission) : undefined,
    derivative: raw.derivative ? clean(raw.derivative) : undefined,
    trim: raw.trim ? clean(raw.trim) : undefined,
    colourFamily: normaliseColourFamily(raw.colour),
    sourceConfidence: {
      make: raw.make ? 1 : 0,
      model: raw.model ? 1 : 0,
      year: year ? 1 : 0,
      generation: gen.generation ? 0.9 : 0, // inferred from year tables, not stated
      bodyStyle: raw.bodyStyle ? 1 : 0,
      derivative: raw.derivative ? 1 : 0,
      colour: raw.colour ? 1 : 0,
    },
  };
}
