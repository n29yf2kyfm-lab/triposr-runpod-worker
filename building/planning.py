"""Planning Mode — what the site itself will let you build.

Every other module in this worker measures the building. This one asks
whether the work is allowed, which is the question that kills jobs latest
and most expensively: a builder prices an extension, wins it, orders the
steel, and then finds the street is an Article 4 area and the permitted
development rights everyone assumed were there were removed in 2019.

The source is the government's Planning Data platform — the national
register that Local Planning Authorities publish their designations to. It
is free, needs no key, and covers over 200 datasets. This module queries the
dozen that change what a builder can do, and translates each one into what
it MEANS for the work rather than reporting a dataset name.

TWO KINDS OF LOOKUP, and the difference matters. Most designations either
cover the site or do not, so a point-in-polygon test answers them. But a
listed building NEXT DOOR still constrains what you build, because its
setting is protected, and a protected tree next door constrains where you
can dig. Those are searched within a radius instead.

WHAT THIS REFUSES TO DO. It will not tell anyone their scheme is permitted
development. It reports the designations the national register holds for a
location, which is a screening check and not a planning decision — see
SCREENING_WARNING for why absence of a designation is not proof of absence.
The output is what you take to the LPA, not a substitute for asking them.
"""
import math
import os
import re

# The national register. Free, no key, no rate limit published.
PLANNING_API = os.environ.get(
    "PLANNING_API", "https://www.planning.data.gov.uk/entity.json")

HTTP_TIMEOUT = 30

# How far to look for designations whose SETTING reaches the site. 100m is
# the distance at which a listed building's setting is normally considered,
# and comfortably beyond the 12m that BS 5837 puts a mature oak's root
# protection area at.
NEARBY_RADIUS_M = 100.0

# Degrees of latitude per metre. Longitude is scaled by cos(latitude) at the
# point — at 52°N a degree of longitude is only 62% of a degree of latitude,
# and using the same figure for both makes the search box a squashed
# rectangle that misses designations to the east and west.
DEG_PER_M_LAT = 1.0 / 111_320.0

MAX_ENTITIES = 200

# --- what each designation actually means to a builder ---------------------
#
# Severity is about the consequence of getting it wrong, not the paperwork:
#
#   critical  doing the work without consent is a criminal offence, or the
#             work will simply not be permitted
#   major     permitted development rights are affected — an application is
#             needed where one would not otherwise be
#   advisory  it constrains how the work is done or costed, but does not by
#             itself stop it

CRITICAL, MAJOR, ADVISORY = "critical", "major", "advisory"

CONSTRAINTS = {
    "listed-building": (
        CRITICAL, "Listed building",
        "Listed Building Consent is needed for ANY work affecting its "
        "character, inside as well as out, and that includes replacing "
        "windows, re-plastering in gypsum, and removing internal walls. "
        "Doing it without consent is a criminal offence, not a planning "
        "breach — it carries an unlimited fine and the council can require "
        "the work to be undone. The listing covers curtilage structures put "
        "up before July 1948 too: outbuildings, walls and railings."),
    "scheduled-monument": (
        CRITICAL, "Scheduled monument",
        "Scheduled Monument Consent is needed from the Secretary of State "
        "before any works, including groundworks. Unauthorised works are a "
        "criminal offence."),
    "tree-preservation-zone": (
        CRITICAL, "Tree Preservation Order",
        "Cutting, topping, lopping or uprooting a protected tree without "
        "consent is a criminal offence with an unlimited fine. It also "
        "drives the FOUNDATIONS: NHBC 4.2 requires depth by species and "
        "distance on shrinkable clay, and you cannot simply remove the tree "
        "to avoid it. Price the foundation from the tree survey, not from "
        "the standard detail."),
    "tree-preservation-order": (
        CRITICAL, "Tree Preservation Order",
        "As above — consent needed before any work to the tree, and the "
        "foundation design follows the tree, not the other way round."),
    "article-4-direction-area": (
        MAJOR, "Article 4 direction",
        "Permitted development rights have been REMOVED here by direction. "
        "Work that would be permitted development anywhere else needs a "
        "planning application. Check which classes the direction covers "
        "before pricing the job — this is the single most common reason a "
        "priced extension turns out to need an application nobody allowed "
        "for."),
    "conservation-area": (
        MAJOR, "Conservation area",
        "Permitted development is restricted: side extensions, cladding, "
        "roof extensions and satellite dishes on the front all lose their "
        "PD rights, and two-storey rear extensions do too. Materials must "
        "match. Demolition of a building or a boundary wall needs consent, "
        "and works to ANY tree need six weeks' written notice to the "
        "council even without a TPO."),
    "world-heritage-site": (
        MAJOR, "World Heritage Site",
        "Permitted development is restricted as in a conservation area, and "
        "the site's Outstanding Universal Value is a material planning "
        "consideration. Expect a design and access statement."),
    "green-belt": (
        MAJOR, "Green Belt",
        "New buildings are inappropriate development by default. Extensions "
        "are allowed only where they are not disproportionate over and "
        "above the ORIGINAL building — as built, or as it stood in July "
        "1948 — so previous extensions count against the allowance even if "
        "someone else built them."),
    "national-park": (
        MAJOR, "National Park",
        "Permitted development is restricted, and the National Park "
        "Authority is the planning authority rather than the district "
        "council."),
    "area-of-outstanding-natural-beauty": (
        MAJOR, "National Landscape (formerly AONB)",
        "Permitted development is restricted — cladding, larger extensions "
        "and outbuildings over 20m2 within 5m of the house all lose PD "
        "rights."),
    "flood-risk-zone": (
        MAJOR, "Flood risk zone",
        "A Flood Risk Assessment is required with any planning application, "
        "and finished floor levels, wiring heights and floor construction "
        "may all be dictated by it. It also affects the client's buildings "
        "insurance, which is worth telling them before they commit."),
    "site-of-special-scientific-interest": (
        MAJOR, "SSSI",
        "Natural England must be consulted, and operations likely to damage "
        "the special interest need consent. The SSSI impact risk zones "
        "extend well beyond the boundary."),
    "special-area-of-conservation": (
        MAJOR, "Special Area of Conservation",
        "Habitats Regulations Assessment may be required. Nutrient "
        "neutrality rules block residential development outright in several "
        "catchments."),
    "ancient-woodland": (
        MAJOR, "Ancient woodland",
        "Irreplaceable habitat. Development causing loss or deterioration "
        "is refused other than in wholly exceptional circumstances, and a "
        "15m buffer is normally expected."),
    "heritage-at-risk": (
        ADVISORY, "Heritage at risk",
        "The asset is on the at-risk register. Grant funding may be "
        "available, and the council will take a close interest."),
    "locally-listed-building": (
        ADVISORY, "Locally listed building",
        "Not statutorily listed, so no Listed Building Consent, but its "
        "significance is a material consideration and the council will "
        "resist unsympathetic alteration."),
    "safety-hazard-area": (
        ADVISORY, "Safety hazard area",
        "The Health and Safety Executive is a statutory consultee. Expect "
        "the application to take longer."),
    "public-safety-zone-around-airport": (
        ADVISORY, "Airport public safety zone",
        "Development is restricted by height and by use. Consult the "
        "airport operator before designing."),
    "nuclear-safety-zone": (
        ADVISORY, "Nuclear safety consultation zone",
        "The Office for Nuclear Regulation is consulted on applications."),
    "brownfield-land": (
        ADVISORY, "On the brownfield register",
        "Previously developed land. Often helpful — it supports the "
        "principle of development — but expect a contamination assessment "
        "under Part C."),
}

# Designations answered by asking whether the site sits inside them.
SITE_DATASETS = (
    "conservation-area", "article-4-direction-area", "green-belt",
    "flood-risk-zone", "national-park", "area-of-outstanding-natural-beauty",
    "world-heritage-site", "site-of-special-scientific-interest",
    "special-area-of-conservation", "ancient-woodland", "brownfield-land",
    "safety-hazard-area", "public-safety-zone-around-airport",
    "nuclear-safety-zone", "heritage-at-risk",
)

# Designations whose SETTING reaches the site even when the site is outside
# them. A listed building next door constrains the design; a protected tree
# next door constrains the foundation.
NEARBY_DATASETS = (
    "listed-building", "scheduled-monument", "tree-preservation-zone",
    "locally-listed-building",
)

# Context rather than constraint: who the application goes to.
CONTEXT_DATASETS = ("local-planning-authority", "parish", "ward")

# Permitted development classes each designation bites on. Used to answer
# the question actually being asked — "can I just build it?" — rather than
# leaving a builder to work it out from a list of designations.
PD_REMOVED_BY = ("article-4-direction-area",)
PD_RESTRICTED_BY = (
    "conservation-area", "national-park",
    "area-of-outstanding-natural-beauty", "world-heritage-site",
    "green-belt",
)

SCREENING_WARNING = (
    "This is a SCREENING CHECK against the national planning register, not "
    "a planning decision and not a substitute for asking the council. The "
    "absence of a designation here is not proof there isn't one: local "
    "planning authorities publish to this register voluntarily and "
    "progressively, Article 4 directions in particular are incompletely "
    "published, and a listing can be made at any time. Confirm with the LPA "
    "before pricing on it.")


class PlanningError(ValueError):
    """Raised when site constraints cannot be established honestly.

    A wrong answer here is not a wrong quantity — it is a builder starting
    work that needed consent, which on a listed building is a criminal
    offence. Silence is safer than a guess.
    """


# --- coverage ---------------------------------------------------------------

# The Planning Data platform is an England-only service. Wales, Scotland and
# Northern Ireland have their own planning systems, their own permitted
# development orders, and their own registers — Scotland's PD rules differ
# substantially from England's, so answering an Edinburgh postcode from
# English data would be wrong rather than merely absent.
NON_ENGLISH_AREAS = {
    "CF": "Wales", "SA": "Wales", "LL": "Wales", "NP": "Wales",
    "SY": "Wales or Shropshire", "LD": "Wales",
    "AB": "Scotland", "DD": "Scotland", "DG": "Scotland", "EH": "Scotland",
    "FK": "Scotland", "G": "Scotland", "HS": "Scotland", "IV": "Scotland",
    "KA": "Scotland", "KW": "Scotland", "KY": "Scotland", "ML": "Scotland",
    "PA": "Scotland", "PH": "Scotland", "TD": "Scotland", "ZE": "Scotland",
    "BT": "Northern Ireland",
    "GY": "Guernsey", "JE": "Jersey", "IM": "Isle of Man",
}

# Postcode areas that straddle the border, so the postcode alone cannot say
# which planning system applies.
BORDER_AREAS = {"CH", "SY", "HR", "SH", "NE", "CA", "TD", "DG"}


def postcode_area(postcode):
    """The alphabetic area from the FRONT of a postcode.

    Read from the front deliberately. Collecting every letter turns "B36
    8AR" into "BA", which is Bath — the same trap valuation.py hit.
    """
    text = re.sub(r"\s+", "", str(postcode or "")).upper()
    match = re.match(r"^([A-Z]{1,2})", text)
    return match.group(1) if match else None


def check_coverage(postcode):
    """Refuse a postcode this register does not cover."""
    area = postcode_area(postcode)
    if not area:
        raise PlanningError(
            f"{postcode!r} is not a recognisable UK postcode")
    nation = NON_ENGLISH_AREAS.get(area)
    if nation and area not in BORDER_AREAS:
        raise PlanningError(
            f"the national planning register covers England only, and {area} "
            f"is {nation}. {nation} has its own permitted development order "
            f"and its own register, and answering from English data would be "
            f"wrong rather than merely incomplete.")
    return True


# --- geometry ---------------------------------------------------------------

def bbox_wkt(lat, lon, radius_m=NEARBY_RADIUS_M):
    """A square in WKT around a point, sized in METRES.

    Longitude is scaled by cos(latitude). Using the same degrees-per-metre
    for both axes makes the box 38% too narrow at Birmingham's latitude, and
    the error is entirely in the east-west direction — so designations to
    either side of a site go unreported while ones to the north and south
    are found. That reads as "no constraint" rather than as a bug.
    """
    if radius_m <= 0:
        raise PlanningError("search radius must be positive")
    dlat = radius_m * DEG_PER_M_LAT
    scale = math.cos(math.radians(lat))
    if abs(scale) < 1e-6:
        raise PlanningError("cannot build a search box at the pole")
    dlon = dlat / scale
    corners = [(lon - dlon, lat - dlat), (lon + dlon, lat - dlat),
               (lon + dlon, lat + dlat), (lon - dlon, lat + dlat),
               (lon - dlon, lat - dlat)]
    inner = ",".join(f"{x:.7f} {y:.7f}" for x, y in corners)
    return f"POLYGON(({inner}))"


# --- fetching ---------------------------------------------------------------

def _fetch(params, timeout=HTTP_TIMEOUT):
    """One call to the register. Returns entities, or raises."""
    import requests
    try:
        response = requests.get(PLANNING_API, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json() or {}
    except Exception as e:
        raise PlanningError(
            f"the national planning register could not be reached "
            f"({type(e).__name__}). Site constraints are not something to "
            f"assume, so nothing is reported rather than an empty list that "
            f"reads as 'no constraints'.")
    return payload.get("entities") or []


def fetch_at_point(lat, lon, datasets=SITE_DATASETS, timeout=HTTP_TIMEOUT):
    """Designations whose boundary contains this point."""
    return _fetch({"longitude": lon, "latitude": lat,
                   "dataset": list(datasets), "limit": MAX_ENTITIES},
                  timeout)


def fetch_nearby(lat, lon, datasets=NEARBY_DATASETS,
                 radius_m=NEARBY_RADIUS_M, timeout=HTTP_TIMEOUT):
    """Designations within `radius_m` whose setting reaches the site."""
    return _fetch({"geometry": bbox_wkt(lat, lon, radius_m),
                   "geometry_relation": "intersects",
                   "dataset": list(datasets), "limit": MAX_ENTITIES},
                  timeout)


# --- reading the answer -----------------------------------------------------

def describe(entity, on_site=True):
    """One register entity as a finding a builder can act on."""
    dataset = entity.get("dataset")
    known = CONSTRAINTS.get(dataset)
    severity, label, meaning = known if known else (
        ADVISORY, (dataset or "designation").replace("-", " "),
        "Recorded on the national planning register. Ask the LPA what it "
        "means for this site.")

    name = entity.get("name") or entity.get("reference") or label
    finding = {
        "dataset": dataset,
        "label": label,
        "name": name,
        "severity": severity,
        "on_site": bool(on_site),
        "means": meaning,
        "reference": entity.get("reference"),
        "entity": entity.get("entity"),
    }

    # Flood zone 3 is a materially different proposition from zone 2 and the
    # register carries the level, so report it rather than making someone
    # look it up.
    level = entity.get("flood-risk-level")
    if level:
        finding["flood_zone"] = str(level)
        if str(level) in ("3", "3a", "3b"):
            finding["severity"] = MAJOR
            finding["means"] = (
                f"Flood Zone {level} — high probability. " + meaning +
                " In Zone 3b, the functional floodplain, residential "
                "development is not normally permitted at all.")

    grade = entity.get("listed-building-grade")
    if grade:
        finding["grade"] = grade

    for key in ("documentation-url", "document-url"):
        if entity.get(key):
            finding["document_url"] = entity[key]
            break

    if not on_site:
        # A designation NEXT DOOR is a different proposition from one on the
        # site, and ranking them the same buries the finding that matters. A
        # listed building you own means Listed Building Consent and a
        # criminal offence without it; a listed building over the road means
        # its setting is a material consideration in your application. Both
        # are real, only one is critical, and a Bath postcode returns 97 of
        # the second kind — enough to push a genuine on-site constraint off
        # the end of the list.
        if dataset in NEARBY_STILL_CRITICAL:
            finding["means"] = (
                f"Within {NEARBY_RADIUS_M:.0f}m of the site. Being the "
                f"neighbour's tree changes nothing: the offence is cutting "
                f"a protected tree whoever owns it, the root protection area "
                f"crosses the boundary, and NHBC 4.2 sets your foundation "
                f"depth from the distance to it. " + finding["means"])
        else:
            finding["severity"] = {CRITICAL: MAJOR,
                                   MAJOR: ADVISORY}.get(severity, ADVISORY)
            finding["means"] = (
                f"Within {NEARBY_RADIUS_M:.0f}m of the site, not on it, so "
                f"its SETTING is the consideration rather than consent for "
                f"the asset itself. " + finding["means"])
    return finding


# Above this many neighbours of one kind, listing them individually buries
# everything else. A historic centre returns a hundred listed buildings and
# the useful fact is "you are in the middle of a listed terrace", not their
# addresses.
MAX_NEARBY_LISTED = 5

# Designations that stay critical even next door. A protected tree is the
# case: the offence is cutting it whoever owns it, its root protection area
# crosses the boundary, and NHBC 4.2 sets foundation depth from the distance
# to the tree — which on a terrace or a tight plot is nearly always the
# neighbour's. Downgrading it would understate the one constraint that
# changes the groundworks price.
NEARBY_STILL_CRITICAL = {"tree-preservation-zone", "tree-preservation-order"}


def _group_nearby(findings):
    """Summarise large runs of same-kind neighbours into one finding."""
    by_dataset = {}
    for finding in findings:
        if finding["on_site"]:
            continue
        by_dataset.setdefault(finding["dataset"], []).append(finding)

    out = [f for f in findings if f["on_site"]]
    for dataset, group in by_dataset.items():
        if len(group) <= MAX_NEARBY_LISTED:
            out += group
            continue
        grades = sorted({f["grade"] for f in group if f.get("grade")})
        head = group[:MAX_NEARBY_LISTED]
        summary = dict(head[0])
        summary.update({
            "name": f"{len(group)} within {NEARBY_RADIUS_M:.0f}m",
            "count": len(group),
            "examples": [f["name"] for f in head],
            "reference": None,
            "entity": None,
        })
        if grades:
            summary["grades"] = grades
            summary["means"] = (
                f"{len(group)} listed buildings within "
                f"{NEARBY_RADIUS_M:.0f}m, graded {', '.join(grades)}. The "
                f"site sits inside a designated historic group, so expect "
                f"the council to assess the effect on the setting of all of "
                f"them, and expect materials and detailing to be conditioned."
            )
        out.append(summary)
    return out


def permitted_development(findings):
    """Whether permitted development can be relied on. The real question.

    Answered in three states rather than yes/no, because "probably" is the
    truthful answer for most sites and rounding it to "yes" is how a builder
    ends up mid-job with an enforcement notice.
    """
    removed = [f for f in findings
               if f["dataset"] in PD_REMOVED_BY and f["on_site"]]
    restricted = [f for f in findings
                  if f["dataset"] in PD_RESTRICTED_BY and f["on_site"]]
    listed = [f for f in findings if f["dataset"] == "listed-building"
              and f["on_site"]]

    if listed:
        return {
            "status": "consent_required",
            "note": ("This is a listed building. Listed Building Consent is "
                     "needed for work affecting its character whether or not "
                     "planning permission is, and permitted development does "
                     "not remove that requirement."),
            "blocking": [f["label"] for f in listed],
        }
    if removed:
        return {
            "status": "removed",
            "note": ("An Article 4 direction applies to this site, so "
                     "permitted development rights have been withdrawn for "
                     "the classes it names. Read the direction before "
                     "pricing: it may cover only one class, or all of them."),
            "blocking": [f["name"] for f in removed],
        }
    if restricted:
        return {
            "status": "restricted",
            "note": ("Permitted development is restricted here. Side "
                     "extensions, cladding and roof alterations commonly "
                     "lose their PD rights on designated land, so check the "
                     "specific class against the GPDO before assuming."),
            "blocking": [f["label"] for f in restricted],
        }
    return {
        "status": "not_restricted",
        "note": ("No designation on the national register removes or "
                 "restricts permitted development at this location. That is "
                 "not the same as saying the work IS permitted development "
                 "— the size, height and position limits in the GPDO still "
                 "apply, and so does the property's own planning history, "
                 "which this register does not hold."),
        "blocking": [],
    }


def screen(lat, lon, radius_m=NEARBY_RADIUS_M, timeout=HTTP_TIMEOUT):
    """Every constraint bearing on a site, and what it means."""
    on_site = fetch_at_point(lat, lon, timeout=timeout)
    near = fetch_nearby(lat, lon, radius_m=radius_m, timeout=timeout)

    findings = [describe(e, on_site=True) for e in on_site]
    seen = {f["entity"] for f in findings}
    findings += [describe(e, on_site=False) for e in near
                 if e.get("entity") not in seen]
    findings = _group_nearby(findings)

    order = {CRITICAL: 0, MAJOR: 1, ADVISORY: 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3),
                                 not f["on_site"], f["label"]))

    context = {}
    try:
        for entity in fetch_at_point(lat, lon, CONTEXT_DATASETS, timeout):
            context.setdefault(entity.get("dataset"), entity.get("name"))
    except PlanningError:
        pass                       # context is a nicety, not a constraint

    counts = {level: sum(1 for f in findings if f["severity"] == level)
              for level in (CRITICAL, MAJOR, ADVISORY)}

    return {
        "location": {"lat": round(lat, 6), "lon": round(lon, 6),
                     "search_radius_m": radius_m},
        "authority": context.get("local-planning-authority"),
        "context": context,
        "constraints": findings,
        "permitted_development": permitted_development(findings),
        "totals": {
            "constraints": len(findings),
            "on_site": sum(1 for f in findings if f["on_site"]),
            "critical": counts[CRITICAL],
            "major": counts[MAJOR],
            "advisory": counts[ADVISORY],
        },
        "source": ("Planning Data platform, planning.data.gov.uk — the "
                   "national register LPAs publish designations to. Contains "
                   "public sector information licensed under the Open "
                   "Government Licence v3.0."),
        "warnings": [SCREENING_WARNING],
    }


# --- handler entry point ----------------------------------------------------

def run(spec, prog, output_dir):
    """Planning mode entry point."""
    import json

    prog.stage("fetching")
    gps = spec.get("gps") or {}
    lat, lon = gps.get("lat"), gps.get("lon")

    if lat is None or lon is None:
        postcode = spec.get("postcode")
        address = spec.get("address") or postcode
        if not address:
            raise PlanningError(
                "planning mode needs an address, a postcode, or gps "
                "{lat, lon} to know which site to screen.")
        if postcode:
            check_coverage(postcode)
        import roof
        try:
            lat, lon = roof._geocode_uk(address)
        except Exception as e:
            raise PlanningError(
                f"could not locate {address!r} ({type(e).__name__}). Supply "
                f"gps: {{\"lat\": ..., \"lon\": ...}} directly.")

    prog.stage("screening")
    result = screen(lat, lon,
                    radius_m=spec.get("search_radius_m") or NEARBY_RADIUS_M)

    prog.stage("exporting")
    import paths
    directory = paths.ensure(output_dir)
    scan = spec.get("scan_id") or "planning"
    path = os.path.join(directory, f"planning_{scan}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    warnings = list(result["warnings"])
    critical = [f for f in result["constraints"]
                if f["severity"] == CRITICAL and f["on_site"]]
    for finding in critical:
        warnings.insert(0, f"{finding['label']}: {finding['name']}. "
                           f"{finding['means']}")

    return ([(path, f"planning/{scan}.json", None)],
            {"planning": result, "warnings": warnings})


run_mode = run
