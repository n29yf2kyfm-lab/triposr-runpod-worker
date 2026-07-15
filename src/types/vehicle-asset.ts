import type { ColourFamily } from "./vehicle";

export type AccuracyGrade =
  | "exact" | "generation-correct" | "representative" | "approximate" | "unavailable";
export type QualityGrade = "A" | "B" | "C" | "rejected";
export type QcStatus = "passed" | "warning" | "failed" | "pending";
export type PublicationStatus = "approved" | "quarantined" | "needs-review" | "retired";
export type InteriorMode = "none" | "panorama" | "gaussian-splat" | "mesh";
export type Provenance = "sourced" | "generated-from-reference" | "licensed" | "hand-built";
export type BodyStyle =
  | "hatchback" | "saloon" | "estate" | "suv" | "coupe" | "convertible"
  | "mpv" | "pickup" | "van" | "roadster";
export type PaintFinish =
  | "solid" | "metallic" | "pearl" | "mica" | "multi-coat" | "tri-coat" | "matte" | "crystal";
export type WrapFinish = "gloss" | "matte" | "satin" | "metallic" | "pearl" | "chrome";

/** Swappable-component sets for an interactive configurator (Tier A).
 *  Every component is a GLB/texture our own pipeline generates and we own —
 *  wheel_replace.py (wheels), clear_glass/recolour (colour), wrap textures.
 *  configuratorReady gates whether the app offers live customization. */
export type Customization = {
  configuratorReady?: boolean;
  componentPipelineVersion?: string | null;
  wheelSets?: Array<{
    id: string; label: string; glbUrl: string;
    thumbnailUrl?: string | null; isDefault?: boolean;
  }>;
  wraps?: Array<{
    id: string; label: string; family: ColourFamily;
    finish?: WrapFinish; glbUrl?: string | null;
    textureUrl?: string | null; thumbnailUrl?: string | null;
  }>;
  colourOptions?: Array<{
    family: string; label: string; hex?: string | null;
    finish?: PaintFinish; oemPaintName?: string | null; glbUrl?: string | null;
  }>;
};

/** Schema v2 catalogue entry. Mirrors schemas/vehicle-asset.schema.json. */
export type VehicleAsset = {
  schemaVersion: 2;
  assetId: string;
  make: string;
  model: string;
  modelFamily: string;
  modelAliases?: string[];
  generation?: string | null;
  generationAliases?: string[];
  generationConfirmed?: boolean;
  yearStart?: number | null;
  yearEnd?: number | null;
  bodyStyle?: BodyStyle | null;
  compatibleFuelTypes?: string[];
  compatibleTrimFamilies?: string[];
  exactDerivative?: string | null;
  exactTrim?: boolean;
  provenance: Provenance;
  sourceTitle: string;
  sourceUrl?: string | null;
  sourceCreator?: string | null;
  sourceReferenceId?: string | null;
  sourceRetrievedAt?: string | null;
  sourceEvidenceUrl?: string | null;
  licence?: string | null;
  generatedFromReference?: boolean;
  referenceImageCount?: number;
  accuracyGrade: AccuracyGrade;
  qualityGrade: QualityGrade;
  technicalStatus: QcStatus;
  visualStatus: QcStatus;
  publicationStatus: PublicationStatus;
  quarantineReason?: string | null;
  hasInterior: boolean;
  interiorMode: InteriorMode;
  hasSeparateDoors?: boolean;
  hasSeparateBonnet?: boolean;
  hasSeparateBoot?: boolean;
  supportsOpenableParts: boolean;
  paintMaterialNames?: string[];
  glassMaterialNames?: string[];
  defaultColourFamily: ColourFamily;
  renderColourLabel?: string | null;
  oemPaintVerified?: boolean;
  oemPaintCode?: string | null;
  oemPaintName?: string | null;
  colourVariants?: Record<string, string>;
  customization?: Customization | null;
  desktopGlbUrl: string;
  mobileGlbUrl?: string | null;
  fallbackGlbUrl?: string | null;
  posterUrl?: string | null;
  turntableUrl?: string | null;
  interiorUrl?: string | null;
  fileSizeBytes?: number | null;
  mobileFileSizeBytes?: number | null;
  triangleCount?: number | null;
  vertexCount?: number | null;
  textureMemoryBytes?: number | null;
  maxTextureResolution?: number | null;
  contentHash?: string | null;
  pipelineVersion?: string | null;
  publishedAt?: string | null;
  replacedAssetId?: string | null;
  needsHumanReview?: string[];
  notes?: string[];
};
