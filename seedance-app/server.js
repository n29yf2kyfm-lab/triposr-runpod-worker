import express from "express";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getProvider } from "./providers.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(express.json({ limit: "25mb" }));
app.use(express.static(path.join(__dirname, "public")));
app.use("/samples", express.static(path.join(__dirname, "samples")));

// --- access control ---------------------------------------------------------
// /api/generate spends real money on FAL_KEY / REPLICATE_API_TOKEN /
// RUNPOD_API_KEY. Without a gate, anyone who can reach this port can bill the
// owner's accounts, so a shared secret is REQUIRED for any provider other than
// the local demo. Set APP_TOKEN and send it as `Authorization: Bearer <token>`
// or `X-App-Token`. Demo mode returns a bundled mp4 and costs nothing, so it
// stays open to keep the getting-started path frictionless.
const APP_TOKEN = process.env.APP_TOKEN || "";

function tokenOk(req) {
  const sent = (req.get("authorization") || "").replace(/^Bearer\s+/i, "")
    || req.get("x-app-token") || "";
  if (!sent || !APP_TOKEN) return false;
  const a = Buffer.from(sent), b = Buffer.from(APP_TOKEN);
  // constant-time: timingSafeEqual throws on length mismatch, so length-check first
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function requireAuth(req, res, next) {
  if (getProvider().name === "demo") return next();
  if (!APP_TOKEN) {
    return res.status(503).json({
      error: "APP_TOKEN is not set. Refusing to expose a paid provider without a token.",
    });
  }
  if (!tokenOk(req)) return res.status(401).json({ error: "Unauthorized" });
  next();
}

// --- rate limit -------------------------------------------------------------
// Coarse per-IP fixed window. Not a substitute for a real limiter behind a proxy,
// but it stops a single client from looping the paid endpoint.
const WINDOW_MS = Number(process.env.RATE_WINDOW_MS || 60_000);
const MAX_REQ = Number(process.env.RATE_MAX || 10);
const hits = new Map();

function rateLimit(req, res, next) {
  const now = Date.now();
  const ip = req.ip || req.socket.remoteAddress || "unknown";
  const e = hits.get(ip);
  if (!e || now > e.reset) {
    hits.set(ip, { n: 1, reset: now + WINDOW_MS });
  } else if (++e.n > MAX_REQ) {
    return res.status(429).json({ error: "Too many requests", retryAfterMs: e.reset - now });
  }
  if (hits.size > 10_000) {
    for (const [k, v] of hits) if (now > v.reset) hits.delete(k);
  }
  next();
}

// Which providers have credentials configured — drives the UI toggle.
app.get("/api/config", (_req, res) => {
  const { name } = getProvider();
  res.json({
    provider: name,
    ready: {
      fal: !!process.env.FAL_KEY,
      replicate: !!process.env.REPLICATE_API_TOKEN,
      runpod: !!(process.env.RUNPOD_API_KEY && process.env.RUNPOD_ENDPOINT_ID),
    },
  });
});

app.post("/api/generate", rateLimit, requireAuth, async (req, res) => {
  const { prompt, imageDataUrl, model = "seedance-2.0", opts = {} } = req.body || {};
  if (!prompt) return res.status(400).json({ error: "Enter a prompt describing the shot." });
  if (typeof prompt !== "string" || prompt.length > 2000) {
    return res.status(400).json({ error: "prompt must be a string under 2000 characters." });
  }
  const { name, fn } = getProvider();
  try {
    const t0 = Date.now();
    const out = await fn({ prompt, imageDataUrl, model, opts });
    res.json({ ...out, provider: name, ms: Date.now() - t0 });
  } catch (e) {
    // Provider errors carry upstream request/response text; log it server-side
    // and hand the client a generic message rather than leaking internals.
    console.error(`[generate] provider=${name}`, e);
    res.status(500).json({ error: "Generation failed. See server logs.", provider: name });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Seedance Studio on http://localhost:${PORT}  (provider: ${getProvider().name})`));
