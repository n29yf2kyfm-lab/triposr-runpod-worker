"""Access, scaffolding and health & safety from measured geometry.

Takes the roof and elevation dimensions the scan already produced and works
out what access the job needs, what the law requires, and where a scaffold
stops being a standard configuration and needs a bespoke design.

Same discipline as regs.py: every finding cites its source, and measurement
uncertainty is carried through so a borderline dimension is reported as
borderline rather than asserted as a breach.

TWO THINGS THIS GETS RIGHT THAT SITE CONVERSATION ROUTINELY GETS WRONG.

The "two metre rule" does not exist in British law. The Work at Height
Regulations 2005 apply at ANY height where a person could fall a distance
liable to cause personal injury — people are killed falling from under two
metres every year. Anything that told a builder work below 2m was exempt
would be worse than useless, so the threshold here is zero and the module
says so.

And a scaffold that is merely "up" is not compliant. TG20 compliance is a
configuration, not a vibe: exceed the height, load class, or sheeting the
eGuide covers, and it needs a bespoke design from a temporary works
engineer. Sheeting in particular is the quiet one — it can double the wind
load on a scaffold that was fine bare.
"""
import math

PASS = "pass"
FAIL = "fail"
BORDERLINE = "borderline"
REQUIRED = "required"      # a duty that applies, not a measurement
UNKNOWN = "insufficient_data"

CRITICAL = "critical"
MAJOR = "major"
ADVISORY = "advisory"

# --- dimensional limits ---------------------------------------------------
# Work at Height Regulations 2005, Schedule 2 — guardrails and toe boards.
MIN_GUARDRAIL_HEIGHT_M = 0.950
MAX_GUARDRAIL_GAP_M = 0.470
MIN_TOEBOARD_HEIGHT_M = 0.150

# Typical tube-and-fitting scaffold geometry, used to size a job.
LIFT_HEIGHT_M = 2.0
BAY_LENGTH_M = 2.4
# Working platform must clear the eaves so a roofer can work off it, and
# guardrails must still stand above that platform.
PLATFORM_BELOW_EAVES_M = 0.15
GUARDRAIL_ABOVE_PLATFORM_M = 0.95

# TG20:21 compliant-scaffold envelope. Beyond any of these the eGuide no
# longer covers the configuration and a bespoke design is required.
TG20_MAX_HEIGHT_M = 26.0
TG20_MAX_BAY_M = 2.7
TG20_SHEETED_MAX_HEIGHT_M = 16.0   # sheeting greatly increases wind load

# Roof pitch above which a roof is "sloping" for access purposes: crawling
# boards or a roof ladder become necessary rather than advisable.
SLOPING_ROOF_DEG = 10.0
STEEP_ROOF_DEG = 30.0

# CDM 2015 notification thresholds (F10 to HSE).
CDM_NOTIFY_DAYS = 30
CDM_NOTIFY_WORKERS = 20
CDM_NOTIFY_PERSON_DAYS = 500

# Scaffold inspection interval, Work at Height Regs reg 12.
INSPECTION_INTERVAL_DAYS = 7


class Finding:
    """One access or safety conclusion, with the duty behind it."""

    def __init__(self, code, title, verdict, severity, message,
                 citation, measured=None, uncertainty=None, unit="m"):
        self.code = code
        self.title = title
        self.verdict = verdict
        self.severity = severity
        self.message = message
        self.citation = citation
        self.measured = measured
        self.uncertainty = uncertainty
        self.unit = unit

    def as_dict(self):
        d = {"code": self.code, "title": self.title, "verdict": self.verdict,
             "severity": self.severity, "message": self.message,
             "citation": self.citation}
        if self.measured is not None:
            d["measured"] = round(self.measured, 3)
            d["unit"] = self.unit
        if self.uncertainty:
            d["uncertainty"] = round(self.uncertainty, 3)
        return d


def _verdict_against(measured, uncertainty, minimum=None, maximum=None):
    """Shared uncertainty-aware comparison — see regs.py for the reasoning."""
    if measured is None:
        return UNKNOWN
    unc = abs(uncertainty or 0.0)
    lo, hi = measured - unc, measured + unc
    if minimum is not None:
        if hi < minimum:
            return FAIL
        if lo < minimum <= hi:
            return BORDERLINE
    if maximum is not None:
        if lo > maximum:
            return FAIL
        if lo <= maximum < hi:
            return BORDERLINE
    return PASS


# ---------------------------------------------------------------------------
# Scaffold sizing
# ---------------------------------------------------------------------------

def scaffold_estimate(eaves_height_m, perimeter_m, sides=None,
                      sheeted=False, uncertainty_m=0.15):
    """Size a perimeter scaffold from measured eaves height and run.

    Returns lifts, bays and area, plus whether the configuration still sits
    inside what TG20 covers. The numbers are for pricing and planning — a
    scaffolder still designs and erects it.
    """
    if not eaves_height_m or not perimeter_m:
        return None

    # The platform must sit just below the eaves, with guardrails above it.
    platform_height = eaves_height_m - PLATFORM_BELOW_EAVES_M
    scaffold_height = platform_height + GUARDRAIL_ABOVE_PLATFORM_M

    lifts = max(1, math.ceil(platform_height / LIFT_HEIGHT_M))
    run = perimeter_m if sides is None else perimeter_m * (sides / 4.0)
    bays = max(1, math.ceil(run / BAY_LENGTH_M))

    max_height = (TG20_SHEETED_MAX_HEIGHT_M if sheeted
                  else TG20_MAX_HEIGHT_M)
    within_tg20 = scaffold_height <= max_height

    return {
        "eaves_height_m": round(eaves_height_m, 2),
        "platform_height_m": round(platform_height, 2),
        "scaffold_height_m": round(scaffold_height, 2),
        "height_uncertainty_m": round(uncertainty_m, 2),
        "lifts": lifts,
        "bays": bays,
        "run_m": round(run, 1),
        "deck_area_m2": round(run * 1.2, 1),   # ~5-board deck
        "sheeted": sheeted,
        "within_tg20": within_tg20,
        "tg20_height_limit_m": max_height,
        "inspection_interval_days": INSPECTION_INTERVAL_DAYS,
    }


def check_scaffold(estimate, guardrail_height_m=None, toeboard_height_m=None,
                   uncertainty_m=0.02):
    """Duties and limits for a scaffold of this size."""
    findings = []
    if not estimate:
        return [Finding(
            "scaffold_unknown", "Scaffold requirement", UNKNOWN, None,
            "Eaves height or perimeter was not measured, so access could not "
            "be sized.", "Work at Height Regulations 2005")]

    height = estimate["scaffold_height_m"]

    # TG20 envelope — the difference between hiring a scaffold and
    # commissioning a design.
    if not estimate["within_tg20"]:
        findings.append(Finding(
            "tg20_scope", "Bespoke scaffold design required", REQUIRED,
            CRITICAL,
            f"At {height:.1f}m{' sheeted' if estimate['sheeted'] else ''} this "
            f"scaffold is outside the {estimate['tg20_height_limit_m']:.0f}m "
            f"TG20 compliant-scaffold envelope, so it needs a bespoke design "
            f"from a temporary works engineer. Price the design in.",
            "NASC TG20:21"))
    else:
        findings.append(Finding(
            "tg20_scope", "Scaffold configuration", PASS, None,
            f"At {height:.1f}m this sits inside the TG20 compliant-scaffold "
            f"envelope, so a TG20 compliance sheet should be obtainable "
            f"without a bespoke design.", "NASC TG20:21"))

    if estimate["sheeted"]:
        findings.append(Finding(
            "sheeting_wind_load", "Sheeting increases wind load", REQUIRED,
            MAJOR,
            "Sheeting or debris netting can more than double the wind load on "
            "a scaffold that was adequate bare. Tie pattern and design must "
            "account for it — never sheet an existing scaffold without "
            "checking.", "NASC TG20:21"))

    # Guardrails and toe boards, where measured.
    v = _verdict_against(guardrail_height_m, uncertainty_m,
                         minimum=MIN_GUARDRAIL_HEIGHT_M)
    findings.append(Finding(
        "guardrail_height", "Main guardrail height", v,
        _severity_for(v, CRITICAL),
        _dim_message("Main guardrail", guardrail_height_m, uncertainty_m, v,
                     minimum=MIN_GUARDRAIL_HEIGHT_M),
        "Work at Height Regulations 2005, Schedule 2",
        guardrail_height_m, uncertainty_m))

    v = _verdict_against(toeboard_height_m, uncertainty_m,
                         minimum=MIN_TOEBOARD_HEIGHT_M)
    findings.append(Finding(
        "toeboard_height", "Toe board height", v, _severity_for(v, MAJOR),
        _dim_message("Toe board", toeboard_height_m, uncertainty_m, v,
                     minimum=MIN_TOEBOARD_HEIGHT_M),
        "Work at Height Regulations 2005, Schedule 2",
        toeboard_height_m, uncertainty_m))

    findings.append(Finding(
        "inspection", "Scaffold inspection regime", REQUIRED, MAJOR,
        f"A scaffold from which a person could fall more than 2m must be "
        f"inspected before first use, every {INSPECTION_INTERVAL_DAYS} days "
        f"thereafter, and again after any alteration or adverse weather. "
        f"Records must be kept.",
        "Work at Height Regulations 2005, regulation 12"))
    return findings


def _severity_for(verdict, on_fail):
    """Severity for a dimensional check.

    An UNMEASURED item carries no severity. Live-confirmed on a real
    assessment: an unbuilt scaffold's guardrail height is obviously not
    measured, and reporting that as a CRITICAL failure put "not measured"
    at the top of the critical list alongside a genuine steep-roof hazard.
    Do that on every job and a builder learns to skim the critical list,
    which is the opposite of what it is for. Unchecked items surface
    separately as things still to verify.
    """
    if verdict == PASS:
        return None
    if verdict == UNKNOWN:
        return None
    if verdict == BORDERLINE:
        return MAJOR
    return on_fail


def _dim_message(what, measured, unc, verdict, minimum=None, maximum=None):
    if measured is None:
        return (f"{what} was not measured, so it could not be checked. It "
                f"still needs verifying on site.")
    band = f" (±{unc * 1000:.0f}mm)" if unc else ""
    if verdict == PASS:
        return f"{what} {measured * 1000:.0f}mm{band} — within requirement."
    if verdict == BORDERLINE:
        limit = minimum if minimum is not None else maximum
        return (f"{what} measures {measured * 1000:.0f}mm{band} against a "
                f"{limit * 1000:.0f}mm requirement — within measurement error "
                f"of the limit. Check with a tape before signing it off.")
    limit = minimum if minimum is not None else maximum
    return (f"{what} measures {measured * 1000:.0f}mm{band} against a "
            f"{limit * 1000:.0f}mm requirement. This does not comply.")


# ---------------------------------------------------------------------------
# Working at height, roof access, CDM
# ---------------------------------------------------------------------------

def check_work_at_height(eaves_height_m, roof_pitch_deg=None,
                         fragile_surfaces=False):
    """Duties triggered by the work itself, regardless of dimensions."""
    findings = []

    # The most common and most dangerous misconception on site.
    findings.append(Finding(
        "wah_threshold", "Work at height duties apply", REQUIRED, CRITICAL,
        "There is no 'two metre rule' in British law. The Work at Height "
        "Regulations apply at ANY height where a fall could cause injury, "
        "and people are killed every year falling from under two metres. "
        "Avoid working at height where the job allows it; where it does not, "
        "prevent falls with a scaffold or tower before relying on anything "
        "that merely limits the consequences.",
        "Work at Height Regulations 2005, regulation 6",
        eaves_height_m))

    if roof_pitch_deg is not None:
        if roof_pitch_deg >= STEEP_ROOF_DEG:
            findings.append(Finding(
                "roof_access", "Steep roof access", REQUIRED, CRITICAL,
                f"At {roof_pitch_deg:.0f}° this roof is steep. Roof ladders "
                f"or crawling boards are required, along with edge protection "
                f"at the eaves, and the work should be planned so nobody "
                f"needs to move across the slope unsecured.",
                "HSE HSG33, Health and safety in roof work",
                roof_pitch_deg, unit="deg"))
        elif roof_pitch_deg >= SLOPING_ROOF_DEG:
            findings.append(Finding(
                "roof_access", "Sloping roof access", REQUIRED, MAJOR,
                f"At {roof_pitch_deg:.0f}° this counts as a sloping roof. "
                f"Crawling boards and eaves edge protection are needed.",
                "HSE HSG33", roof_pitch_deg, unit="deg"))
        else:
            findings.append(Finding(
                "roof_access", "Flat roof access", REQUIRED, MAJOR,
                f"At {roof_pitch_deg:.0f}° this is effectively a flat roof. "
                f"Edge protection is required to every open edge, and any "
                f"rooflight must be treated as a fragile surface.",
                "HSE HSG33", roof_pitch_deg, unit="deg"))

    if fragile_surfaces:
        findings.append(Finding(
            "fragile_surface", "Fragile surfaces present", REQUIRED, CRITICAL,
            "Fragile surfaces — asbestos cement sheet, rooflights, corroded "
            "metal, liner panels — cause a large share of fatal roof falls. "
            "They must be guarded, covered or the area kept clear, and "
            "signed. Assume a roof is fragile until proven otherwise.",
            "HSE HSG33; Work at Height Regulations 2005, regulation 9"))
    return findings


def check_cdm(duration_days=None, max_workers=None, person_days=None,
              contractor_count=1, domestic_client=False):
    """CDM 2015 duties and whether the job is notifiable to HSE."""
    findings = []

    notifiable = None
    if duration_days is not None and max_workers is not None:
        notifiable = (duration_days > CDM_NOTIFY_DAYS
                      and max_workers > CDM_NOTIFY_WORKERS)
    if person_days is not None and person_days > CDM_NOTIFY_PERSON_DAYS:
        notifiable = True

    if notifiable is None:
        findings.append(Finding(
            "cdm_notify", "CDM notification", UNKNOWN, None,
            f"Programme not supplied, so notification could not be assessed. "
            f"A project is notifiable when it runs over {CDM_NOTIFY_DAYS} "
            f"working days with more than {CDM_NOTIFY_WORKERS} workers at any "
            f"one time, or exceeds {CDM_NOTIFY_PERSON_DAYS} person-days.",
            "CDM 2015, regulation 6"))
    elif notifiable:
        findings.append(Finding(
            "cdm_notify", "Project is notifiable to HSE", REQUIRED, MAJOR,
            f"This project exceeds the CDM thresholds, so form F10 must be "
            f"sent to HSE before construction begins.",
            "CDM 2015, regulation 6"))
    else:
        findings.append(Finding(
            "cdm_notify", "Project is not notifiable", PASS, None,
            "Below the CDM notification thresholds. Every other CDM duty "
            "still applies — notification is not what triggers them.",
            "CDM 2015, regulation 6"))

    if contractor_count > 1:
        findings.append(Finding(
            "cdm_roles", "Principal Designer and Principal Contractor",
            REQUIRED, MAJOR,
            "More than one contractor means the client must appoint a "
            "Principal Designer and a Principal Contractor in writing, and a "
            "construction phase plan is required.",
            "CDM 2015, regulations 5 and 12"))
    else:
        findings.append(Finding(
            "cdm_roles", "Single contractor", REQUIRED, ADVISORY,
            "With one contractor, that contractor prepares the construction "
            "phase plan. A plan is required on every construction project, "
            "however small.",
            "CDM 2015, regulation 15"))

    if domestic_client:
        findings.append(Finding(
            "cdm_domestic", "Domestic client duties transfer", REQUIRED,
            MAJOR,
            "For a domestic client the client duties normally pass to the "
            "contractor, or to the Principal Contractor where there is more "
            "than one. A householder does not carry them — you do.",
            "CDM 2015, regulation 7"))
    return findings


def assess(roof=None, eaves_height_m=None, perimeter_m=None, sheeted=False,
           guardrail_height_m=None, toeboard_height_m=None,
           fragile_surfaces=False, duration_days=None, max_workers=None,
           person_days=None, contractor_count=1, domestic_client=True,
           uncertainty_m=0.15):
    """Full access and safety assessment from a measured roof."""
    pitch = None
    if roof:
        q = roof.get("quantities") or roof
        pitch = q.get("predominant_pitch_deg")
        perimeter_m = perimeter_m or q.get("eaves_m")

    estimate = scaffold_estimate(eaves_height_m, perimeter_m,
                                 sheeted=sheeted, uncertainty_m=uncertainty_m)
    findings = []
    findings += check_work_at_height(eaves_height_m, pitch, fragile_surfaces)
    findings += check_scaffold(estimate, guardrail_height_m,
                               toeboard_height_m)
    findings += check_cdm(duration_days, max_workers, person_days,
                          contractor_count, domestic_client)

    by_sev = {CRITICAL: [], MAJOR: [], ADVISORY: []}
    for f in findings:
        if f.severity in by_sev:
            by_sev[f.severity].append(f.as_dict())
    # Things that could not be checked are a to-do list for site, not
    # failures — kept visible, kept out of the severity buckets.
    to_verify = [f.as_dict() for f in findings if f.verdict == UNKNOWN]

    return {
        "scaffold": estimate,
        "findings": [f.as_dict() for f in findings],
        "to_verify_on_site": to_verify,
        "critical": by_sev[CRITICAL],
        "major": by_sev[MAJOR],
        "advisory": by_sev[ADVISORY],
        "disclaimer":
            "An access and safety first pass from measured geometry. It does "
            "not replace a scaffold design, a risk assessment or a method "
            "statement, and it cannot see site conditions — overhead lines, "
            "ground bearing, excavations, public access, asbestos. A "
            "competent person still plans the work.",
    }
