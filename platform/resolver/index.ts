// ExpertCarCheck — resolve-vehicle Edge Function (Phase 1)
// Input : a decoded vehicle spec — make / model / year / trim / colour / fuel.
// Output: the best-matching 3D asset + render-set manifest for the viewer.
//
// The registration is NOT an input here and is never stored or indexed. The app
// decodes the reg to these vehicle attributes; the catalogue is keyed on the
// attributes only.
//
// Hard rule: this function never triggers AI generation on the request path.
// If no exact asset exists it returns the nearest match instantly and enqueues
// an offline build job, so the exact model is cached for the next visitor.
//
// Deploy: supabase functions deploy resolve-vehicle
// Secrets: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

interface Decoded {
  make?: string;
  model?: string;
  year?: number;
  trim?: string;
  colour?: string;   // DVLA colour string
  bodyStyle?: string;
  fuel?: string;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
  });

// Score how well a catalogue row matches the decoded vehicle. Higher = better.
function score(row: any, d: Decoded): number {
  let s = 0;
  if (d.make && row.make === slug(d.make)) s += 40;
  if (d.model && row.model === slug(d.model)) s += 40;
  if (d.year && row.year_from && d.year >= row.year_from &&
      (!row.year_to || d.year <= row.year_to)) s += 15;
  if (d.bodyStyle && row.body_style === d.bodyStyle) s += 5;
  if (d.fuel && row.fuel === d.fuel) s += 3;
  if (d.trim && row.trim && row.trim.toLowerCase() === d.trim.toLowerCase()) s += 8;
  return s;
}

const slug = (x: string) =>
  x.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return json({}, 204);
  let d: Decoded = {};
  try { d = await req.json(); } catch { /* empty body */ }

  if (!d.make && !d.model) {
    return json({ error: "Provide at least make + model (the app decodes these from the reg)." }, 400);
  }

  // Pull candidate rows for the make (small set — the resolver view is flat).
  const { data: rows, error } = await supabase
    .from("variant_resolved")
    .select("*")
    .eq("make", slug(d.make ?? ""))
    .limit(500);

  if (error) return json({ error: error.message }, 500);
  if (!rows?.length) {
    // nothing for this make yet → tell the client to show a neutral placeholder
    return json({ match: "none", enqueue: true, vehicle: d }, 200);
  }

  // Rank; prefer a render set that matches the DVLA colour, else any.
  const ranked = rows
    .map((r) => ({ r, s: score(r, d) }))
    .sort((a, b) => b.s - a.s);

  const best = ranked[0];
  const exact = best.s >= 80;                       // make+model at minimum

  // colour match: same model, requested colour, else the base render set
  const colourMatch = d.colour
    ? rows.find((r) =>
        r.model === best.r.model &&
        (r.colour ?? "").toLowerCase() === d.colour!.toLowerCase())
    : undefined;

  const chosen = colourMatch ?? best.r;

  // Load the frame manifest so the client can start showing frames immediately.
  let manifest: unknown = null;
  if (chosen.manifest_url) {
    try {
      manifest = await (await fetch(chosen.manifest_url)).json();
    } catch { /* manifest optional */ }
  }

  return json({
    match: exact ? "exact" : "nearest",
    confidence: best.s / 103,
    enqueue: !exact,                                // build the exact one offline
    vehicle: {
      make: chosen.make, model: chosen.model, generation: chosen.generation,
      trim: chosen.trim, year: chosen.year_from, fuel: chosen.fuel,
      colour: chosen.colour, colourHex: chosen.colour_hex, bodyStyle: chosen.body_style,
    },
    asset: {
      tier: chosen.tier, glbUrl: chosen.glb_url,
      env: chosen.env, frameCount: chosen.frame_count,
      manifestUrl: chosen.manifest_url, manifest,
    },
  });
});
