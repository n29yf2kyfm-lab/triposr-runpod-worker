import type {
  Health,
  Identification,
  Listing,
  Pricing,
  PromoVideo,
  PublishResult,
} from "./types";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  async health(): Promise<Health> {
    const res = await fetch("/api/health");
    return res.json();
  },

  async identify(file: File): Promise<Identification> {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/identify", { method: "POST", body: form });
    if (!res.ok) throw new Error(`identify failed: ${res.status}`);
    return res.json();
  },

  price(identification: Identification): Promise<Pricing> {
    return post("/api/price", { identification });
  },

  listing(identification: Identification, pricing: Pricing): Promise<Listing> {
    return post("/api/listing", { identification, pricing });
  },

  video(identification: Identification, listing: Listing, image_id: string): Promise<PromoVideo> {
    return post("/api/video", { identification, listing, image_id });
  },

  publish(listing: Listing, pricing: Pricing, image_id: string): Promise<PublishResult> {
    return post("/api/publish", { listing, pricing, image_id });
  },
};
