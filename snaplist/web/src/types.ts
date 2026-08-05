export interface ItemSpecific {
  name: string;
  value: string;
}

export interface Identification {
  title_guess: string;
  brand: string;
  model: string;
  category: string;
  condition: string;
  color: string;
  material: string;
  attributes: ItemSpecific[];
  confidence: number;
  notes: string;
  image_id: string;
  source: string;
}

export interface PriceComp {
  title: string;
  price: number;
  currency: string;
  source: string;
  url: string;
}

export interface Pricing {
  suggested_price: number;
  currency: string;
  low: number;
  high: number;
  comps: PriceComp[];
  rationale: string;
  source: string;
}

export interface Listing {
  title: string;
  subtitle: string;
  description_html: string;
  bullet_points: string[];
  item_specifics: ItemSpecific[];
  keywords: string[];
  category_id: string;
  source: string;
}

export interface StoryboardShot {
  seconds: number;
  visual: string;
  caption: string;
}

export interface PromoVideo {
  status: string;
  video_url: string;
  thumbnail_url: string;
  duration_s: number;
  hook: string;
  caption: string;
  hashtags: string[];
  storyboard: StoryboardShot[];
  source: string;
}

export interface PublishResult {
  status: string;
  listing_id: string;
  view_url: string;
  environment: string;
  message: string;
  live: boolean;
}

export interface Health {
  ok: boolean;
  integrations: {
    ai_vision_and_copy: boolean;
    pricing: boolean;
    video: boolean;
    ebay: boolean;
    ebay_env: string;
  };
}
