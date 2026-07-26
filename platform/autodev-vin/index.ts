// ExpertCarCheck — autodev-vin Edge Function
// VIN -> authoritative make / model / year / trim / body / engine via the
// auto.dev VIN decode API. Richer than the DVSA decode (adds trim, body,
// drivetrain, transmission) — feeds the resolve-vehicle scorer directly.
// No spec is ever guessed; only what auto.dev returns is passed through.
//
// Deploy: supabase functions deploy autodev-vin
// SECRET (set in Supabase → Edge Functions → Secrets, NEVER in code/frontend):
//   AUTODEV_API_KEY   (starts sk_ad_…)
//
// Privacy: the VIN is read ONLY from the POST body (never the query string,
// which edge/CDN/proxy layers log verbatim), and is never logged by this
// function. It travels to auto.dev in the upstream request path — unavoidable
// for that API, but that call is server-side.

const API_KEY = Deno.env.get("AUTODEV_API_KEY") ?? "";
const HOST = "https://api.auto.dev/vin";

const cors = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type, apikey",
  "access-control-allow-methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...cors, "content-type": "application/json" } });
// 204 is a null-body status — a body at 204 throws in Deno and breaks preflight.
const noContent = () => new Response(null, { status: 204, headers: cors });

// 17 chars, uppercase, no I/O/Q (ISO 3779).
const normaliseVin = (v: string) => (v ?? "").toUpperCase().replace(/\s+/g, "").trim();
const VIN_RE = /^[A-HJ-NPR-Z0-9]{17}$/;

// auto.dev body strings ("Coupe 2D", "Sedan 4D", "Sport Utility 4D") reduced to
// a family the resolver's alias table understands; unknown -> passed raw.
function bodyFamily(body: string | undefined): string | undefined {
  if (!body) return undefined;
  const b = body.toLowerCase();
  if (b.includes("coupe")) return "coupe";
  if (b.includes("convertible") || b.includes("roadster") || b.includes("spyder")) return "convertible";
  if (b.includes("sedan") || b.includes("saloon")) return "saloon";
  if (b.includes("wagon") || b.includes("estate") || b.includes("touring")) return "estate";
  if (b.includes("hatch")) return "hatchback";
  if (b.includes("suv") || b.includes("sport utility") || b.includes("crossover")) return "suv";
  if (b.includes("pickup") || b.includes("truck")) return "pickup";
  if (b.includes("van") || b.includes("minivan")) return "van";
  if (b.includes("mpv")) return "mpv";
  return body;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return noContent();
  if (req.method !== "POST") return json({ error: "Use POST." }, 405);
  if (!API_KEY) return json({ error: "autodev_not_configured" }, 500);

  let vin = "";
  try {
    vin = ((await req.json().catch(() => ({}))) as { vin?: string }).vin ?? "";
  } catch { /* ignore */ }
  vin = normaliseVin(vin);
  if (!VIN_RE.test(vin)) return json({ error: "Invalid VIN (17 chars, no I/O/Q)." }, 400);

  try {
    const r = await fetch(`${HOST}/${encodeURIComponent(vin)}?apiKey=${encodeURIComponent(API_KEY)}`,
      { signal: AbortSignal.timeout(8000) });
    if (r.status === 404) return json({ found: false, vin }, 404);
    if (!r.ok) return json({ error: `autodev ${r.status}` }, 502);
    const d = await r.json();
    if (d?.vinValid === false || !d?.make) return json({ found: false, vin }, 404);

    // Pass through only verified decode fields.
    const trim = d.trim ?? null;
    return json({
      found: true,
      vin: d.vin ?? vin,
      make: d.make ?? null,
      model: d.model != null ? String(d.model) : null,
      year: d.year ?? null,
      trim,
      body: d.body ?? null,
      engine: d.engine ?? null,
      drive: d.drive ?? null,
      transmission: d.transmission ?? null,
      squishVin: d.squishVin ?? null,
      // ready to hand straight to resolve-vehicle
      resolverInput: {
        make: d.make ?? null,
        model: d.model != null ? String(d.model) : null,
        year: d.year ?? null,
        bodyStyle: bodyFamily(d.body),
        trim,
        derivative: trim,
      },
      source: "auto.dev",
    });
  } catch (e) {
    // Never surface the raw exception (it can carry the upstream URL, which
    // embeds the API key and the VIN). Scrub the VIN before logging; return
    // a generic error to the caller.
    console.error("autodev-vin failed:", String(e).split(vin).join("<vin>"));
    return json({ error: "lookup_failed" }, 502);
  }
});
