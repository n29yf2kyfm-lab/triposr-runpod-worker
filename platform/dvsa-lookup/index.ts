// ExpertCarCheck — dvsa-lookup Edge Function
// Reg -> authoritative make / model / colour / fuel / year via the DVSA MOT
// History API. This is the source of truth for vehicle spec; the 3D catalogue
// is only matched on make+model afterwards. No spec is ever guessed.
//
// Deploy: supabase functions deploy dvsa-lookup
// SECRETS (set in Supabase → Edge Functions → Secrets, NEVER in code/frontend):
//   DVSA_CLIENT_ID, DVSA_CLIENT_SECRET, DVSA_API_KEY, DVSA_TOKEN_URL, DVSA_SCOPE

const TOKEN_URL = Deno.env.get("DVSA_TOKEN_URL")!;   // login.microsoftonline.com/{tenant}/oauth2/v2.0/token
const SCOPE = Deno.env.get("DVSA_SCOPE") ?? "https://tapi.dvsa.gov.uk/.default";
const CLIENT_ID = Deno.env.get("DVSA_CLIENT_ID")!;
const CLIENT_SECRET = Deno.env.get("DVSA_CLIENT_SECRET")!;
const API_KEY = Deno.env.get("DVSA_API_KEY")!;
const MOT_BASE = "https://history.mot.api.gov.uk/v1/trade/vehicles/registration";

const cors = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type, apikey",
};
const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...cors, "content-type": "application/json" } });

// cache the client-credentials token in memory (~1h) so we don't re-auth per call
let cached: { token: string; exp: number } | null = null;
async function getToken(): Promise<string> {
  if (cached && Date.now() < cached.exp - 60_000) return cached.token;
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: CLIENT_ID,
    client_secret: CLIENT_SECRET,
    scope: SCOPE,
  });
  const r = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!r.ok) throw new Error(`token ${r.status}`);
  const j = await r.json();
  cached = { token: j.access_token, exp: Date.now() + (j.expires_in ?? 3600) * 1000 };
  return cached.token;
}

function normaliseReg(reg: string): string {
  return reg.toUpperCase().replace(/\s+/g, "").trim();
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return json({}, 204);
  let reg = "";
  try {
    const url = new URL(req.url);
    reg = url.searchParams.get("reg") ?? (await req.json().catch(() => ({}))).reg ?? "";
  } catch { /* ignore */ }
  reg = normaliseReg(reg);
  if (!reg) return json({ error: "Provide a registration (?reg=…)" }, 400);

  try {
    const token = await getToken();
    const r = await fetch(`${MOT_BASE}/${encodeURIComponent(reg)}`, {
      headers: { authorization: `Bearer ${token}`, "x-api-key": API_KEY },
    });
    if (r.status === 404) return json({ found: false, reg }, 404);
    if (!r.ok) return json({ error: `DVSA ${r.status}` }, 502);
    const v = await r.json();

    const latestMot = Array.isArray(v.motTests) && v.motTests.length ? v.motTests[0] : null;
    const year = (v.firstUsedDate ?? v.registrationDate ?? v.manufactureDate ?? "").slice(0, 4);

    // Only pass through what DVSA actually returns — never fabricated.
    return json({
      found: true,
      reg: v.registration ?? reg,
      make: v.make ?? null,
      model: v.model ?? null,
      colour: v.primaryColour ?? null,
      fuel: v.fuelType ?? null,
      year: year || null,
      engineSize: v.engineSize ?? null,
      motStatus: latestMot?.testResult ?? null,
      motExpiry: latestMot?.expiryDate ?? null,
      source: "dvsa-mot-history",
    });
  } catch (e) {
    return json({ error: String(e).slice(0, 200) }, 500);
  }
});
