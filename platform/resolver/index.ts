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
//
// ---------------------------------------------------------------------------
// MOBILE SERVING (added 2026-08-21, DEFAULT OFF — see RESOLVER_MOBILE_SERVING)
//
// Audit finding: this resolver handed `desktopGlbUrl` to EVERY device.
// `mobileGlbUrl` was passed through as a separate field for the client to
// choose and the resolver never chose it, so every phone downloaded a desktop
// model. Measured on the live catalogue (1,044 resolver-eligible entries,
// 2026-08-21): median 11.0 MB, p90 34.4 MB, max 47.9 MB, 66.7% over 5 MB.
// It could not have worked client-side either: 1,042 of those 1,044 entries
// have `mobileGlbUrl` byte-identical to `desktopGlbUrl`, so there was nothing
// distinct to choose.
//
// The selection lives here rather than in the client because the resolver is
// the only place that sees the asset record, and because the client cannot be
// changed in lockstep with the catalogue.
//
// TWO SAFETY PROPERTIES, both unit-tested in tests/resolver/mobile-serving.test.ts:
//   1. With RESOLVER_MOBILE_SERVING unset (the default "off") the response is
//      byte-identical to the previous behaviour for every entry. The device is
//      still CLASSIFIED and REPORTED, so the mobile/desktop split can be
//      measured in production before anything about serving changes.
//   2. With it "on", a mobile asset is preferred ONLY when one exists and
//      DIFFERS from the desktop URL. No mobile asset -> the desktop URL, exactly
//      as today. A mobile path that 404s is worse than a heavy download.

const DATA_BASE =
  "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/resolver";
const CACHE_MS = 10 * 60 * 1000;

// Deno globals, declared and guarded so the pure helpers and `handler` below
// can be exercised by vitest under Node without a Deno runtime. `Deno.serve`
// is only invoked when the runtime actually provides it, so importing this
// module from a test is inert.
declare const Deno:
  | {
      env: { get(k: string): string | undefined };
      serve(h: (req: Request) => Response | Promise<Response>): unknown;
    }
  | undefined;

const envVar = (k: string): string | undefined =>
  typeof Deno !== "undefined" ? Deno.env.get(k) : undefined;

// see OPERATIONAL THRESHOLD note above — 75 once metadata enrichment lands
const MIN_SCORE = Number(envVar("RESOLVER_MIN_SCORE") ?? 40);

// Kill switch AND enable switch. Default "off" so the function can be deployed
// inert and turned on (and straight back off) with an env var, with no code
// change and no redeploy.
const MOBILE_SERVING = (envVar("RESOLVER_MOBILE_SERVING") ?? "off").trim().toLowerCase() === "on";

type Aliases = {
  make: Record<string, string>;
  model: Record<string, Record<string, string>>;
  generation: Record<string, Record<string, { yearStart: number; yearEnd: number | null }>>;
  bodyStyle: Record<string, string>;
  fuel: Record<string, string>;
};

let cache: { at: number; catalogue: any[]; aliases: Aliases } | null = null;

/** Drops the 10-minute cold-start cache. Used by the tests to isolate cases. */
export function resetDataCache(): void { cache = null; }

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

function scoreAsset(a: any, v: any, al: Aliases) {
  const matched: string[] = [];
  // The ASSET's make must go through the same alias map as the vehicle's, or
  // an aliased marque can never match. Measured 2026-08-13: DVLA returns
  // "VAUXHALL", which normalises to `vauxhall`, while four approved cars are
  // filed make="opel" and were slugged to `opel` here — half of the entire
  // Vauxhall library was unreachable for the exact lookups it exists to serve,
  // and Vauxhall is the UK's second marque. Catalogue make strings come from
  // source titles, so they carry whatever the uploader badged the car; the
  // resolver is the right place to reconcile that, not the data.
  if (normaliseMake(a.make, al) !== v.make) {
    return { a, score: 0, matched, rejected: "make" };
  }
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

// ---- device class ----------------------------------------------------------
export type DeviceClass = "mobile" | "desktop";
export type DeviceSource = "explicit" | "client-hint" | "user-agent" | "default";

// Deliberately narrow, and the asymmetry is deliberate too: a MISSED phone
// costs today's behaviour (a desktop file on a phone), while a misread desktop
// costs a smaller file on a big screen. Neither breaks, so this errs toward
// not firing.
//
// `Mobile Safari` is the token Android Chrome and iOS Safari both carry;
// desktop Chrome and desktop Safari carry `Safari` WITHOUT `Mobile`, which is
// why the space matters and why the desktop UAs are in the test list.
//
// KNOWN AND ACCEPTED MISS: iPadOS Safari reports itself as `Macintosh` and
// sends no client hints, so an iPad is classed desktop. That is the safe
// direction (it gets exactly what it gets today) and a large screen anyway.
const MOBILE_UA =
  /Android|iPhone|iPod|iPad|Mobile Safari|webOS|BlackBerry|IEMobile|Opera Mini|Windows Phone|Silk\//i;

/**
 * Decide the device class. Precedence is explicit > client hint > user agent,
 * so a client that knows (it can measure its own viewport) always wins over a
 * string we are guessing from.
 */
export function classifyDevice(input: {
  explicit?: string | null;
  clientHintMobile?: string | null; // Sec-CH-UA-Mobile: "?1" | "?0"
  userAgent?: string | null;
}): { device: DeviceClass; source: DeviceSource } {
  const e = (input.explicit ?? "").trim().toLowerCase();
  if (e === "mobile" || e === "phone") return { device: "mobile", source: "explicit" };
  if (e === "desktop") return { device: "desktop", source: "explicit" };
  // "auto", "", or anything unrecognised deliberately falls through.

  const ch = (input.clientHintMobile ?? "").trim();
  if (ch === "?1") return { device: "mobile", source: "client-hint" };
  if (ch === "?0") return { device: "desktop", source: "client-hint" };

  const ua = input.userAgent ?? "";
  if (ua) return { device: MOBILE_UA.test(ua) ? "mobile" : "desktop", source: "user-agent" };

  return { device: "desktop", source: "default" };
}

// ---- GLB selection ---------------------------------------------------------
/**
 * A mobile asset only counts when it EXISTS and DIFFERS from the desktop URL.
 * 1,042 of 1,044 approved entries carry mobileGlbUrl == desktopGlbUrl, and
 * treating those as "a mobile asset" would make every response claim a mobile
 * serve that never happened — the rollout could then not be verified at all.
 */
function distinctMobileUrl(candidate: unknown, desktopUrl: string): string | null {
  if (typeof candidate !== "string") return null;
  const m = candidate.trim();
  if (!m || m === desktopUrl) return null;
  return m;
}

export type GlbSelection = {
  glbUrl: string;
  desktopGlbUrl: string;
  mobileGlbUrl: string | null; // null = no DISTINCT mobile asset exists
  glbVariant: "mobile" | "desktop";
};

/**
 * COLOUR IS CHOSEN FIRST AND IS NEVER TRADED FOR WEIGHT.
 *
 * The variant path exists so a customer sees their own DVLA colour; handing a
 * phone the base grey car because no light variant was baked would be a
 * visible regression, not an optimisation. So a missing mobile variant falls
 * back to the DESKTOP variant of the SAME colour — never to a mobile car of
 * the wrong colour. Weight is the only thing this function ever changes.
 */
export function selectGlb(
  a: any,
  variantKey: string | undefined,
  device: DeviceClass,
): GlbSelection {
  const variants: Record<string, string> = a.colourVariants ?? {};
  const mobileVariants: Record<string, string> = a.mobileColourVariants ?? {};

  const desktopUrl: string = variantKey ? variants[variantKey] : a.desktopGlbUrl;
  const mobileUrl = variantKey
    ? distinctMobileUrl(mobileVariants[variantKey], desktopUrl)
    : distinctMobileUrl(a.mobileGlbUrl, desktopUrl);

  const useMobile = device === "mobile" && mobileUrl !== null;
  return {
    glbUrl: useMobile ? (mobileUrl as string) : desktopUrl,
    desktopGlbUrl: desktopUrl,
    mobileGlbUrl: mobileUrl,
    glbVariant: useMobile ? "mobile" : "desktop",
  };
}

// ---- HTTP ------------------------------------------------------------------
// `x-device` is listed so a browser preflight can carry it; the same value is
// also accepted in the JSON body and as ?device=, neither of which needs CORS.
const CORS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, OPTIONS",
  "access-control-allow-headers": "authorization, x-client-info, apikey, content-type, x-device",
  "access-control-max-age": "86400",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...CORS },
  });

export async function handler(req: Request): Promise<Response> {
  // 204 is a NULL-BODY status: `new Response("{}", { status: 204 })` throws a
  // TypeError in every WHATWG fetch implementation, so the old `json({}, 204)`
  // could only ever have produced a 500 on the CORS preflight. Reproduced
  // locally on the same implementation; see the test.
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

  let d: any = {};
  try { d = await req.json(); } catch { /* empty body */ }
  if (!d.make || !d.model) {
    return json({ error: "Provide make + model (the app decodes these from the reg)." }, 400);
  }

  // Device class. Explicit beats hints; a client that measures its own viewport
  // is a better witness than any string we sniff.
  let qsDevice: string | null = null;
  try { qsDevice = new URL(req.url).searchParams.get("device"); } catch { /* non-absolute URL */ }
  const { device, source: deviceSource } = classifyDevice({
    explicit: d.device ?? qsDevice ?? req.headers.get("x-device"),
    clientHintMobile: req.headers.get("sec-ch-ua-mobile"),
    userAgent: req.headers.get("user-agent"),
  });

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
    .map((a: any) => scoreAsset(a, v, aliases))
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

  // With MOBILE_SERVING off this is pinned to "desktop", which makes the
  // selection provably identical to the pre-2026-08-21 behaviour.
  const chosen = selectGlb(a, variantKey, MOBILE_SERVING ? device : "desktop");
  const glbUrl = chosen.glbUrl;

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
      // Additive: the desktop-weight URL for the SAME colour as glbUrl, so a
      // client that wants the heavy file on a big screen never has to
      // reconstruct it from colourVariants.
      desktopGlbUrl: chosen.desktopGlbUrl,
      // OFF: the raw catalogue field, exactly as before.
      // ON: the mobile-weight URL for the chosen colour, falling back to the
      // desktop one so this key is never null while glbUrl is a string — a
      // client that reads mobileGlbUrl unconditionally on a phone cannot be
      // handed a null by this change.
      mobileGlbUrl: MOBILE_SERVING
        ? (chosen.mobileGlbUrl ?? chosen.desktopGlbUrl)
        : (a.mobileGlbUrl ?? null),
      // "mobile" only when a DISTINCT mobile asset was actually served.
      glbVariant: chosen.glbVariant,
      manifestUrl: a.turntableUrl ?? null,
      colourVariants: variants,
    },
    // the v2 truth
    resolution: {
      type, score: best.score, assetId: a.assetId,
      matched: best.matched, disclosure,
      accuracyGrade: a.accuracyGrade, provenance: a.provenance,
      // Reported even while MOBILE_SERVING is off, so the mobile/desktop split
      // is measurable in production BEFORE any serving behaviour changes.
      device, deviceSource, mobileServing: MOBILE_SERVING,
    },
  });
}

if (typeof Deno !== "undefined") Deno.serve(handler);
