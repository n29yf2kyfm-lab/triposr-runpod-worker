/**
 * Mobile serving path — platform/resolver/index.ts
 *
 * The audit finding this covers: the resolver handed `desktopGlbUrl` to every
 * device and never chose `mobileGlbUrl`. These tests pin BOTH directions —
 * that a phone gets the mobile asset when one exists, and that it gets exactly
 * today's desktop asset when one does not. The second is the one that matters:
 * a mobile path that 404s is worse than a heavy download.
 *
 * The regression block runs against platform/catalogue/catalogue.v2.json, which
 * was verified byte-identical (sha256) to the catalogue the live resolver
 * fetches, so those are real live entries and not fixtures.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { classifyDevice, selectGlb } from "../../platform/resolver/index";

// ---------------------------------------------------------------------------
// device classification
// ---------------------------------------------------------------------------

// Real UA strings. The desktop list is the half that proves the regex can FAIL:
// a gate only tested against what it should catch is not a tested gate.
const MOBILE_UAS: Array<[string, string]> = [
  ["Android Chrome", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"],
  ["iPhone Safari", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"],
  ["iPhone Chrome", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.0.0 Mobile/15E148 Safari/604.1"],
  ["legacy iPad", "Mozilla/5.0 (iPad; CPU OS 12_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.0 Mobile/15E148 Safari/604.1"],
  ["Android Firefox", "Mozilla/5.0 (Android 14; Mobile; rv:121.0) Gecko/121.0 Firefox/121.0"],
  ["Samsung Internet", "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36"],
];

const DESKTOP_UAS: Array<[string, string]> = [
  ["macOS Chrome", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"],
  ["macOS Safari", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"],
  ["Windows Chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"],
  ["Windows Edge", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"],
  ["Linux Firefox", "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"],
  ["curl", "curl/8.5.0"],
];

describe("classifyDevice — must fire", () => {
  for (const [name, ua] of MOBILE_UAS) {
    it(`classifies ${name} as mobile`, () => {
      expect(classifyDevice({ userAgent: ua })).toEqual({ device: "mobile", source: "user-agent" });
    });
  }
  it("honours the Sec-CH-UA-Mobile client hint", () => {
    expect(classifyDevice({ clientHintMobile: "?1" })).toEqual({ device: "mobile", source: "client-hint" });
  });
  it("honours an explicit device request", () => {
    expect(classifyDevice({ explicit: "mobile" })).toEqual({ device: "mobile", source: "explicit" });
    expect(classifyDevice({ explicit: " MOBILE " })).toEqual({ device: "mobile", source: "explicit" });
    expect(classifyDevice({ explicit: "phone" })).toEqual({ device: "mobile", source: "explicit" });
  });
});

describe("classifyDevice — must NOT fire", () => {
  for (const [name, ua] of DESKTOP_UAS) {
    it(`classifies ${name} as desktop`, () => {
      expect(classifyDevice({ userAgent: ua }).device).toBe("desktop");
    });
  }
  it("classifies a Sec-CH-UA-Mobile ?0 as desktop even on a mobile-looking UA", () => {
    const ua = MOBILE_UAS[0][1];
    expect(classifyDevice({ clientHintMobile: "?0", userAgent: ua })).toEqual({
      device: "desktop", source: "client-hint",
    });
  });
  it("defaults to desktop when nothing at all is known", () => {
    expect(classifyDevice({})).toEqual({ device: "desktop", source: "default" });
  });
  it("does not treat an unrecognised explicit value as mobile", () => {
    expect(classifyDevice({ explicit: "tablet-ish" }).device).toBe("desktop");
    expect(classifyDevice({ explicit: "auto", userAgent: DESKTOP_UAS[0][1] }).device).toBe("desktop");
  });
  it("KNOWN MISS, asserted so it is a decision and not a surprise: iPadOS Safari reads as desktop", () => {
    // Modern iPadOS reports itself as Macintosh and sends no client hints.
    const ipadOS = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15";
    expect(classifyDevice({ userAgent: ipadOS }).device).toBe("desktop");
  });
});

describe("classifyDevice — precedence", () => {
  it("explicit beats both hint and user agent", () => {
    expect(classifyDevice({
      explicit: "desktop", clientHintMobile: "?1", userAgent: MOBILE_UAS[0][1],
    })).toEqual({ device: "desktop", source: "explicit" });
  });
  it("client hint beats user agent", () => {
    expect(classifyDevice({
      clientHintMobile: "?1", userAgent: DESKTOP_UAS[0][1],
    })).toEqual({ device: "mobile", source: "client-hint" });
  });
});

// ---------------------------------------------------------------------------
// selection + the fallback that matters
// ---------------------------------------------------------------------------
const DESK = "https://cdn.example/car.glb";
const MOB = "https://cdn.example/car_mobile.glb";

describe("selectGlb — mobile asset exists", () => {
  it("serves the mobile asset to a phone", () => {
    const s = selectGlb({ desktopGlbUrl: DESK, mobileGlbUrl: MOB }, undefined, "mobile");
    expect(s.glbUrl).toBe(MOB);
    expect(s.glbVariant).toBe("mobile");
    expect(s.desktopGlbUrl).toBe(DESK);
  });
  it("still serves the desktop asset to a desktop", () => {
    const s = selectGlb({ desktopGlbUrl: DESK, mobileGlbUrl: MOB }, undefined, "desktop");
    expect(s.glbUrl).toBe(DESK);
    expect(s.glbVariant).toBe("desktop");
  });
});

describe("selectGlb — FALLBACK: no mobile asset means today's desktop asset", () => {
  const noMobile: Array<[string, Record<string, unknown>]> = [
    ["mobileGlbUrl absent", { desktopGlbUrl: DESK }],
    ["mobileGlbUrl null", { desktopGlbUrl: DESK, mobileGlbUrl: null }],
    ["mobileGlbUrl empty string", { desktopGlbUrl: DESK, mobileGlbUrl: "" }],
    ["mobileGlbUrl whitespace", { desktopGlbUrl: DESK, mobileGlbUrl: "   " }],
    ["mobileGlbUrl IDENTICAL to desktop (the live case, 1042/1044)", { desktopGlbUrl: DESK, mobileGlbUrl: DESK }],
    ["mobileGlbUrl a non-string", { desktopGlbUrl: DESK, mobileGlbUrl: 12345 }],
  ];
  for (const [name, a] of noMobile) {
    it(`${name} -> desktop URL, marked desktop`, () => {
      const s = selectGlb(a, undefined, "mobile");
      expect(s.glbUrl).toBe(DESK);
      expect(s.glbVariant).toBe("desktop");
      expect(s.mobileGlbUrl).toBeNull();
    });
  }
});

describe("selectGlb — colour variants", () => {
  const base = {
    desktopGlbUrl: DESK,
    mobileGlbUrl: MOB,
    colourVariants: { blue: "https://cdn.example/car__blue.glb", red: "https://cdn.example/car__red.glb" },
  };

  it("serves the mobile variant of the SAME colour when one exists", () => {
    const a = { ...base, mobileColourVariants: { blue: "https://cdn.example/car__blue_mobile.glb" } };
    const s = selectGlb(a, "blue", "mobile");
    expect(s.glbUrl).toBe("https://cdn.example/car__blue_mobile.glb");
    expect(s.glbVariant).toBe("mobile");
    expect(s.desktopGlbUrl).toBe("https://cdn.example/car__blue.glb");
  });

  it("COLOUR IS NEVER TRADED FOR WEIGHT: a missing mobile variant falls back to the DESKTOP variant of that colour, not to the mobile base", () => {
    const a = { ...base, mobileColourVariants: { blue: "https://cdn.example/car__blue_mobile.glb" } };
    const s = selectGlb(a, "red", "mobile");            // red has no mobile variant
    expect(s.glbUrl).toBe("https://cdn.example/car__red.glb");
    expect(s.glbUrl).not.toBe(MOB);                     // never the grey base
    expect(s.glbVariant).toBe("desktop");
  });

  it("no mobileColourVariants at all -> every colour serves the desktop variant", () => {
    const s = selectGlb(base, "blue", "mobile");
    expect(s.glbUrl).toBe("https://cdn.example/car__blue.glb");
    expect(s.glbVariant).toBe("desktop");
  });

  it("a mobile variant identical to its desktop variant does not count as mobile", () => {
    const a = { ...base, mobileColourVariants: { blue: "https://cdn.example/car__blue.glb" } };
    const s = selectGlb(a, "blue", "mobile");
    expect(s.glbUrl).toBe("https://cdn.example/car__blue.glb");
    expect(s.glbVariant).toBe("desktop");
  });

  it("desktop keeps exactly the pre-change variant behaviour", () => {
    const a = { ...base, mobileColourVariants: { blue: "https://cdn.example/car__blue_mobile.glb" } };
    expect(selectGlb(a, "blue", "desktop").glbUrl).toBe("https://cdn.example/car__blue.glb");
  });
});

// ---------------------------------------------------------------------------
// regression against the REAL live catalogue
// ---------------------------------------------------------------------------
type Entry = Record<string, any>;
const CATALOGUE: Entry[] = JSON.parse(
  readFileSync(new URL("../../platform/catalogue/catalogue.v2.json", import.meta.url), "utf-8"),
);
const APPROVED = CATALOGUE.filter(
  (e) => e.publicationStatus === "approved" && e.qualityGrade !== "rejected",
);
/** The exact expression the resolver used before this change. */
const legacyUrl = (a: Entry, k: string | undefined) =>
  k ? (a.colourVariants ?? {})[k] : a.desktopGlbUrl;
const firstVariantKey = (a: Entry) => Object.keys(a.colourVariants ?? {})[0];

describe("live catalogue regression", () => {
  it("has entries to test", () => {
    expect(APPROVED.length).toBeGreaterThan(1000);
  });

  it("DESKTOP selection is byte-identical to the pre-change expression on every approved entry, base and variant", () => {
    for (const a of APPROVED) {
      expect(selectGlb(a, undefined, "desktop").glbUrl).toBe(legacyUrl(a, undefined));
      const k = firstVariantKey(a);
      if (k) expect(selectGlb(a, k, "desktop").glbUrl).toBe(legacyUrl(a, k));
    }
  });

  it("MOBILE selection changes ONLY where a distinct mobile asset exists — everywhere else it is today's URL", () => {
    const changed: string[] = [];
    const withDistinct: string[] = [];
    for (const a of APPROVED) {
      const m = a.mobileGlbUrl;
      const distinct = typeof m === "string" && m.trim() !== "" && m.trim() !== a.desktopGlbUrl;
      if (distinct) withDistinct.push(a.assetId);
      const url = selectGlb(a, undefined, "mobile").glbUrl;
      if (url !== legacyUrl(a, undefined)) changed.push(a.assetId);
    }
    // the set that moves is exactly the set that has somewhere to move to
    expect(changed.sort()).toEqual(withDistinct.sort());
  });

  it("every approved entry whose mobileGlbUrl equals desktopGlbUrl serves the desktop file to a phone", () => {
    const same = APPROVED.filter((a) => a.mobileGlbUrl === a.desktopGlbUrl);
    expect(same.length).toBeGreaterThan(1000); // 1,042 measured 2026-08-21
    for (const a of same) {
      const s = selectGlb(a, undefined, "mobile");
      expect(s.glbUrl).toBe(a.desktopGlbUrl);
      expect(s.glbVariant).toBe("desktop");
    }
  });

  it("the one live entry that DOES have a distinct mobile asset is served it", () => {
    const subaru = APPROVED.find((a) => a.assetId === "subaru-impreza-x-2010-2012-v1");
    expect(subaru, "subaru-impreza-x-2010-2012-v1 present in the live catalogue").toBeTruthy();
    const s = selectGlb(subaru!, undefined, "mobile");
    expect(s.glbUrl).toBe(subaru!.mobileGlbUrl);
    expect(s.glbVariant).toBe("mobile");
    expect(selectGlb(subaru!, undefined, "desktop").glbUrl).toBe(subaru!.desktopGlbUrl);
  });

  it("no approved entry carries mobileColourVariants yet, so no colour can change weight today", () => {
    const withMobileVariants = APPROVED.filter(
      (a) => a.mobileColourVariants && Object.keys(a.mobileColourVariants).length > 0,
    );
    // Tripwire: this is 0 until the compression run lands. When it is not 0,
    // that is the signal the variant path has real assets behind it.
    expect(withMobileVariants.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// end-to-end through the handler, with the env switch on and off
// ---------------------------------------------------------------------------
const TEST_ASSET = {
  assetId: "test-golf-v1",
  make: "volkswagen", model: "golf", modelFamily: "golf",
  publicationStatus: "approved", qualityGrade: "B",
  accuracyGrade: "representative", provenance: "sourced",
  desktopGlbUrl: DESK, mobileGlbUrl: MOB,
  colourVariants: { blue: "https://cdn.example/car__blue.glb" },
  mobileColourVariants: { blue: "https://cdn.example/car__blue_mobile.glb" },
  turntableUrl: null,
};

// "vw" -> "volkswagen" is needed or the make gate rejects before any GLB is
// picked; the resolver aliases the ASSET's make through the same table.
const TEST_ALIASES = { make: { vw: "volkswagen" }, model: {}, generation: {}, bodyStyle: {}, fuel: {} };

async function loadResolver(env: Record<string, string> = {}) {
  vi.resetModules();
  vi.stubGlobal("Deno", { env: { get: (k: string) => env[k] }, serve: () => {} });
  vi.stubGlobal("fetch", async (url: string) =>
    new Response(JSON.stringify(String(url).includes("aliases") ? TEST_ALIASES : [TEST_ASSET]), {
      headers: { "content-type": "application/json" },
    }));
  const mod = await import("../../platform/resolver/index");
  mod.resetDataCache();
  return mod;
}

const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://edge.example/resolve-vehicle", {
    method: "POST", headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });

afterEach(() => { vi.unstubAllGlobals(); });

describe("handler — RESOLVER_MOBILE_SERVING off (the default)", () => {
  it("serves the desktop URL to a phone, exactly as before the change", async () => {
    const mod = await loadResolver();                       // no env at all
    const r = await mod.handler(post({ make: "VW", model: "Golf" }, { "user-agent": MOBILE_UAS[0][1] }));
    const j = await r.json();
    expect(j.asset.glbUrl).toBe(DESK);
    expect(j.asset.glbVariant).toBe("desktop");
    expect(j.asset.mobileGlbUrl).toBe(MOB);                 // raw pass-through, unchanged
    expect(j.resolution.mobileServing).toBe(false);
  });
  it("still REPORTS the device, so the split is measurable before anything is switched on", async () => {
    const mod = await loadResolver();
    const r = await mod.handler(post({ make: "VW", model: "Golf" }, { "user-agent": MOBILE_UAS[0][1] }));
    const j = await r.json();
    expect(j.resolution.device).toBe("mobile");
    expect(j.resolution.deviceSource).toBe("user-agent");
  });
});

describe("handler — RESOLVER_MOBILE_SERVING on", () => {
  const ON = { RESOLVER_MOBILE_SERVING: "on" };

  it("serves the mobile asset to a phone", async () => {
    const mod = await loadResolver(ON);
    const r = await mod.handler(post({ make: "VW", model: "Golf" }, { "user-agent": MOBILE_UAS[0][1] }));
    const j = await r.json();
    expect(j.asset.glbUrl).toBe(MOB);
    expect(j.asset.glbVariant).toBe("mobile");
    expect(j.asset.desktopGlbUrl).toBe(DESK);
  });

  it("serves the desktop asset to a desktop", async () => {
    const mod = await loadResolver(ON);
    const r = await mod.handler(post({ make: "VW", model: "Golf" }, { "user-agent": DESKTOP_UAS[0][1] }));
    const j = await r.json();
    expect(j.asset.glbUrl).toBe(DESK);
    expect(j.asset.glbVariant).toBe("desktop");
  });

  it("accepts an explicit device in the body and in the query string", async () => {
    const mod = await loadResolver(ON);
    const byBody = await (await mod.handler(post({ make: "VW", model: "Golf", device: "mobile" }))).json();
    expect(byBody.asset.glbUrl).toBe(MOB);
    expect(byBody.resolution.deviceSource).toBe("explicit");

    const req = new Request("https://edge.example/resolve-vehicle?device=mobile", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ make: "VW", model: "Golf" }),
    });
    const byQuery = await (await mod.handler(req)).json();
    expect(byQuery.asset.glbUrl).toBe(MOB);
  });

  it("keeps the customer's colour and drops the weight", async () => {
    const mod = await loadResolver(ON);
    const j = await (await mod.handler(post({ make: "VW", model: "Golf", colour: "Blue", device: "mobile" }))).json();
    expect(j.asset.glbUrl).toBe("https://cdn.example/car__blue_mobile.glb");
    expect(j.asset.desktopGlbUrl).toBe("https://cdn.example/car__blue.glb");
  });

  it("mobileGlbUrl is never null while glbUrl is a string, so a client that reads it blindly cannot break", async () => {
    const mod = await loadResolver(ON);
    vi.stubGlobal("fetch", async (url: string) =>
      new Response(JSON.stringify(String(url).includes("aliases")
        ? TEST_ALIASES
        : [{ ...TEST_ASSET, mobileGlbUrl: null, mobileColourVariants: undefined }])));
    mod.resetDataCache();
    const j = await (await mod.handler(post({ make: "VW", model: "Golf", device: "mobile" }))).json();
    expect(j.asset.glbUrl).toBe(DESK);
    expect(j.asset.mobileGlbUrl).toBe(DESK);
    expect(j.asset.glbVariant).toBe("desktop");
  });
});

describe("handler — CORS preflight", () => {
  it("the OLD `json({}, 204)` form throws: 204 is a null-body status", () => {
    expect(() => new Response(JSON.stringify({}), { status: 204 })).toThrow(TypeError);
  });
  it("the preflight now returns a bodyless 204 with the CORS headers", async () => {
    const mod = await loadResolver();
    const r = await mod.handler(new Request("https://edge.example/resolve-vehicle", { method: "OPTIONS" }));
    expect(r.status).toBe(204);
    expect(r.body).toBeNull();
    expect(r.headers.get("access-control-allow-origin")).toBe("*");
    expect(r.headers.get("access-control-allow-headers")).toContain("content-type");
  });
});
