"""UK Building Regulations checked against a measured model — pure stdlib.

Encodes the Approved Document limits that can be tested from geometry, and
returns a verdict against each one with the clause cited, so a finding can
be looked up and argued rather than taken on trust.

THE THING THAT MAKES THIS HONEST — and that a rules engine written against
drawings never has to face — is measurement uncertainty. A drawing states
a stair rise is 220mm. A scan MEASURES it as 221mm, plus or minus five.
Reporting that as a failure is irresponsible: it is a borderline case that
needs a tape on site, and calling it a breach could send someone ripping out
a compliant staircase. Every check therefore carries the tolerance of the
measurement that fed it, and a result within that band of a limit comes back
BORDERLINE rather than PASS or FAIL.

Approved Documents are also not the only word. They are guidance, not the
regulation itself; compliance can be demonstrated another way, older work is
judged against the rules of its day, and listed or historic buildings carry
exemptions. Nothing here is a determination — it is a competent first pass
that tells a builder what to look at.
"""

PASS = "pass"
FAIL = "fail"
BORDERLINE = "borderline"
UNKNOWN = "insufficient_data"

# Severity, so a report can be triaged rather than read end to end.
CRITICAL = "critical"    # life safety — escape, falls, structure
MAJOR = "major"          # would fail building control
ADVISORY = "advisory"    # good practice, or a limit that is guidance only


class Rule:
    """One checkable limit, with the document and clause behind it."""

    def __init__(self, code, part, clause, title, severity=MAJOR,
                 minimum=None, maximum=None, unit="m", note=None):
        self.code = code
        self.part = part
        self.clause = clause
        self.title = title
        self.severity = severity
        self.minimum = minimum
        self.maximum = maximum
        self.unit = unit
        self.note = note

    def cite(self):
        return f"Approved Document {self.part}, {self.clause}"


# ---------------------------------------------------------------------------
# The rules. Dwellings, England. Figures from the Approved Documents.
# ---------------------------------------------------------------------------
RULES = {
    # --- Part K: protection from falling, collision and impact -------------
    "stair_rise": Rule(
        "stair_rise", "K", "1.2", "Stair rise", CRITICAL,
        minimum=0.150, maximum=0.220,
        note="Private stair. Every rise in a flight must be equal."),
    "stair_going": Rule(
        "stair_going", "K", "1.2", "Stair going", CRITICAL,
        minimum=0.220,
        note="Private stair. Rise and going must also satisfy "
             "2x rise + going between 550mm and 700mm."),
    "stair_pitch": Rule(
        "stair_pitch", "K", "1.3", "Stair pitch", CRITICAL,
        maximum=42.0, unit="deg", note="Private stair maximum pitch."),
    "stair_headroom": Rule(
        "stair_headroom", "K", "1.10", "Headroom over a stair", CRITICAL,
        minimum=2.000,
        note="Measured vertically from the pitch line. 1.8m may be accepted "
             "in a loft conversion at the lower side."),
    "handrail_height": Rule(
        "handrail_height", "K", "1.16", "Handrail height", MAJOR,
        minimum=0.900, maximum=1.000,
        note="Above the pitch line, or above floor level on a landing."),
    "guarding_stair": Rule(
        "guarding_stair", "K", "3.3", "Guarding to a stair", CRITICAL,
        minimum=0.900, note="Measured above the pitch line."),
    # AD K Diagram 3.1 draws the line at the wall of the house: inside a
    # single dwelling, a landing or gallery edge needs 900mm; step outside
    # onto a balcony and it becomes 1100mm. One combined rule here used to
    # hold every floor edge to the balcony figure, which reported a
    # compliant 950mm internal landing as a critical life-safety breach —
    # the ripping-out-compliant-work outcome this module exists to prevent.
    "guarding_floor": Rule(
        "guarding_floor", "K", "Diagram 3.1",
        "Guarding to an internal floor edge or landing",
        CRITICAL, minimum=0.900,
        note="Internal floor edges, landings and galleries in a single "
             "dwelling. External balconies are held to 1100mm — see "
             "guarding_balcony."),
    "guarding_balcony": Rule(
        "guarding_balcony", "K", "Diagram 3.1",
        "Guarding to an external balcony",
        CRITICAL, minimum=1.100,
        note="External balconies and accessible roof edges."),
    "guarding_gap": Rule(
        "guarding_gap", "K", "3.3", "Gap in guarding", CRITICAL,
        maximum=0.100,
        note="A 100mm sphere must not pass through. Aimed at small children."),

    # --- Part B: fire safety ----------------------------------------------
    "escape_window_area": Rule(
        "escape_window_area", "B1", "2.10",
        "Escape window clear openable area",
        CRITICAL, minimum=0.330, unit="m2",
        note="Unobstructed openable area for escape or rescue."),
    "escape_window_dim": Rule(
        "escape_window_dim", "B1", "2.10",
        "Escape window least dimension", CRITICAL, minimum=0.450,
        note="Both height and width of the openable area."),
    # AD B sets ONLY a maximum on the cill: above 1100mm the window cannot
    # be climbed out of. There is no minimum in the document — an invented
    # 0.800m floor here was failing fully compliant low-cill windows as
    # definite breaches. A low cill raises a Part K guarding question, not
    # a Part B escape one, and this module does not get to make limits up.
    "escape_window_cill": Rule(
        "escape_window_cill", "B1", "2.10", "Escape window cill height",
        MAJOR, maximum=1.100,
        note="Above floor level. Higher than 1100mm is not usable in escape."),

    # --- Part M: access ----------------------------------------------------
    # The paragraph number for the 450-1200mm band was never verified
    # against the document — the knowledge base records the provision
    # without one — so the citation names the provision, not an invented
    # clause. docs/UK_COMPLIANCE_KNOWLEDGE.md section 7.
    "socket_height": Rule(
        "socket_height", "M", "switches and sockets 450-1200mm",
        "Socket outlet height", MAJOR,
        minimum=0.450, maximum=1.200,
        note="Centre above finished floor level, new dwellings."),
    # AD M puts switches, sockets and controls in ONE 450-1200mm band.
    # A stricter 0.900m minimum here — presumably from the common practice
    # of mounting switches at light-switch height — was directing the
    # relocation of accessories the document explicitly permits.
    "switch_height": Rule(
        "switch_height", "M", "switches and sockets 450-1200mm",
        "Switch height", MAJOR,
        minimum=0.450, maximum=1.200,
        note="Centre above finished floor level, new dwellings. Same "
             "450-1200mm band as sockets."),
    "door_clear_width": Rule(
        "door_clear_width", "M", "9.7", "Clear opening width of a door",
        MAJOR, minimum=0.750,
        note="Clear width when open, not the leaf size."),
    "threshold_upstand": Rule(
        "threshold_upstand", "M", "6.7", "Accessible threshold upstand",
        MAJOR, maximum=0.015, note="An accessible threshold is level."),

    # --- Part C: site preparation and moisture ----------------------------
    "dpc_height": Rule(
        "dpc_height", "C", "5.8", "Damp-proof course above ground", MAJOR,
        minimum=0.150,
        note="Above adjoining external ground or paving. A raised drive or "
             "new patio is the usual way this gets breached."),

    # --- Part F: ventilation ----------------------------------------------
    "purge_ventilation_ratio": Rule(
        "purge_ventilation_ratio", "F", "1.5",
        "Purge ventilation opening area", MAJOR, minimum=0.05, unit="ratio",
        note="Openable area of at least 1/20 of the room's floor area."),

    # --- Part K again: headroom generally ---------------------------------
    "ceiling_height": Rule(
        "ceiling_height", "K", "—", "Habitable room ceiling height",
        ADVISORY, minimum=2.300,
        note="No longer a fixed regulation for most rooms, but below about "
             "2.3m affects usability, valuation and loft conversions."),
}


class Finding:
    """The outcome of one check against one measurement."""

    def __init__(self, rule, measured, uncertainty, verdict, message,
                 location=None):
        self.rule = rule
        self.measured = measured
        self.uncertainty = uncertainty
        self.verdict = verdict
        self.message = message
        self.location = location

    @property
    def severity(self):
        if self.verdict == PASS:
            return None
        if self.verdict == UNKNOWN:
            # "I could not check this" is not a finding against the
            # building. Filing an unmeasured stair under life-safety
            # failures would bury the real breaches under things that were
            # simply never captured — so it carries no severity and is
            # surfaced separately as a gap in the survey instead.
            return None
        if self.verdict == BORDERLINE:
            # A borderline life-safety item still needs looking at, but it
            # is not yet a breach, so it is not reported at full severity.
            return ADVISORY if self.rule.severity == ADVISORY else MAJOR
        return self.rule.severity

    def as_dict(self):
        return {
            "code": self.rule.code,
            "title": self.rule.title,
            "part": self.rule.part,
            "citation": self.rule.cite(),
            "verdict": self.verdict,
            "severity": self.severity,
            "measured": (round(self.measured, 4)
                         if self.measured is not None else None),
            "uncertainty": (round(self.uncertainty, 4)
                            if self.uncertainty else None),
            "unit": self.rule.unit,
            "limit_min": self.rule.minimum,
            "limit_max": self.rule.maximum,
            "message": self.message,
            "location": self.location,
            "guidance_note": self.rule.note,
        }


def check(code, measured, uncertainty=0.0, location=None):
    """Test one measurement against one rule.

    `uncertainty` is the plus-or-minus on the measurement, in the rule's
    units. It is what separates a defensible finding from a confident guess:
    a value that only breaches a limit by less than its own error bar has
    not been shown to breach anything.
    """
    rule = RULES.get(code)
    if rule is None:
        raise KeyError(
            f"unknown rule {code!r}; known: {', '.join(sorted(RULES))}")

    if measured is None:
        return Finding(rule, None, None, UNKNOWN,
                       f"{rule.title} was not measured, so it could not be "
                       f"checked. {rule.cite()}.", location)

    unc = abs(uncertainty or 0.0)
    lo, hi = measured - unc, measured + unc
    u = rule.unit

    def fmt(v):
        return f"{v:.3f}{u}" if u != "deg" else f"{v:.1f}deg"

    band = f" (±{fmt(unc).lstrip()})" if unc else ""

    # Definite breaches: the whole error band sits outside the limit.
    if rule.minimum is not None and hi < rule.minimum:
        return Finding(rule, measured, unc, FAIL,
                       f"{rule.title} measures {fmt(measured)}{band}, below "
                       f"the {fmt(rule.minimum)} minimum. {rule.cite()}.",
                       location)
    if rule.maximum is not None and lo > rule.maximum:
        return Finding(rule, measured, unc, FAIL,
                       f"{rule.title} measures {fmt(measured)}{band}, above "
                       f"the {fmt(rule.maximum)} maximum. {rule.cite()}.",
                       location)

    # Straddling a limit — the honest middle ground, and the reason this
    # module exists. Do not send someone ripping out a compliant stair.
    if rule.minimum is not None and lo < rule.minimum <= hi:
        return Finding(rule, measured, unc, BORDERLINE,
                       f"{rule.title} measures {fmt(measured)}{band} against "
                       f"a {fmt(rule.minimum)} minimum — within measurement "
                       f"error of the limit. Check with a tape on site "
                       f"before acting. {rule.cite()}.", location)
    if rule.maximum is not None and lo <= rule.maximum < hi:
        return Finding(rule, measured, unc, BORDERLINE,
                       f"{rule.title} measures {fmt(measured)}{band} against "
                       f"a {fmt(rule.maximum)} maximum — within measurement "
                       f"error of the limit. Check with a tape on site "
                       f"before acting. {rule.cite()}.", location)

    return Finding(rule, measured, unc, PASS,
                   f"{rule.title} {fmt(measured)}{band} — within "
                   f"{rule.cite()}.", location)


# ---------------------------------------------------------------------------
# Composite checks, where the rule is a relationship rather than a limit
# ---------------------------------------------------------------------------

def check_stair(rise, going, uncertainty=0.005, location=None):
    """A stair is judged by its geometry as a whole, not rise alone.

    Beyond the individual limits, Part K requires 2 x rise + going to fall
    between 550mm and 700mm — the relationship that makes a flight
    comfortable rather than merely legal.
    """
    findings = [check("stair_rise", rise, uncertainty, location),
                check("stair_going", going, uncertainty, location)]

    if rise is not None and going is not None:
        import math
        pitch = math.degrees(math.atan(rise / going)) if going else None
        # Pitch error compounds from both measurements.
        pitch_unc = (math.degrees(
            math.atan((rise + uncertainty) / max(going - uncertainty, 1e-6)))
            - pitch) if pitch is not None else 0.0
        findings.append(check("stair_pitch", pitch, abs(pitch_unc), location))

        formula = 2 * rise + going
        f_unc = 3 * uncertainty
        rule = RULES["stair_going"]
        if formula + f_unc < 0.550 or formula - f_unc > 0.700:
            findings.append(Finding(
                rule, formula, f_unc, FAIL,
                f"2x rise + going is {formula * 1000:.0f}mm, outside the "
                f"550-700mm range. The flight will feel wrong to climb even "
                f"if each dimension passes alone. {rule.cite()}.", location))
        elif formula - f_unc < 0.550 or formula + f_unc > 0.700:
            findings.append(Finding(
                rule, formula, f_unc, BORDERLINE,
                f"2x rise + going is {formula * 1000:.0f}mm ±{f_unc * 1000:.0f}, "
                f"at the edge of the 550-700mm range. Verify on site. "
                f"{rule.cite()}.", location))
    return findings


def check_escape_window(width, height, cill_height, uncertainty=0.02,
                        location=None):
    """An escape window must satisfy area, least dimension AND cill height.

    Passing one and failing another is still a failure, and it is the
    combination that gets missed — a wide, shallow window can have ample
    area and be impossible to climb through.
    """
    area = (width * height) if (width and height) else None
    area_unc = (abs((width + uncertainty) * (height + uncertainty) - area)
                if area else 0.0)
    least = min(width, height) if (width and height) else None
    return [
        check("escape_window_area", area, area_unc, location),
        check("escape_window_dim", least, uncertainty, location),
        check("escape_window_cill", cill_height, uncertainty, location),
    ]


def check_purge_ventilation(openable_area_m2, floor_area_m2,
                            uncertainty_ratio=0.005, location=None):
    """Openable area must be at least 1/20 of the room's floor area."""
    if not floor_area_m2:
        return [check("purge_ventilation_ratio", None, 0, location)]
    ratio = (openable_area_m2 or 0.0) / floor_area_m2
    return [check("purge_ventilation_ratio", ratio, uncertainty_ratio,
                  location)]


def summarise(findings):
    """Triage a set of findings into something a builder can act on."""
    out = {"pass": 0, "fail": 0, "borderline": 0, "insufficient_data": 0}
    by_severity = {CRITICAL: [], MAJOR: [], ADVISORY: []}
    for f in findings:
        out[f.verdict] += 1
        if f.severity:
            by_severity[f.severity].append(f.as_dict())

    checked = len(findings) - out[UNKNOWN]
    # Gaps in the survey are reported in their own right: a rule that could
    # not be checked is a reason to go back on site, and hiding it would let
    # a report look cleaner than the evidence supports.
    not_checked = [f.as_dict() for f in findings if f.verdict == UNKNOWN]
    return {
        "counts": out,
        "checked": checked,
        "not_checked": not_checked,
        "critical": by_severity[CRITICAL],
        "major": by_severity[MAJOR],
        "advisory": by_severity[ADVISORY],
        "headline": _headline(out),
        "disclaimer":
            "Approved Documents are guidance, not the regulation itself — "
            "compliance can be demonstrated another way, existing work is "
            "judged against the rules in force when it was built, and "
            "historic or listed buildings carry exemptions. This is a "
            "competent first pass from measured geometry, not a "
            "determination. Building control decides.",
    }


def _headline(counts):
    if counts["fail"]:
        return (f"{counts['fail']} item(s) measured outside the guidance "
                f"limits.")
    if counts["borderline"]:
        return (f"Nothing clearly outside the limits, but "
                f"{counts['borderline']} item(s) sit within measurement "
                f"error of one — check those on site.")
    if counts["insufficient_data"] and not counts["pass"]:
        return "Nothing could be checked from the geometry available."
    return f"All {counts['pass']} checked item(s) within the guidance limits."
