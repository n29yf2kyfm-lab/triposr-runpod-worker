/** Normalised vehicle identity — the single shape every lookup resolves to
 *  before asset matching. Registration is transient: it may appear here in
 *  memory during a lookup but must never be persisted, logged or sent on. */
export type VehicleIdentity = {
  registration?: string;
  make: string;
  model: string;
  modelFamily: string;
  generation?: string;
  manufactureYear?: number;
  registrationYear?: number;
  yearStart?: number;
  yearEnd?: number;
  bodyStyle?: string;
  fuelType?: string;
  transmission?: string;
  derivative?: string;
  trim?: string;
  colourFamily?: ColourFamily;
  sourceConfidence: {
    make: number;
    model: number;
    year: number;
    generation: number;
    bodyStyle: number;
    derivative: number;
    colour: number;
  };
};

export type ColourFamily =
  | "black" | "white" | "grey" | "silver" | "blue" | "red" | "green"
  | "yellow" | "orange" | "brown" | "beige" | "purple" | "gold"
  | "bronze" | "multicolour" | "unknown";

export type ResolutionType =
  | "exact"
  | "generation-correct"
  | "representative"
  | "unavailable";

export type VehicleResolution = {
  asset: import("./vehicle-asset").VehicleAsset | null;
  score: number;
  resolutionType: ResolutionType;
  matchedFields: string[];
  mismatchedFields: string[];
  missingFields: string[];
  disclosure: string;
};
