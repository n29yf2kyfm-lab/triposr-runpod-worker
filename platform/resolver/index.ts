// ExpertCarCheck — resolve-vehicle Edge Function (v2)
//
// Audit finding A1: the previously deployed function was the Phase-1 additive
// scorer — make+model alone badged "exact", with no generation-conflict
// rejection, no year hard gate, no quarantine awareness and no disclosures.
// This replaces it with a faithful port of the tested v2 resolver
// (src/lib/vehicle-resolver.ts + vehicle-normalisation.ts, 34/34 tests):
//   - make + modelFamily are mandatory gates, never scored around
//   - confirmed generation conflict -> immediate rejection
//   - year outside the asset's range by >1 year -> rejection
//   - body-style conflict -> rejection
//   - only approved, non-rejected assets are candidates
//   - every response carries the honesty disclosure line
//
// OPERATIONAL THRESHOLD (measured 2026-07-15): the library's strict
// score<75 -> unavailable assumes generation/year-enriched asset metadata.
// The live catalogue only carries what source titles defensibly stated, so
// at 75 even the flagship Golf resolves unavailable (best=70). Until the
// metadata enrichment lands, MIN_SCORE=40 serves a conflict-free match as
// "representative" WITH its honest disclosure — the hard rejections above
// still make a wrong-generation serve impossible. Raise back to 75 when
// assets carry confirmed generations/years.
//
// Self-contained: no database. Reads the published v2 catalogue and alias
// tables from public storage at cold start (cached ~10 min). The registration
// is NOT an input and is never stored or logged. Never triggers AI generation.
//
// Deploy: supabase functions deploy resolve-vehicle
// Response keeps the old keys (match/confidence/vehicle/asset) so the current
// app keeps working, and adds `resolution` with the v2 truth.

const DATA_BASE =
  "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/resolver";
const CACHE_MS = 10 * 60 * 1000;
// see OPERATIONAL THRESHOLD note above — 75 once metadata enrichment lands
const MIN_SCORE = Number(Deno.env.get("RESOLVER_MIN_SCORE") ?? 40);

type Aliases = {
  make: Record<string, string>;
  model: Record<string, Record<string, string>>;
  generation: Record<string, Record<string, { yearStart: number; yearEnd: number | null }>>;
  bodyStyle: Record<string, string>;
  fuel: Record<string, string>;
};

let cache: { at: number; catalogue: any[]; aliases: Aliases } | null = null;

async function loadData(): Promise<{ catalogue: any[]; aliases: Aliases }> {
  if (cache && Date.now() - cache.at < CACHE_MS) return cache;
  const [catalogue, aliases] = await Promise.all([
    (await fetch(`${DATA_BASE}/catalogue.v2.json`)).json(),
    (await fetch(`${DATA_BASE}/aliases.json`)).json(),
  ]);
  cache = { at: Date.now(), catalogue, aliases };
  return cache;
}

// ---- normalisation (port of src/lib/vehicle-normalisation.ts) --------------
const clean = (s: string): string =>
  (s ?? "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[._/]+/g, " ")
    .replace(/[^a-z0-9 -]/g, "")
    .replace(/\s+/g, " ")
    .trim();

const slug = (s: string): string =>
  clean(s).replace(/ /g, "-").replace(/-+/g, "-").replace(/(^-|-$)/g, "");

function normaliseMake(raw: string, al: Aliases): string {
  const c = clean(raw);
  return slug(al.make[c] ?? c);
}

function normaliseModel(make: string, raw: string, al: Aliases): string {
  const mk = normaliseMake(make, al);
  const c = clean(raw);
  const table = al.model[mk] ?? {};
  if (table[c]) return slug(table[c]);
  const keys = Object.keys(table).sort((a, b) => b.length - a.length);
  for (const k of keys) if (c === k || c.startsWith(k + " ")) return slug(table[k]);
  return slug(c);
}

function normaliseBodyStyle(raw: string | undefined, al: Aliases): string | undefined {
  if (!raw) return undefined;
  const c = clean(raw);
  if (al.bodyStyle[c]) return al.bodyStyle[c];
  for (const [k, v] of Object.entries(al.bodyStyle)) if (c.includes(k)) return v;
  return undefined;
}

function inferGeneration(make: string, family: string, year: number | undefined, al: Aliases) {
  if (!year) return {};
  const gens = al.generation[`${make}/${family}`];
  if (!gens) return {};
  for (const [gen, info] of Object.entries(gens)) {
    if (year >= info.yearStart && year <= (info.yearEnd ?? 9999)) return { generation: gen };
  }
  return {};
}

// ---- v2 resolver (port of src/lib/vehicle-resolver.ts) ---------------------
const DISCLOSURES: Record<string, string> = {
  exact: "3D model matched to this vehicle specification.",
  "generation-correct":
    "3D model matched to this vehicle generation. Some trim details may differ.",
  representative:
    "Representative 3D model. Year, trim, wheels and styling details may differ.",
  "approximate-generated":
    "AI-generated representative model. Exterior details may differ from the real vehicle.",
  unavailable: "A reliable 3D model is not currently available for this vehicle.",
};

function scoreAsset(a: any, v: any) {
  const matched: string[] = [];
  if (slug(a.make) !== v.make) return { a, score: 0, matched, rejected: "make" };
  matched.push("make");
  const famOk = slug(a.modelFamily) === v.modelFamily ||
    (a.modelAliases ?? []).some((x: string) => slug(x) === v.modelFamily || slug(x) === v.model);
  if (!famOk) return { a, score: 0, matched, rejected: "modelFamily" };
  matched.push("modelFamily");

  let gen: boolean | undefined = undefined;
  if (v.generation && a.generation) {
    gen = slug(a.generation) === slug(v.generation) ||
      (a.generationAliases ?? []).some((x: string) => slug(x) === slug(v.generation));
    if (!gen) return { a, score: 0, matched, rejected: "generation-conflict" };
  }
  const y = v.year;
  if (y && a.yearStart != null) {
    const end = a.yearEnd ?? 9999;
    if (y < a.yearStart - 1 || y > end + 1) return { a, score: 0, matched, rejected: "year-out-of-range" };
  }
  if (v.bodyStyle && a.bodyStyle && v.bodyStyle !== a.bodyStyle) {
    return { a, score: 0, matched, rejected: "body-style-conflict" };
  }

  let score = 40;
  if (gen === true) { score += 35; matched.push("generation"); }
  if (y && a.yearStart != null && y >= a.yearStart && y <= (a.yearEnd ?? 9999)) {
    score += 30; matched.push("year");
  }
  if (v.bodyStyle && a.bodyStyle && v.bodyStyle === a.bodyStyle) { score += 15; matched.push("bodyStyle"); }
  if (v.fuel && (a.compatibleFuelTypes ?? []).map(clean).includes(v.fuel)) { score += 5; matched.push("fuel"); }
  if (v.trim && (a.compatibleTrimFamilies ?? []).map(clean).includes(v.trim)) { score += 5; matched.push("trim"); }
  if (a.provenance === "generated-from-reference" || a.accuracyGrade === "approximate") score -= 15;
  if (a.qualityGrade === "C") score -= 20;
  return { a, score: Math.max(0, Math.min(100, score)), matched };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
  });

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return json({}, 204);
  let d: any = {};
  try { d = await req.json(); } catch { /* empty body */ }
  if (!d.make || !d.model) {
    return json({ error: "Provide make + model (the app decodes these from the reg)." }, 400);
  }

  const { catalogue, aliases } = await loadData();
  const make = normaliseMake(d.make, aliases);
  const modelFamily = normaliseModel(d.make, d.model, aliases);
  const year = d.year ? Number(d.year) : undefined;
  const v = {
    make, modelFamily, model: slug(d.model),
    generation: d.generation ?? inferGeneration(make, modelFamily, year, aliases).generation,
    year,
    bodyStyle: normaliseBodyStyle(d.bodyStyle, aliases),
    fuel: d.fuel ? clean(d.fuel) : undefined,
    trim: d.trim ? clean(d.trim) : undefined,
  };

  const candidates = catalogue
    .filter((a: any) => a.publicationStatus === "approved" && a.qualityGrade !== "rejected")
    .map((a: any) => scoreAsset(a, v))
    .filter((s: any) => !s.rejected)
    .sort((x: any, y_: any) => y_.score - x.score);

  const best = candidates[0];
  if (!best || best.score < MIN_SCORE) {
    return json({
      match: "none", enqueue: true, vehicle: d,
      resolution: { type: "unavailable", score: best?.score ?? 0, disclosure: DISCLOSURES.unavailable },
    });
  }

  const a = best.a;
  let type = "representative";
  if (best.score >= 90) {
    type = a.exactTrim && best.matched.includes("derivative") ? "exact" : "generation-correct";
  }
  const disclosure = a.provenance === "generated-from-reference"
    ? DISCLOSURES["approximate-generated"] : DISCLOSURES[type];

  // colour variant: DVLA colour family -> pre-tinted GLB when one exists
  const fam = clean(d.colour ?? "");
  const variants: Record<string, string> = a.colourVariants ?? {};
  const variantKey = Object.keys(variants).find((k) => fam && clean(k).includes(fam));
  const glbUrl = variantKey ? variants[variantKey] : a.desktopGlbUrl;

  return json({
    // legacy keys, so the current app keeps working unchanged
    match: type === "exact" || type === "generation-correct" ? "exact" : "nearest",
    confidence: best.score / 100,
    enqueue: best.score < 90,
    vehicle: {
      make: a.make, model: a.model, generation: a.generation ?? null,
      year: a.yearStart ?? null, bodyStyle: a.bodyStyle ?? null,
      colour: d.colour ?? null,
    },
    asset: {
      tier: a.qualityGrade, glbUrl,
      mobileGlbUrl: a.mobileGlbUrl ?? null,
      manifestUrl: a.turntableUrl ?? null,
      colourVariants: variants,
    },
    // the v2 truth
    resolution: {
      type, score: best.score, assetId: a.assetId,
      matched: best.matched, disclosure,
      accuracyGrade: a.accuracyGrade, provenance: a.provenance,
    },
  });
});
