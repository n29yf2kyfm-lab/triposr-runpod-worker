"""Tests for Planning Mode — what the site will let you build.

The output that matters is a single sentence: can this be built under
permitted development, or does it need an application? Getting that wrong
costs a builder the job, and on a listed building it is a criminal offence,
so most of these tests are about the cases where the module must NOT say
"no constraints".

Network-free. The register is stubbed, because a test that depends on a
government service being up is a test that fails for reasons nobody can fix.

Run: python building/test_planning.py
"""
import math
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import planning as P  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


class _Prog:
    def stage(self, *a, **k):
        pass


# ---- 1. coverage — England only -------------------------------------------
# Scotland's permitted development order differs substantially from
# England's, so answering an Edinburgh postcode from English data would be
# wrong rather than merely absent.
check("1a a Birmingham postcode is covered", P.check_coverage("B36 8AR"))
check("1b a London postcode is covered", P.check_coverage("SW1A 1AA"))
check("1c a Bath postcode is covered", P.check_coverage("BA1 1LZ"))

for bad, nation in [("EH1 1AA", "Scotland"), ("G1 1AA", "Scotland"),
                    ("CF10 1AA", "Wales"), ("LL30 1AA", "Wales"),
                    ("BT1 1AA", "Northern Ireland"),
                    ("JE2 3AA", "Jersey"), ("IM1 1AA", "Isle of Man")]:
    try:
        P.check_coverage(bad)
        check(f"1d {bad} ({nation}) refused", False, "accepted")
    except P.OutsideCoverageError as e:
        check(f"1d {bad} ({nation}) refused", nation in str(e), str(e))

# BEING IN WALES IS NOT A BREAKAGE. The refusal is right — Welsh PD rights
# come from a different order and answering from English data would be wrong
# rather than incomplete — but it is an answer about jurisdiction, and the
# handler completes the job with status "no_data" instead of failing it.
#
# This deliberately does NOT inherit PlanningError. A caller catching that is
# handling "the screening could not be done"; "the site is in Wales" is a
# different statement and wants a different response from the app.
from validation import NoDataError as _NoData  # noqa: E402
try:
    P.check_coverage("CF10 1AA")
    check("1d-i outside coverage is a no-data answer, not a failure", False)
except _NoData:
    check("1d-i outside coverage is a no-data answer, not a failure", True)
check("1d-ii outside coverage is NOT a PlanningError",
      not issubclass(P.OutsideCoverageError, P.PlanningError))
# An unreadable postcode still IS a failure — the caller typed something
# wrong, and retrying with the same input will not help.
#
# "12345" and not "not a postcode": postcode_area reads the leading letters,
# so that string yields the area "NO", which is no recognised nation and
# sails straight through. check_coverage screens jurisdiction, it is not the
# postcode validator, and pretending otherwise here would test the wrong
# function.
try:
    P.check_coverage("12345")
    check("1d-iii an unreadable postcode still fails", False)
except _NoData:
    check("1d-iii an unreadable postcode still fails", False,
          "classed as no_data — bad input is not missing data")
except P.PlanningError:
    check("1d-iii an unreadable postcode still fails", True)

# THE parsing bug this guards, same one valuation.py hit: "B36 8AR" contains
# A and R in its inward code, so collecting every letter turns Birmingham
# into "BA", which is Bath.
check("1e the area is read from the FRONT of the postcode",
      P.postcode_area("B36 8AR") == "B", P.postcode_area("B36 8AR"))
check("1f a two-letter area is read whole",
      P.postcode_area("SW1A 1AA") == "SW")
check("1g nonsense is refused", P.postcode_area("!!!") is None)


# ---- 2. the search box, in metres -----------------------------------------
# A degree of longitude at 52°N is only 61% of a degree of latitude. Using
# one figure for both makes the box 39% too narrow east-west, so designations
# to either side go unreported — which reads as "no constraint", not as a bug.
_wkt = P.bbox_wkt(52.5, -1.9, 100.0)
_pts = [tuple(map(float, p.split()))
        for p in _wkt[len("POLYGON(("):-2].split(",")]
_h = (max(p[1] for p in _pts) - min(p[1] for p in _pts)) * 111_320.0
_w = ((max(p[0] for p in _pts) - min(p[0] for p in _pts)) * 111_320.0
      * math.cos(math.radians(52.5)))
check("2a the box is the right height in metres", abs(_h - 200.0) < 1.0,
      f"{_h:.1f}m")
check("2b and the right WIDTH — longitude scaled by cos(latitude)",
      abs(_w - 200.0) < 1.0, f"{_w:.1f}m: not scaled by cos(lat)?")
check("2c the ring is closed", _pts[0] == _pts[-1])

# The scaling must actually vary with latitude, or it is a coincidence.
_north = P.bbox_wkt(58.0, -3.0, 100.0)
_south = P.bbox_wkt(50.0, -3.0, 100.0)


def _lon_span(wkt):
    pts = [tuple(map(float, p.split()))
           for p in wkt[len("POLYGON(("):-2].split(",")]
    return max(p[0] for p in pts) - min(p[0] for p in pts)


check("2d a box further north spans more DEGREES of longitude",
      _lon_span(_north) > _lon_span(_south) * 1.2,
      f"{_lon_span(_north):.6f} vs {_lon_span(_south):.6f}")

try:
    P.bbox_wkt(52.5, -1.9, 0)
    check("2e a zero radius is refused", False)
except P.PlanningError:
    check("2e a zero radius is refused", True)


# ---- 3. reading one designation -------------------------------------------
_listed = P.describe({"dataset": "listed-building", "name": "THE OLD HALL",
                      "listed-building-grade": "II*", "entity": 1},
                     on_site=True)
check("3a a listed building on site is critical",
      _listed["severity"] == P.CRITICAL, _listed["severity"])
check("3b the grade is reported", _listed["grade"] == "II*")
check("3c and it says consent is needed, not just 'listed'",
      "Listed Building Consent" in _listed["means"])
check("3d and that it is a criminal offence without it",
      "criminal offence" in _listed["means"])

# A listed building NEXT DOOR is a setting consideration, not consent for
# your own building. Ranking them the same buries the on-site findings — a
# Bath postcode returns 95 neighbours.
_near = P.describe({"dataset": "listed-building", "name": "X", "entity": 2},
                   on_site=False)
check("3e a listed building nearby is downgraded from critical",
      _near["severity"] == P.MAJOR, _near["severity"])
check("3f and says the SETTING is what is at stake",
      "SETTING" in _near["means"])

# Flood Zone 3 is a materially different proposition from Zone 2, and the
# register carries the level, so it is reported rather than looked up.
_flood2 = P.describe({"dataset": "flood-risk-zone", "flood-risk-level": "2",
                      "entity": 3})
_flood3 = P.describe({"dataset": "flood-risk-zone", "flood-risk-level": "3",
                      "entity": 4})
check("3g the flood zone level is reported", _flood2["flood_zone"] == "2")
check("3h zone 3 says high probability", "high probability" in
      _flood3["means"])
check("3i and names the functional floodplain rule",
      "3b" in _flood3["means"])

# An unknown dataset must not be silently dropped — the register grows.
_unknown = P.describe({"dataset": "some-new-designation", "entity": 5})
check("3j an unrecognised designation is still reported",
      _unknown["label"] == "some new designation", _unknown["label"])
check("3k and says to ask the LPA", "LPA" in _unknown["means"])


# ---- 4. the question actually being asked ---------------------------------
def _f(dataset, on_site=True, name="X"):
    return P.describe({"dataset": dataset, "name": name, "entity": 0},
                      on_site=on_site)


_pd = P.permitted_development([_f("listed-building")])
check("4a a listed building means consent regardless of PD",
      _pd["status"] == "consent_required", _pd["status"])
check("4b and says PD does not remove that requirement",
      "does not remove that requirement" in _pd["note"])

_pd = P.permitted_development([_f("article-4-direction-area", name="HMO")])
check("4c an Article 4 direction means PD is REMOVED",
      _pd["status"] == "removed", _pd["status"])
check("4d and names the direction so it can be read",
      _pd["blocking"] == ["HMO"], str(_pd["blocking"]))

_pd = P.permitted_development([_f("conservation-area")])
check("4e a conservation area RESTRICTS rather than removes",
      _pd["status"] == "restricted", _pd["status"])

_pd = P.permitted_development([_f("green-belt")])
check("4f green belt restricts too", _pd["status"] == "restricted")

# Nothing found must NOT read as "yes, build it". The register does not hold
# the property's planning history and the GPDO limits still apply.
_pd = P.permitted_development([])
check("4g no designation is 'not restricted', not 'permitted'",
      _pd["status"] == "not_restricted", _pd["status"])
check("4h and says so explicitly",
      "not the same as saying the work IS permitted development"
      in _pd["note"], _pd["note"])
check("4i and points at the GPDO limits it cannot check",
      "GPDO" in _pd["note"] and "planning history" in _pd["note"])

# A designation NEXT DOOR does not remove YOUR permitted development rights.
_pd = P.permitted_development([_f("article-4-direction-area", on_site=False)])
check("4j a neighbour's Article 4 does not remove your PD rights",
      _pd["status"] == "not_restricted", _pd["status"])

# Order of severity: listed beats Article 4 beats conservation area.
_pd = P.permitted_development(
    [_f("conservation-area"), _f("article-4-direction-area"),
     _f("listed-building")])
check("4k the most serious finding leads", _pd["status"] == "consent_required")


# ---- 5. grouping neighbours ----------------------------------------------
# A historic centre returns a hundred listed buildings. The useful fact is
# "you are in the middle of a listed terrace", not their addresses.
_many = [P.describe({"dataset": "listed-building", "name": f"No {i}",
                     "listed-building-grade": "II" if i % 3 else "I",
                     "entity": i}, on_site=False) for i in range(40)]
_grouped = P._group_nearby(_many)
check("5a forty neighbours become one finding", len(_grouped) == 1,
      str(len(_grouped)))
check("5b which says how many", _grouped[0]["count"] == 40)
check("5c and which grades", _grouped[0]["grades"] == ["I", "II"],
      str(_grouped[0].get("grades")))
check("5d and gives examples rather than all forty",
      len(_grouped[0]["examples"]) == P.MAX_NEARBY_LISTED)

_few = _many[:3]
check("5e a handful are left as they are", len(P._group_nearby(_few)) == 3)

# On-site findings are NEVER grouped away — they are the important ones.
_mixed = _many + [_f("conservation-area")]
check("5f an on-site finding survives grouping",
      any(f["on_site"] for f in P._group_nearby(_mixed)))


# ---- 6. a network failure must never read as "no constraints" -------------
# This is the one that would hurt. An empty list from a failed request is
# indistinguishable from a clean site, and a builder would price on it.
def _install(get):
    module = types.ModuleType("requests")
    module.get = get
    sys.modules["requests"] = module


def _boom(*a, **k):
    raise OSError("connection reset")


_install(_boom)
try:
    P.fetch_at_point(52.5, -1.9)
    check("6a a failed request raises rather than returning nothing", False,
          "returned an empty list")
except P.PlanningError as e:
    check("6a a failed request raises rather than returning nothing", True)
    check("6b and explains why silence is not an empty list",
          "assume" in str(e) or "reads as" in str(e), str(e))
finally:
    sys.modules.pop("requests", None)


# ---- 7. end to end, with the register stubbed -----------------------------
class _FakeRegister:
    def __init__(self, at_point, nearby, context=None):
        self.at_point = at_point
        self.nearby = nearby
        self.context = context or []
        self.calls = []

    def get(self, url, params=None, timeout=None):
        params = params or {}
        self.calls.append(params)
        datasets = params.get("dataset") or []
        if "geometry" in params:
            entities = self.nearby
        elif "local-planning-authority" in datasets:
            entities = self.context
        else:
            entities = self.at_point
        return _FakeResponse({"entities": entities})


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


_register = _FakeRegister(
    at_point=[
        {"dataset": "conservation-area", "name": "Bath", "entity": 10},
        {"dataset": "article-4-direction-area", "name": "CITY WIDE HMO",
         "entity": 11},
        {"dataset": "flood-risk-zone", "flood-risk-level": "3",
         "entity": 12},
    ],
    nearby=[
        {"dataset": "listed-building", "name": "THE ABBEY",
         "listed-building-grade": "I", "entity": 20},
        {"dataset": "tree-preservation-zone", "name": "TPO 12", "entity": 21},
    ],
    context=[{"dataset": "local-planning-authority",
              "name": "Bath and North East Somerset LPA", "entity": 30}],
)
_install(_register.get)
try:
    _arts, _extra = P.run({"gps": {"lat": 51.3811, "lon": -2.3590},
                           "scan_id": "t1"}, _Prog(), tempfile.mkdtemp())
    _r = _extra["planning"]

    check("7a the authority is reported so you know who to apply to",
          _r["authority"] == "Bath and North East Somerset LPA",
          str(_r["authority"]))
    check("7b every designation is reported",
          _r["totals"]["constraints"] == 5, str(_r["totals"]))
    check("7c on-site and nearby are counted separately",
          _r["totals"]["on_site"] == 3, str(_r["totals"]))
    check("7d the Article 4 direction drives the headline",
          _r["permitted_development"]["status"] == "removed",
          _r["permitted_development"]["status"])
    # A neighbour's protected tree is NOT a lesser finding: the offence is
    # cutting it whoever owns it, its root protection area crosses the
    # boundary, and NHBC 4.2 sets the foundation depth from the distance to
    # it — which on a terrace is nearly always next door's tree.
    _tpo = [f for f in _r["constraints"]
            if f["dataset"] == "tree-preservation-zone"]
    check("7e a TPO next door is reported", len(_tpo) == 1, str(_tpo))
    check("7e2 and stays critical rather than being downgraded as 'setting'",
          _tpo[0]["severity"] == P.CRITICAL, _tpo[0]["severity"])
    check("7f and it says the foundation depth follows the tree",
          "foundation" in _tpo[0]["means"].lower(), _tpo[0]["means"])
    check("7f2 while a listed building next door IS downgraded to setting",
          all(f["severity"] == P.MAJOR for f in _r["constraints"]
              if f["dataset"] == "listed-building" and not f["on_site"]))
    check("7g a json artifact is written",
          _arts and _arts[0][0].endswith(".json"), str(_arts))
    check("7h the screening warning is always present",
          any("SCREENING CHECK" in w for w in _r["warnings"]),
          str(_r["warnings"]))
    check("7i and says absence is not proof",
          any("not proof" in w for w in _r["warnings"]))
    check("7j the licence is stated", "Open Government" in _r["source"])
    check("7k critical on-site findings are lifted into the warnings",
          any("Flood" in w or "Article 4" in w
              for w in _extra["warnings"]), str(_extra["warnings"])[:200])
finally:
    sys.modules.pop("requests", None)

# A job with nothing to locate must be refused before any request.
try:
    P.run({}, _Prog(), tempfile.mkdtemp())
    check("7l a job with no location is refused", False)
except P.PlanningError as e:
    check("7l a job with no location is refused",
          "address" in str(e) and "postcode" in str(e), str(e))

# Validation must be reachable through the handler, which is the bug that
# made Price Mode unreachable for a fortnight.
import validation  # noqa: E402

check("7m planning is a registered mode", "planning" in validation.MODES)
_spec = validation.parse_job({"mode": "planning", "postcode": "B36 8AR",
                              "search_radius_m": 250})
check("7n and its search radius survives parse_job",
      _spec["search_radius_m"] == 250.0, str(_spec.get("search_radius_m")))
try:
    validation.parse_job({"mode": "planning"})
    check("7o a planning job with no site is refused at the door", False)
except validation.InputError as e:
    check("7o a planning job with no site is refused at the door",
          "address" in str(e), str(e))


# ---- 8. the jurisdiction guard runs on the path the app actually uses -----
# check_coverage passed every test in section 1 while run() never called it
# on an address. `{"mode": "planning", "address": "CF10 1AA"}` — a Cardiff
# postcode, which is exactly the shape the app sends — geocoded to Wales,
# screened against the ENGLISH register, and came back "success" with no
# constraints found. A confident all-clear for a site in a different planning
# jurisdiction is the worst thing this module can emit: it is a builder
# starting work that needed consent.
#
# The guard was `if postcode: check_coverage(postcode)`, and spec["postcode"]
# is only set when the caller fills that field separately. Found by running a
# real job, not by reading — section 1 was green throughout.

for _bad, _nation in [("CF10 1AA", "Wales"), ("EH1 1AA", "Scotland"),
                      ("BT1 1AA", "Northern Ireland")]:
    try:
        P.run({"address": _bad, "scan_id": "t"}, _Prog(), tempfile.mkdtemp())
        check(f"8a {_nation} in `address` is refused, not screened", False,
              "returned a result for a site outside England")
    except P.OutsideCoverageError as e:
        check(f"8a {_nation} in `address` is refused, not screened",
              _nation in str(e), str(e)[:100])

# Refused BEFORE any network call, so it costs nothing and cannot depend on
# the register being up.
try:
    P.run({"postcode": "CF10 1AA", "scan_id": "t"}, _Prog(), tempfile.mkdtemp())
    check("8b the separate postcode field is still screened", False)
except P.OutsideCoverageError:
    check("8b the separate postcode field is still screened", True)

# And it is a no_data answer, not a breakage — the handler completes the job.
check("8c outside coverage reaches the handler as no-data",
      issubclass(P.OutsideCoverageError, validation.NoDataError))

# THE POSTCODE AREA IS A HEURISTIC; THE GEOCODER IS THE ANSWER. Screening on
# the prefix needs a maintained table of which areas are Welsh — it cannot
# know "B" is Birmingham and "BT" is Belfast on its own. postcodes.io states
# the country outright, so a border case or a newly-issued area cannot slip
# through a stale list. This stubs a postcode whose area looks English while
# the geocoder says otherwise.
import roof as _roof
_saved_full = _roof._geocode_uk_full
try:
    _roof._geocode_uk_full = lambda a: {
        "latitude": 51.4791, "longitude": -3.1781, "country": "Wales"}
    try:
        P.run({"address": "ZZ1 1ZZ", "scan_id": "t"}, _Prog(),
              tempfile.mkdtemp())
        check("8d the geocoder overrules a postcode area that looks English",
              False, "screened a Welsh site")
    except P.OutsideCoverageError as e:
        check("8d the geocoder overrules a postcode area that looks English",
              "Wales" in str(e), str(e)[:100])

    # England still goes through.
    _roof._geocode_uk_full = lambda a: {
        "latitude": 52.5014, "longitude": -1.8067, "country": "England"}
    _arts, _extra = P.run({"address": "ZZ1 1ZZ", "scan_id": "t"}, _Prog(),
                          tempfile.mkdtemp())
    check("8e an English site still screens normally",
          "planning" in _extra, str(list(_extra)))
    check("8f an English site is not warned about jurisdiction",
          not any("jurisdiction was NOT confirmed" in w
                  for w in _extra["warnings"]))
finally:
    _roof._geocode_uk_full = _saved_full

# Raw coordinates carry no country, so nothing can confirm the site is in
# England. Screening silently would let an all-clear stand for a Welsh site,
# so the gap is stated instead of hidden. A reverse geocode is the proper
# fix; this is the honest interim and the warning says which check did not
# run.
_arts, _extra = P.run({"gps": {"lat": 51.4791, "lon": -3.1781},
                       "scan_id": "t"}, _Prog(), tempfile.mkdtemp())
check("8g a gps-only screen says the jurisdiction was not confirmed",
      any("jurisdiction was NOT confirmed" in w for w in _extra["warnings"]),
      str(_extra["warnings"])[:160])
check("8h and that warning comes first, ahead of the standard caveat",
      "jurisdiction was NOT confirmed" in _extra["warnings"][0],
      _extra["warnings"][0][:90])


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
