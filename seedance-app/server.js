import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getProvider } from "./providers.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(express.json({ limit: "25mb" }));
app.use(express.static(path.join(__dirname, "public")));
app.use("/samples", express.static(path.join(__dirname, "samples")));

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

app.post("/api/generate", async (req, res) => {
  const { prompt, imageDataUrl, model = "seedance-2.0", opts = {} } = req.body || {};
  if (!prompt) return res.status(400).json({ error: "Enter a prompt describing the shot." });
  const { name, fn } = getProvider();
  try {
    const t0 = Date.now();
    const out = await fn({ prompt, imageDataUrl, model, opts });
    res.json({ ...out, provider: name, ms: Date.now() - t0 });
  } catch (e) {
    res.status(500).json({ error: String(e.message || e), provider: name });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Seedance Studio on http://localhost:${PORT}  (provider: ${getProvider().name})`));
