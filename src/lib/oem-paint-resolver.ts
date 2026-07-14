/**
 * OEM paint colour resolution — implements steps 4–8 of the owner-specified
 * workflow (see CLAUDE.md "OEM paint colour resolution"):
 *
 *   4. filter the OEM paint database by MANUFACTURER
 *   5. filter those candidates by the DVLA broad colour
 *   6. image analysis may only RANK the remaining candidates — never decide
 *   7. never claim an exact OEM paint from an image alone
 *   8. display as "Possible OEM colour: <name>" (unconfirmed) until confirmed
 *      by VIN, paint label, or manufacturer record
 *
 * Steps 1–3 (DVLA decode) happen upstream in the app; the registration is
 * never passed into, stored by, or logged from this module.
 */
import { clean, normaliseMake } from "./vehicle-normalisation";

export interface OemPaint {
  manufacturer: string;
  name: string;
  /** DVLA broad colour, upper case (GREY, BLACK, …) */
  dvlaColour: string;
  /** render-palette family (must exist in the render worker's _RGB palette) */
  colourFamily: string;
  finish: string;
}

export interface OemPaintResolution {
  status: "candidates" | "no-match" | "unknown-make";
  /** steps 4–5 result, possibly reordered by step 6 — never added to */
  candidates: OemPaint[];
  /** rule-8 caption for the top candidate, or null when there are none */
  displayLine: string | null;
  /** top candidate's colour family for the render palette, or null */
  renderFamily: string | null;
  /**
   * Always false here: confirmation requires VIN, paint label, or a
   * manufacturer record (rule 7) — that evidence never comes from this
   * resolver, so callers must treat every result as unconfirmed.
   */
  confirmed: false;
}

/**
 * Resolve possible OEM paints for a decoded vehicle.
 *
 * @param make        manufacturer from the DVLA/DVSA decode
 * @param dvlaColour  broad colour string from the DVLA decode
 * @param paints      the OEM paint database (data/oem-paints.json `paints`)
 * @param imageRanking optional ordered paint names from image analysis.
 *   Step 6: it may only reorder the candidate list; names outside the
 *   candidate set are ignored, and it can never make a result "confirmed".
 */
export function resolveOemPaint(
  make: string,
  dvlaColour: string,
  paints: OemPaint[],
  imageRanking?: string[],
): OemPaintResolution {
  const wantMake = normaliseMake(make ?? "");
  const wantColour = clean(dvlaColour ?? "").toUpperCase();

  const forMake = paints.filter((p) => normaliseMake(p.manufacturer) === wantMake);
  if (forMake.length === 0) {
    return { status: "unknown-make", candidates: [], displayLine: null, renderFamily: null, confirmed: false };
  }

  let candidates = forMake.filter((p) => p.dvlaColour === wantColour);
  if (candidates.length === 0) {
    return { status: "no-match", candidates: [], displayLine: null, renderFamily: null, confirmed: false };
  }

  if (imageRanking && imageRanking.length > 0) {
    const rank = new Map(imageRanking.map((n, i) => [clean(n).toLowerCase(), i]));
    const pos = (p: OemPaint) => rank.get(clean(p.name).toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
    candidates = [...candidates].sort((a, b) => pos(a) - pos(b));
  }

  const top = candidates[0];
  return {
    status: "candidates",
    candidates,
    displayLine: `Possible OEM colour: ${top.name}`,
    renderFamily: top.colourFamily,
    confirmed: false,
  };
}
