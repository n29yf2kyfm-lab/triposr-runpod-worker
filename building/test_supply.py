"""Tests for Supply mode — importing a real merchant price list.

The parsing is not the risky part. The risky parts are VAT, pack sizes and
unit conversion, because each of them fails SILENTLY and produces a price
list that looks complete and is wrong by 20%, or by a factor of three, or by
whatever the coverage rate happened to be. These tests are mostly about
those three.

Run: python building/test_supply.py
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import prices  # noqa: E402
import supply as S  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


TODAY = date(2026, 8, 1)


# ---- 1. column detection --------------------------------------------------
# Merchant exports use whatever their export tool felt like that day.
c = S.detect_columns(["Product Code", "Description", "Unit", "Price"])
check("1a description found", c["description"] == 1, str(c))
check("1b price found", c["price"] == 3, str(c))
check("1c sku found", c["sku"] == 0, str(c))
check("1d unit found", c["unit"] == 2, str(c))

# "Unit Price" must be read as the price, not as the unit.
c = S.detect_columns(["Item Name", "Unit Price"])
check("1e 'Unit Price' is a price, not a unit", c.get("price") == 1, str(c))
check("1f and does not also claim the unit slot", c.get("unit") is None,
      str(c))

c = S.detect_columns(["SKU", "Product Description", "Pack Size",
                      "Trade Price", "Supplier"])
check("1g realistic trade header maps fully",
      {"sku", "description", "unit", "price", "supplier"} <= set(c), str(c))

check("1h nothing usable is reported as nothing",
      "price" not in S.detect_columns(["colour", "weight"]))


# ---- 2. money -------------------------------------------------------------
for text, want in [("£12.50", 12.50), ("12.50", 12.50), ("1,234.56", 1234.56),
                   ("£12.50 ea", 12.50), ("12.50 ex VAT", 12.50),
                   ("GBP 4.99", 4.99), ("  £0.85  ", 0.85)]:
    got = S.parse_money(text)
    check(f"2a parse {text!r}", got is not None and abs(got - want) < 1e-9,
          str(got))

check("2b pence convention", abs(S.parse_money("85p") - 0.85) < 1e-9,
      str(S.parse_money("85p")))
check("2c a number is a number", S.parse_money(9.99) == 9.99)
# A zero in a price column is an export artefact, not a free material.
check("2d zero is treated as missing", S.parse_money("0.00") is None)
check("2e blank is missing", S.parse_money("") is None)
check("2f text is missing", S.parse_money("POA") is None)
check("2g None is missing", S.parse_money(None) is None)


# ---- 3. VAT — the 20% trap ------------------------------------------------
# The single most expensive mistake this module can make. A trade list is
# ex-VAT and a shelf price is inc-VAT; mixing them is a bigger error than the
# entire margin on the job.
check("3a explicit ex-VAT read", S.vat_basis_of("£12.50 ex VAT") == S.VAT_EX)
check("3b '+VAT' read", S.vat_basis_of("12.50 +VAT") == S.VAT_EX)
check("3c 'nett of vat' read", S.vat_basis_of("net of VAT") == S.VAT_EX)
check("3d 'inc VAT' read", S.vat_basis_of("£15.00 inc VAT") == S.VAT_INC)
check("3e 'including VAT' read",
      S.vat_basis_of("price including VAT") == S.VAT_INC)
# SILENCE MUST NOT BE READ AS A BASIS.
check("3f silence stays unknown",
      S.vat_basis_of("12.5mm plasterboard") == S.VAT_UNKNOWN)
check("3g a file-level default can fill silence",
      S.vat_basis_of("plasterboard", default=S.VAT_EX) == S.VAT_EX)

check("3h ex-VAT passes through", S.to_ex_vat(100.0, S.VAT_EX) == 100.0)
check("3i inc-VAT is stripped",
      abs(S.to_ex_vat(120.0, S.VAT_INC) - 100.0) < 1e-9,
      str(S.to_ex_vat(120.0, S.VAT_INC)))
try:
    S.to_ex_vat(100.0, S.VAT_UNKNOWN)
    check("3j unknown VAT refused, never guessed", False)
except S.SupplyError as e:
    check("3j unknown VAT refused, never guessed", "20%" in str(e), str(e))


# ---- 4. pack sizes --------------------------------------------------------
for text, want in [("Plasterboard 12.5mm - pack of 3", 3),
                   ("Screws 5x80mm (200)", 200),
                   ("Batten 25x50 - 10 per pack", 10),
                   ("Tiles, box of 24", 24),
                   ("Membrane roll, pack size: 6", 6),
                   ("Cement per 10", 10),
                   ("Facing brick", 1),
                   ("Single sheet", 1)]:
    got = S.parse_pack(text)
    check(f"4a pack of {text!r} -> {want}", got == want, str(got))

# A five-digit number in brackets is a product code, not a pack.
check("4b a product code is not a pack size",
      S.parse_pack("Gyproc WallBoard (10025)") == 1,
      str(S.parse_pack("Gyproc WallBoard (10025)")))
check("4c 'pack of 1' is not treated as a pack",
      S.parse_pack("Board, pack of 1") == 1)


# ---- 5. units -------------------------------------------------------------
check("5a each", S.normalise_unit("Each") == "each")
check("5b linear metre", S.normalise_unit("Linear Metre") == "m")
check("5c sqm", S.normalise_unit("sq m") == "m2")
check("5d m2 symbol", S.normalise_unit("m²") == "m2")
check("5e tonne", S.normalise_unit("Tonnes") == "tonne")
check("5f sheet", S.normalise_unit("Sheet") == "sheet")
check("5g unreadable is None", S.normalise_unit("widgets") is None)
check("5h empty is None", S.normalise_unit("") is None)


# ---- 5b. dimensions read off the description ------------------------------
# A merchant nearly always states the size, and reading it beats assuming a
# average: a 100mm loft roll and a PIR board differ by about two times.
check("5b-1 metres by metres", abs(S.parse_area_m2("Membrane 1.5m x 50m")
                                   - 75.0) < 1e-9)
check("5b-2 a 1m roll", abs(S.parse_area_m2("Felt 1m x 10m") - 10.0) < 1e-9)
check("5b-3 millimetres by millimetres",
      abs(S.parse_area_m2("Plasterboard 2400x1200") - 2.88) < 1e-9,
      str(S.parse_area_m2("Plasterboard 2400x1200")))
check("5b-4 a thickness is not a size",
      S.parse_area_m2("Mineral Wool Loft Roll 100mm") is None,
      str(S.parse_area_m2("Mineral Wool Loft Roll 100mm")))
check("5b-5 timber section is not a sheet size",
      S.parse_area_m2("C24 Sawn Carcassing 47x200") is None)
check("5b-6 nothing stated is None", S.parse_area_m2("Facing Brick") is None)

# The stated size must WIN over the fallback table.
line = S.Line(description="Bitumen Felt Underlay 1m x 10m", price=22.50,
              unit="Roll", vat=S.VAT_EX)
S.normalise_line(line)
check("5b-7 stated size beats the assumed one",
      abs(line.unit_price_ex_vat - 2.25) < 1e-9, str(line.unit_price_ex_vat))
check("5b-8 and is not flagged, because nothing was guessed",
      not any("check this line" in n for n in line.notes), str(line.notes))

# No stated size: the fallback applies but must announce itself.
line = S.Line(description="Mineral Wool Loft Roll 100mm", price=19.90,
              unit="Roll", vat=S.VAT_EX)
S.normalise_line(line)
check("5b-9 an assumed area is flagged",
      any("check this line" in n for n in line.notes), str(line.notes))
check("5b-10 and says it assumed",
      any("ASSUMED" in n for n in line.notes), str(line.notes))


# ---- 6. product and tier matching -----------------------------------------
p, _ = S.match_product("12.5mm Standard Plasterboard 2400 x 1200mm")
check("6a plasterboard matched", p == "plasterboard", str(p))
p, _ = S.match_product("Treated Roofing Batten 25 x 50mm BS5534")
check("6b batten matched", p == "battens", str(p))
# "tile batten" mentions tiles but IS a batten — the higher-weighted, more
# specific keyword must win.
p, _ = S.match_product("Tile Batten 38x25 treated")
check("6c 'tile batten' is a batten, not a tile", p == "battens", str(p))
p, _ = S.match_product("Natural Welsh Slate 500x250")
check("6d slate matched to roof covering", p == "roof_covering", str(p))
p, _ = S.match_product("Breathable Roofing Membrane 1.5m x 50m")
check("6e membrane matched", p == "membrane", str(p))
p, _ = S.match_product("Deepflow Guttering 4m Black")
check("6f guttering matched", p == "guttering", str(p))

# An unmatched line must stay unmatched rather than land somewhere plausible.
p, score = S.match_product("Kitchen tap chrome mixer")
check("6g unrelated product not matched", p is None, f"{p} score {score}")
p, _ = S.match_product("")
check("6h empty not matched", p is None)

check("6i premium read from spec",
      S.match_tier("Natural Slate handmade") == prices.PREMIUM)
check("6j economy read from spec",
      S.match_tier("Untreated ungraded batten") == prices.ECONOMY)
check("6k no signal defaults to standard",
      S.match_tier("Roofing batten 25x50") == prices.STANDARD)

# Tier is defined per PRODUCT by the catalogue, not by a global word list.
# "Natural slate" is premium as a roof covering and meaningless as a batten;
# "half-round" is the economy gutter while "deepflow" is the standard one.
# A product-blind keyword list gets every one of these wrong.
for description, product, want in [
        ("Concrete Interlocking Roof Tile", "roof_covering", prices.ECONOMY),
        ("Concrete Plain Tile 265x165", "roof_covering", prices.STANDARD),
        ("Natural Welsh Slate 500x250", "roof_covering", prices.PREMIUM),
        ("Half Round Guttering 4m White", "guttering", prices.ECONOMY),
        ("Deepflow Guttering 4m Black", "guttering", prices.STANDARD),
        ("Mineral Wool Loft Roll 100mm", "insulation", prices.ECONOMY),
        ("PIR Insulation Board 50mm 2400x1200", "insulation", prices.STANDARD),
        ("Bitumen Felt Underlay 1m x 10m", "membrane", prices.ECONOMY),
        ("Breathable Roofing Membrane 1.5m x 50m", "membrane",
         prices.STANDARD),
        ("Common Brick 65mm", "bricks", prices.ECONOMY),
        ("Facing Brick 65mm", "bricks", prices.STANDARD),
        ("C16 Sawn Carcassing 47x100", "structural_timber", prices.ECONOMY),
        ("C24 Sawn Carcassing 47x200", "structural_timber", prices.STANDARD),
        ("9.5mm Plasterboard 2400x1200", "plasterboard", prices.ECONOMY),
        ("12.5mm Moisture Resistant Plasterboard", "plasterboard",
         prices.PREMIUM)]:
    got = S.match_tier(description, product)
    check(f"6l {description[:34]} -> {want}", got == want, got)

# THE one that must not invert. "treated" is a substring of "untreated" and
# "graded" of "ungraded", so substring matching reads the economy batten as
# the standard one — backwards, on the item whose economy choice carries a
# BS 5534 failure warning.
check("6m untreated batten is economy, not standard",
      S.match_tier("Untreated batten 25x50 ungraded", "battens")
      == prices.ECONOMY)
check("6n treated graded batten is standard",
      S.match_tier("Treated Roofing Batten 25x50 BS5534 graded", "battens")
      == prices.STANDARD)


# ---- 7. normalising a line end to end -------------------------------------
# A pack of 3 boards at £30 inc-VAT is NOT £30, and NOT £10 either — it is
# £25 ex-VAT for the pack, £8.33 a board, £2.89 a square metre. Every one of
# those steps is a place this can go silently wrong.
line = S.Line(description="Plasterboard 12.5mm 2400x1200 - pack of 3",
              price=30.0, unit="pack", pack=3, vat=S.VAT_INC)
S.normalise_line(line)
check("7a matched", line.product == "plasterboard")
check("7b catalogue unit is m2", line.catalogue_unit == "m2")
expected = (30.0 / 1.2) / 3 / 2.88
check("7c VAT, pack and coverage all applied",
      abs(line.unit_price_ex_vat - expected) < 1e-6,
      f"{line.unit_price_ex_vat} vs {expected}")
check("7d the pack division is disclosed",
      any("pack of 3" in n for n in line.notes), str(line.notes))
check("7e the coverage conversion is disclosed",
      any("m2" in n for n in line.notes), str(line.notes))

# A per-metre item stays per-metre.
line = S.Line(description="Treated Roofing Batten 25x50", price=0.92,
              unit="m", vat=S.VAT_EX)
S.normalise_line(line)
check("7f batten priced per metre unchanged",
      abs(line.unit_price_ex_vat - 0.92) < 1e-9, str(line.unit_price_ex_vat))

# A unit we cannot convert must be FLAGGED, not quietly passed through as if
# the numbers lined up.
line = S.Line(description="Facing brick", price=480.0, unit="tonne",
              vat=S.VAT_EX)
S.normalise_line(line)
check("7g an unconvertible unit is flagged",
      any("check this line" in n for n in line.notes), str(line.notes))

line = S.Line(description="Kitchen tap", price=45.0, vat=S.VAT_EX)
S.normalise_line(line)
check("7h unmatched line carries no price into the catalogue",
      line.product is None and line.unit_price_ex_vat is None)

# "per pack" with NO readable pack count. The price is for the whole pack and
# dividing never happened, so it is several times too high — the single most
# dangerous line a merchant list can contain, because it looks ordinary.
line = S.Line(description="Plasterboard 12.5mm", price=29.55, unit="pack",
              vat=S.VAT_EX)
S.normalise_line(line)
check("7i an unreadable pack size is flagged, not swallowed",
      any("check this line" in n for n in line.notes), str(line.notes))
check("7j and it says the price is for the whole pack",
      any("whole pack" in n for n in line.notes), str(line.notes))

# A sheet good with no unit at all is genuinely ambiguous — per board and per
# square metre differ by about three times.
line = S.Line(description="Plasterboard 12.5mm 2400x1200", price=9.85,
              vat=S.VAT_EX)
S.normalise_line(line)
check("7k an unstated unit on a sheet good is flagged",
      any("check this line" in n for n in line.notes), str(line.notes))

# A per-metre good with no unit is not ambiguous in the same way — it should
# NOT cry wolf, or the flag stops meaning anything.
line = S.Line(description="Treated Roofing Batten 25x50", price=0.92,
              vat=S.VAT_EX)
S.normalise_line(line)
check("7l but an unambiguous missing unit does not cry wolf",
      not any("check this line" in n for n in line.notes), str(line.notes))


# ---- 8. reading a whole list ----------------------------------------------
CSV = """SKU,Description,Unit,Trade Price
PB125,12.5mm Plasterboard 2400x1200,Sheet,9.85
BAT25,Treated Roofing Batten 25x50 BS5534,m,0.92
MEM15,Breathable Roofing Membrane 1.5m x 50m,Roll,68.00
TIL01,Concrete Interlocking Roof Tile,Each,1.32
GUT4,Deepflow Guttering 4m,m,4.20
TAP99,Chrome Kitchen Mixer Tap,Each,45.00
"""

report = S.import_price_list(CSV, vat=S.VAT_EX, channel="trade_account",
                             supplier="Local Merchant", when=TODAY)
check("8a lines read", len(report["lines"]) == 6, str(len(report["lines"])))
check("8b five matched", report["matched"] == 5, str(report["matched"]))
check("8c the tap is skipped", report["skipped"] == 1)
check("8d skips are reported, not hidden",
      any("not matched" in w for w in report["warnings"]),
      str(report["warnings"]))
check("8e trade account is invoice-grade",
      report["source_trust"] == prices.INVOICE)

obs = report["observations"]
check("8f observations built", len(obs) == 5, str(len(obs)))
check("8g supplier carried onto every observation",
      all(o.merchant == "Local Merchant" for o in obs))
board = [o for o in obs if o.product == "plasterboard"][0]
check("8h sheet price converted to m2",
      abs(board.price - 9.85 / 2.88) < 1e-6, str(board.price))

# A file with no VAT statement anywhere must REFUSE.
try:
    S.import_price_list(CSV, channel="trade_account", when=TODAY)
    check("8i a list with no VAT basis is refused", False)
except S.SupplyError as e:
    check("8i a list with no VAT basis is refused", "VAT" in str(e), str(e))

# Marking a retail feed as ex-VAT is legal but suspicious — say so.
report2 = S.import_price_list(CSV, vat=S.VAT_EX, channel="affiliate_feed",
                              when=TODAY)
check("8j an unusual VAT basis for the channel is queried",
      any("usually" in w for w in report2["warnings"]),
      str(report2["warnings"]))

for bad, label in [({"channel": "carrier_pigeon"}, "channel"),
                   ({"vat": "maybe"}, "vat")]:
    try:
        S.import_price_list(CSV, when=TODAY, **bad)
        check(f"8k unknown {label} refused", False)
    except S.SupplyError:
        check(f"8k unknown {label} refused", True)

try:
    S.import_price_list("", vat=S.VAT_EX, when=TODAY)
    check("8l empty list refused", False)
except S.SupplyError as e:
    check("8l empty list refused", "empty" in str(e))

try:
    S.import_price_list("colour,weight\nred,2kg\n", vat=S.VAT_EX, when=TODAY)
    check("8m unreadable header refused", False)
except S.SupplyError as e:
    check("8m unreadable header refused", "description" in str(e), str(e))


# ---- 9. many suppliers ----------------------------------------------------
# The reason for holding more than one merchant.
CHEAP = CSV.replace("0.92", "0.79").replace("9.85", "8.40")
r2 = S.import_price_list(CHEAP, vat=S.VAT_EX, channel="trade_account",
                         supplier="Other Merchant", when=TODAY)
both = report["observations"] + r2["observations"]

cmp = S.compare_suppliers(both, "battens", prices.STANDARD)
check("9a two suppliers compared", cmp is not None)
check("9b cheapest identified", cmp["cheapest"] == "Other Merchant", str(cmp))
check("9c spread reported", cmp["spread_pct"] > 0)
check("9d saving is per unit",
      abs(cmp["saving_per_unit"] - (0.92 - 0.79)) < 1e-6,
      str(cmp["saving_per_unit"]))

# One supplier is a price, not a comparison — do not dress it up as one.
check("9e a single supplier is not a comparison",
      S.compare_suppliers(report["observations"], "battens",
                          prices.STANDARD) is None)


# ---- 10. basket -----------------------------------------------------------
QTY = {"battens": 503.3, "membrane": 158.0, "plasterboard": 96.0}
b = S.basket(QTY, both, tier=prices.STANDARD, today=TODAY)
check("10a lines priced", len(b["lines"]) == 3, str(b["lines"]))
check("10b total is the sum of its lines",
      abs(b["materials_total_ex_vat"]
          - sum(l["total"] for l in b["lines"])) < 0.02)
check("10c total is plausible", 500 < b["materials_total_ex_vat"] < 5000,
      str(b["materials_total_ex_vat"]))
check("10d basket is ex-VAT and says so", "ex-VAT" in b["note"])
check("10e complete basket flagged complete", b["complete"])

# A product with no price must appear as a GAP, never be silently dropped.
gappy = S.basket({"battens": 100.0, "bricks": 5000.0}, both, today=TODAY)
check("10f missing price becomes a visible gap", len(gappy["gaps"]) == 1,
      str(gappy["gaps"]))
check("10g the gap names the product",
      gappy["gaps"][0]["product"] == "bricks")
check("10h an incomplete basket is not marked complete",
      not gappy["complete"])
check("10i quantity is kept on the gap so it can be chased",
      gappy["gaps"][0]["quantity"] == 5000.0)

unknown = S.basket({"unobtainium": 5.0}, both, today=TODAY)
check("10j a product outside the catalogue is a gap, not a crash",
      unknown["gaps"][0]["reason"] == "not in the catalogue")


# ---- 11. handler entry ----------------------------------------------------
class _Prog:
    def stage(self, *a, **k):
        pass


import tempfile  # noqa: E402
OUT = os.path.join(tempfile.gettempdir(), "supply-test")

artifacts, extra = S.run(
    {"price_list_csv": CSV, "vat": "ex", "channel": "trade_account",
     "supplier": "Local Merchant", "quantities": QTY, "scan_id": "t1"},
    _Prog(), OUT)
check("11a an artifact is written", len(artifacts) == 1, str(artifacts))
check("11b the artifact exists on disk", os.path.exists(artifacts[0][0]))
check("11c a basket is returned", "basket" in extra["supply"])
check("11d coverage is reported", "coverage" in extra["supply"])

for bad, phrase in [({}, "price list"),
                    ({"price_list_csv": CSV, "channel": "smoke signal"},
                     "channel"),
                    ({"price_list_csv": CSV, "vat": "probably"}, "vat")]:
    try:
        S.run(bad, _Prog(), OUT)
        check(f"11e refused: {phrase}", False)
    except S.SupplyError as e:
        check(f"11e refused: {phrase}", phrase.split()[0] in str(e), str(e))

# The lesson from CI: validation must come before any network import, so a
# malformed job fails as a SupplyError rather than an ImportError.
try:
    S.run({"price_list_url": "https://example.invalid/x.csv",
           "vat": "nonsense"}, _Prog(), OUT)
    check("11f bad input refused before any network work", False)
except S.SupplyError:
    check("11f bad input refused before any network work", True)
except ImportError as e:
    check("11f bad input refused before any network work", False,
          f"imported before validating: {e}")


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
