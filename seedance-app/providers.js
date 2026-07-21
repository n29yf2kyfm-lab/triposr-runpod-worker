// Pluggable video-generation providers.
// Each provider exposes: async generate({prompt, imageDataUrl, model, opts}) -> { videoUrl } | { videoBase64 }
// Selection is by env PROVIDER = demo | fal | replicate | runpod.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- DEMO: no keys, returns a bundled sample so the whole flow is testable ---
async function demo({ model }) {
  await sleep(1200);
  return { videoUrl: "/samples/demo.mp4", note: `demo mode (${model}) — plug an API key or RunPod endpoint for real generation` };
}

// --- Seedance 2.0 via fal.ai ---
// Needs FAL_KEY. Model ids: bytedance/seedance-2.0/image-to-video, .../fast/image-to-video, .../text-to-video
async function fal({ prompt, imageDataUrl, model, opts }) {
  const key = process.env.FAL_KEY;
  if (!key) throw new Error("FAL_KEY not set");
  const isI2V = !!imageDataUrl;
  const modelId = model.includes("fast")
    ? (isI2V ? "bytedance/seedance-2.0/fast/image-to-video" : "bytedance/seedance-2.0/fast/text-to-video")
    : (isI2V ? "bytedance/seedance-2.0/image-to-video" : "bytedance/seedance-2.0/text-to-video");
  const input = {
    prompt,
    resolution: opts.resolution || "720p",
    duration: String(opts.duration || 5),
    aspect_ratio: opts.aspectRatio || "auto",
    generate_audio: opts.audio !== false,
  };
  if (isI2V) input.image_url = imageDataUrl; // fal accepts data URIs
  const res = await fetch(`https://fal.run/${modelId}`, {
    method: "POST",
    headers: { Authorization: `Key ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`fal ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return { videoUrl: data?.video?.url };
}

// --- Seedance 2.0 via Replicate ---
// Needs REPLICATE_API_TOKEN.
async function replicate({ prompt, imageDataUrl, opts }) {
  const key = process.env.REPLICATE_API_TOKEN;
  if (!key) throw new Error("REPLICATE_API_TOKEN not set");
  const input = {
    prompt,
    resolution: opts.resolution || "720p",
    duration: Number(opts.duration || 5),
    aspect_ratio: opts.aspectRatio || "16:9",
    generate_audio: opts.audio !== false,
  };
  if (imageDataUrl) input.image = imageDataUrl;
  let r = await fetch("https://api.replicate.com/v1/models/bytedance/seedance-2.0/predictions", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", Prefer: "wait" },
    body: JSON.stringify({ input }),
  });
  if (!r.ok) throw new Error(`replicate ${r.status}: ${await r.text()}`);
  let pred = await r.json();
  // poll if not finished
  while (pred.status && !["succeeded", "failed", "canceled"].includes(pred.status)) {
    await sleep(2000);
    r = await fetch(pred.urls.get, { headers: { Authorization: `Bearer ${key}` } });
    pred = await r.json();
  }
  if (pred.status !== "succeeded") throw new Error(`replicate: ${pred.error || pred.status}`);
  const out = Array.isArray(pred.output) ? pred.output[0] : pred.output;
  return { videoUrl: out };
}

// --- Self-hosted via RunPod serverless (LTX / Wan worker) ---
// Needs RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID. Worker returns { video_b64 } or { video_url }.
async function runpod({ prompt, imageDataUrl, opts }) {
  const key = process.env.RUNPOD_API_KEY;
  const ep = process.env.RUNPOD_ENDPOINT_ID;
  if (!key || !ep) throw new Error("RUNPOD_API_KEY / RUNPOD_ENDPOINT_ID not set");
  const input = {
    prompt,
    width: opts.width || 768,
    height: opts.height || 448,
    num_frames: opts.numFrames || 121,
    num_inference_steps: opts.steps || 40,
    fps: opts.fps || 24,
  };
  if (imageDataUrl) input.image_b64 = imageDataUrl.split(",").pop();
  let r = await fetch(`https://api.runpod.ai/v2/${ep}/run`, {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
  if (!r.ok) throw new Error(`runpod ${r.status}: ${await r.text()}`);
  const { id } = await r.json();
  for (let i = 0; i < 180; i++) {
    await sleep(3000);
    r = await fetch(`https://api.runpod.ai/v2/${ep}/status/${id}`, { headers: { Authorization: `Bearer ${key}` } });
    const s = await r.json();
    if (s.status === "COMPLETED") {
      const o = s.output || {};
      if (o.video_url) return { videoUrl: o.video_url };
      if (o.video_b64) return { videoBase64: o.video_b64 };
      throw new Error("runpod: no video in output");
    }
    if (s.status === "FAILED") throw new Error(`runpod failed: ${JSON.stringify(s.error || o)}`);
  }
  throw new Error("runpod: timed out");
}

const PROVIDERS = { demo, fal, replicate, runpod };

export function getProvider() {
  const name = (process.env.PROVIDER || "demo").toLowerCase();
  return { name, fn: PROVIDERS[name] || demo };
}
