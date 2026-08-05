import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  Health,
  Identification,
  Listing,
  Pricing,
  PromoVideo,
  PublishResult,
} from "./types";

type Busy = null | "identify" | "price" | "listing" | "video" | "publish";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [ident, setIdent] = useState<Identification | null>(null);
  const [imageId, setImageId] = useState("");
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const [listing, setListing] = useState<Listing | null>(null);
  const [video, setVideo] = useState<PromoVideo | null>(null);
  const [publishResult, setPublish] = useState<PublishResult | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  function reset() {
    setFile(null);
    setPreview("");
    setIdent(null);
    setImageId("");
    setPricing(null);
    setListing(null);
    setVideo(null);
    setPublish(null);
    setError("");
  }

  async function run<T>(stage: Busy, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(stage);
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  function onPick(f: File | null) {
    if (!f) return;
    reset();
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }

  async function doIdentify() {
    if (!file) return;
    const res = await run("identify", () => api.identify(file));
    if (res) {
      setImageId(res.image_id);
      setIdent(res);
    }
  }
  async function doPrice() {
    if (!ident) return;
    const res = await run("price", () => api.price(ident));
    if (res) setPricing(res);
  }
  async function doListing() {
    if (!ident || !pricing) return;
    const res = await run("listing", () => api.listing(ident, pricing));
    if (res) setListing(res);
  }
  async function doVideo() {
    if (!ident || !listing) return;
    const res = await run("video", () => api.video(ident, listing, imageId));
    if (res) setVideo(res);
  }
  async function doPublish() {
    if (!listing || !pricing) return;
    const res = await run("publish", () => api.publish(listing, pricing, imageId));
    if (res) setPublish(res);
  }

  const demoMode = health && !health.integrations.ai_vision_and_copy;

  return (
    <div className="app">
      <Header health={health} />

      {demoMode && (
        <div className="banner">
          <strong>Demo mode.</strong> Running on realistic sample data — no API keys set.
          Add keys in <code>api/.env</code> to identify your real photos, pull live prices,
          render real video, and publish to the eBay Sandbox.
        </div>
      )}

      {error && <div className="banner err">⚠ {error}</div>}

      {/* STEP 1 — PHOTO */}
      <Step n={1} title="Snap or upload a photo" done={!!ident}>
        <Dropzone preview={preview} onPick={onPick} />
        {file && (
          <button className="btn primary" disabled={busy !== null} onClick={doIdentify}>
            {busy === "identify" ? "Identifying…" : "Identify item →"}
          </button>
        )}
      </Step>

      {/* STEP 2 — IDENTIFY */}
      {ident && (
        <Step n={2} title="Confirm what it is" done={!!pricing}>
          <IdentCard ident={ident} onChange={setIdent} />
          <button className="btn primary" disabled={busy !== null} onClick={doPrice}>
            {busy === "price" ? "Checking prices…" : "Check market price →"}
          </button>
        </Step>
      )}

      {/* STEP 3 — PRICE */}
      {pricing && (
        <Step n={3} title="Market price" done={!!listing}>
          <PriceCard pricing={pricing} onChange={setPricing} />
          <button className="btn primary" disabled={busy !== null} onClick={doListing}>
            {busy === "listing" ? "Writing listing…" : "Write the listing →"}
          </button>
        </Step>
      )}

      {/* STEP 4 — LISTING */}
      {listing && (
        <Step n={4} title="Your eBay listing" done={!!video}>
          <ListingCard listing={listing} onChange={setListing} />
          <button className="btn primary" disabled={busy !== null} onClick={doVideo}>
            {busy === "video" ? "Building promo…" : "Make the promo video →"}
          </button>
        </Step>
      )}

      {/* STEP 5 — VIDEO */}
      {video && (
        <Step n={5} title="Promo video" done={!!publishResult}>
          <VideoCard video={video} />
          <button className="btn primary" disabled={busy !== null} onClick={doPublish}>
            {busy === "publish" ? "Publishing…" : "Publish to eBay →"}
          </button>
        </Step>
      )}

      {/* STEP 6 — PUBLISH */}
      {publishResult && (
        <Step n={6} title="Published" done={publishResult.status === "published"}>
          <PublishCard result={publishResult} />
          <button className="btn ghost" onClick={reset}>
            List another item
          </button>
        </Step>
      )}

      <footer className="foot">
        SnapList · working prototype · photo → eBay listing → promo video
      </footer>
    </div>
  );
}

/* ---------------- components ---------------- */

function Header({ health }: { health: Health | null }) {
  const dot = (on: boolean) => (
    <span className={`dot ${on ? "on" : "off"}`} />
  );
  return (
    <header className="head">
      <div>
        <div className="logo">Snap<span>List</span></div>
        <div className="tag">One photo. Listed and marketed.</div>
      </div>
      {health && (
        <div className="status">
          <span>{dot(health.integrations.ai_vision_and_copy)} AI</span>
          <span>{dot(health.integrations.pricing)} Pricing</span>
          <span>{dot(health.integrations.video)} Video</span>
          <span>{dot(health.integrations.ebay)} eBay ({health.integrations.ebay_env})</span>
        </div>
      )}
    </header>
  );
}

function Step(props: { n: number; title: string; done: boolean; children: React.ReactNode }) {
  return (
    <section className="step">
      <div className="step-head">
        <span className={`step-n ${props.done ? "done" : ""}`}>
          {props.done ? "✓" : props.n}
        </span>
        <h2>{props.title}</h2>
      </div>
      <div className="step-body">{props.children}</div>
    </section>
  );
}

function Dropzone({ preview, onPick }: { preview: string; onPick: (f: File | null) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={`drop ${over ? "over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        onPick(e.dataTransfer.files?.[0] ?? null);
      }}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
    >
      {preview ? (
        <img src={preview} alt="item preview" />
      ) : (
        <div className="drop-empty">
          <div className="drop-icon">📷</div>
          <p>Drop a product photo, or click to choose</p>
          <span>JPG or PNG · one item per photo</span>
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function IdentCard({
  ident,
  onChange,
}: {
  ident: Identification;
  onChange: (i: Identification) => void;
}) {
  const set = (k: keyof Identification, v: string) => onChange({ ...ident, [k]: v });
  const conf = Math.round(ident.confidence * 100);
  const low = conf < 60;
  return (
    <div className="card">
      <div className={`conf ${low ? "low" : ""}`}>
        Confidence {conf}%
        {low && " — low, double-check the brand/model before listing"}
      </div>
      <div className="grid2">
        <Field label="Item" value={ident.title_guess} onChange={(v) => set("title_guess", v)} />
        <Field label="Brand" value={ident.brand} onChange={(v) => set("brand", v)} />
        <Field label="Model" value={ident.model} onChange={(v) => set("model", v)} />
        <Field label="Condition" value={ident.condition} onChange={(v) => set("condition", v)} />
        <Field label="Color" value={ident.color} onChange={(v) => set("color", v)} />
        <Field label="Category" value={ident.category} onChange={(v) => set("category", v)} />
      </div>
      {ident.attributes.length > 0 && (
        <div className="chips">
          {ident.attributes.map((a, i) => (
            <span key={i} className="chip">
              {a.name}: {a.value}
            </span>
          ))}
        </div>
      )}
      {ident.notes && <p className="note">{ident.notes}</p>}
    </div>
  );
}

function PriceCard({
  pricing,
  onChange,
}: {
  pricing: Pricing;
  onChange: (p: Pricing) => void;
}) {
  return (
    <div className="card">
      <div className="price-row">
        <div className="price-big">
          <label>
            <span>Your price</span>
            <div className="money">
              ${" "}
              <input
                type="number"
                value={pricing.suggested_price}
                onChange={(e) =>
                  onChange({ ...pricing, suggested_price: Number(e.target.value) })
                }
              />
            </div>
          </label>
        </div>
        <div className="price-range">
          <span>Market range</span>
          <strong>
            ${pricing.low.toFixed(0)} – ${pricing.high.toFixed(0)}
          </strong>
        </div>
      </div>
      <p className="note">{pricing.rationale}</p>
      <div className="comps">
        {pricing.comps.map((c, i) => (
          <div key={i} className="comp">
            <span className="comp-src">{c.source || "listing"}</span>
            <span className="comp-title">{c.title}</span>
            <span className="comp-price">${c.price.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ListingCard({
  listing,
  onChange,
}: {
  listing: Listing;
  onChange: (l: Listing) => void;
}) {
  return (
    <div className="card">
      <label className="field">
        <span>
          Title <em>({listing.title.length}/80)</em>
        </span>
        <input
          value={listing.title}
          maxLength={80}
          onChange={(e) => onChange({ ...listing, title: e.target.value })}
        />
      </label>
      <div className="subhead">Description</div>
      <div
        className="desc"
        dangerouslySetInnerHTML={{ __html: listing.description_html }}
      />
      {listing.item_specifics.length > 0 && (
        <>
          <div className="subhead">Item specifics</div>
          <div className="chips">
            {listing.item_specifics.map((s, i) => (
              <span key={i} className="chip">
                {s.name}: {s.value}
              </span>
            ))}
          </div>
        </>
      )}
      {listing.keywords.length > 0 && (
        <>
          <div className="subhead">SEO keywords</div>
          <div className="chips">
            {listing.keywords.map((k, i) => (
              <span key={i} className="chip kw">
                {k}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function VideoCard({ video }: { video: PromoVideo }) {
  return (
    <div className="card">
      <div className="video-top">
        <div className="phone">
          {video.video_url ? (
            <video src={video.video_url} controls poster={video.thumbnail_url} />
          ) : (
            <div className="phone-mock">
              <div className="hook">{video.hook}</div>
              <div className="phone-tag">
                {video.status === "processing"
                  ? "rendering…"
                  : "storyboard preview"}
              </div>
            </div>
          )}
        </div>
        <div className="video-meta">
          <div className="subhead">Caption</div>
          <p>{video.caption}</p>
          <div className="chips">
            {video.hashtags.map((h, i) => (
              <span key={i} className="chip kw">
                {h}
              </span>
            ))}
          </div>
          <p className="note">
            {video.source === "mock"
              ? "Storyboard + caption generated. Add a VIDEO_API_KEY to render the actual clip."
              : "Video render queued with your provider."}
          </p>
        </div>
      </div>
      <div className="subhead">Storyboard</div>
      <div className="board">
        {video.storyboard.map((s, i) => (
          <div key={i} className="shot">
            <span className="shot-t">{s.seconds.toFixed(1)}s</span>
            <div>
              <div className="shot-v">{s.visual}</div>
              <div className="shot-c">{s.caption}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PublishCard({ result }: { result: PublishResult }) {
  const ok = result.status === "published";
  const err = result.status === "error";
  return (
    <div className={`card publish ${ok ? "ok" : err ? "err" : "draft"}`}>
      <div className="publish-status">
        {ok ? "✓ Live on eBay" : err ? "Publish error" : "Draft ready"}
        <span className="env">{result.environment}</span>
      </div>
      {result.listing_id && (
        <div className="publish-id">Listing ID: {result.listing_id}</div>
      )}
      {result.view_url && (
        <a className="btn primary" href={result.view_url} target="_blank" rel="noreferrer">
          View on eBay →
        </a>
      )}
      <p className="note">{result.message}</p>
    </div>
  );
}
