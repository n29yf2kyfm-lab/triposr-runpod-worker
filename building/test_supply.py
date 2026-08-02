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

# THE hundredfold error. Merchant exports carry whatever locale the export
# tool was set to, and the two conventions collide exactly where it hurts:
# no UK convention writes "12,50" for twelve pounds fifty, but half of Europe
# does, and reading it as 1250 poisons every line in the file while looking
# entirely ordinary.
for text, want in [("£12,50", 12.50),        # European decimal comma
                   ("1.234,56", 1234.56),    # European thousands + decimal
                   ("1,234.56", 1234.56),    # UK/US thousands + decimal
                   ("1,234", 1234.0),        # UK thousands grouping
                   ("2.999,99", 2999.99),
                   ("0,85", 0.85)]:
    got = S.parse_money(text)
    check(f"2b2 {text!r} -> {want}",
          got is not None and abs(got - want) < 1e-9, str(got))

# When both separators appear the LAST one is the decimal point; that
# resolves the ambiguity without guessing.
check("2b3 the last separator decides",
      S.parse_money("1.234,56") == S.parse_money("1,234.56"))

# A token that is not a readable number must be refused, not salvaged for a
# prefix — that is how a mangled cell becomes a confident wrong price.
check("2b4 a mangled number is refused", S.parse_money("12.50.60") is None,
      str(S.parse_money("12.50.60")))
check("2b5 a negative is still refused", S.parse_money("-12.50") is None)
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

# A line the PRICE ENGINE rejects must become a visible skip, not an
# exception from another module. to_observations promises SupplyError, and
# one unusable row must not lose the other forty-nine.
_bad = S.Line(description="Facing brick", price=-5.0, unit="each",
              vat=S.VAT_EX)
S.normalise_line(_bad)
try:
    _o, _s = S.to_observations([_bad], channel="trade_account", when=TODAY)
    check("8f2 a price the engine rejects is skipped, not raised",
          len(_o) == 0 and len(_s) == 1, f"{len(_o)}/{len(_s)}")
    # A reason must be recorded, whichever gate caught it. The plausibility
    # band now catches a negative brick price before the engine sees it —
    # defence in depth, and a clearer message — so this asserts that SOME
    # gate explained itself rather than naming one of them.
    check("8f3 and the reason is recorded on the line",
          any("price engine" in n or "plausibly cost" in n
              for n in _s[0].notes), str(_s[0].notes))
except prices.PriceError as e:
    check("8f2 a price the engine rejects is skipped, not raised", False,
          f"PriceError escaped: {e}")
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

# Roof mode reports every element it measures, so a plain gable arrives with
# hip_m: 0 and valley_m: 0. An element that is not there is not a basket line
# — pricing it at £0 puts an item on a materials list nobody needs to buy.
zeroed = S.basket({"battens": 100.0, "hip_m": 0, "valley_m": 0}, both,
                  today=TODAY)
check("10k zero-length elements produce no basket line",
      len(zeroed["lines"]) == 1, str(zeroed["lines"]))
check("10l and are not reported as gaps either", not zeroed["gaps"],
      str(zeroed["gaps"]))
check("10m so the basket still reads complete", zeroed["complete"])

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


# ---- Test 12: money forms that produced confident wrong prices -----------
# Every one of these was live while all 150 tests above passed. They are
# grouped here because they share a cause: a numeric token was salvaged out
# of a cell the parser did not actually understand.

# ".50" is a routine Excel rendering of fifty pence. The old pattern required
# a leading digit, skipped the dot and read £50.00 — a 100x overprice. On a
# 1,000-tile roof that is £50,000 of tiles instead of £500.
check("12a a leading decimal point is fifty pence, not fifty pounds",
      S.parse_money(".50") == 0.5, str(S.parse_money(".50")))

# Space-grouped thousands: Excel's "# ##0.00" and several European locales.
# The old pattern stopped at the space and read £1.00 out of £1,234.56.
check("12b space-grouped thousands read whole",
      S.parse_money("1 234,56") == 1234.56, str(S.parse_money("1 234,56")))
check("12c space-grouped thousands with a decimal point too",
      S.parse_money("1 234.56") == 1234.56, str(S.parse_money("1 234.56")))

# Refusals. The module's stated policy is that a cell it cannot read is
# refused rather than salvaged for a prefix, and these were the exceptions.
check("12d scientific notation is a mangled export, not a price",
      S.parse_money("1.5e3") is None, str(S.parse_money("1.5e3")))
check("12e a malformed comma group is refused, not read as thousands",
      S.parse_money("1,2345") is None, str(S.parse_money("1,2345")))
check("12f the original mangled-cell case still refuses",
      S.parse_money("12.50.60") is None)

# Everything that already worked must keep working.
for _text, _want in [("£12.50", 12.5), ("1,234.56", 1234.56),
                     ("1.234,56", 1234.56), ("12,50", 12.5),
                     ("85p", 0.85), ("4.99", 4.99), ("GBP 4.99", 4.99)]:
    check(f"12g {_text!r} still reads as {_want}",
          S.parse_money(_text) == _want, str(S.parse_money(_text)))

# "per 4.8m" is a LENGTH. Read as a pack of 4 it quartered a £28.50 joist to
# £7.13, and the report's warnings list came back empty.
check("12h 'per 4.8m' is a length, not a pack of four",
      S.parse_pack("Timber C24 47x225 per 4.8m") == 1,
      str(S.parse_pack("Timber C24 47x225 per 4.8m")))
check("12i 'per 2.4m' likewise",
      S.parse_pack("C16 studwork per 2.4m") == 1)
check("12j a bracketed board dimension is not a pack of 2400",
      S.parse_pack("Gyproc WallBoard 2400x1200 (2400)") == 1,
      str(S.parse_pack("Gyproc WallBoard 2400x1200 (2400)")))
check("12k a real pack is still read", S.parse_pack("Screws box of 200") == 200)
check("12l 'per 24' with no unit after it is still a pack",
      S.parse_pack("Roof tiles per 24") == 24)
check("12m a bracketed count with no dimension on the line is still a pack",
      S.parse_pack("Galvanised nails (500)") == 500)

# A pack division cuts the price by the pack count, so it has to be visible.
_packed = S.normalise_line(S.Line(
    description="Roof tile pack of 24", price=48.0, unit="pack",
    vat=S.VAT_EX), S.UK_VAT_RATE)
check("12n a pack division carries the phrase the report escalates on",
      any("check this line" in n for n in _packed.notes),
      str(_packed.notes))

# ex-VAT is this module's own spelling throughout its docstrings, and it read
# as unknown. With a file-level vat='inc', a line saying "excludes VAT" was
# divided by 1.2 anyway, putting two identical tiles 16.7% apart.
for _text, _want in [("ex-VAT", S.VAT_EX), ("excludes VAT", S.VAT_EX),
                     ("exclusive of VAT", S.VAT_EX),
                     ("VAT excluded", S.VAT_EX), ("before VAT", S.VAT_EX),
                     ("inc-VAT", S.VAT_INC), ("includes VAT", S.VAT_INC),
                     ("inclusive of VAT", S.VAT_INC),
                     ("VAT included", S.VAT_INC)]:
    check(f"12o {_text!r} reads as {_want}",
          S.vat_basis_of(_text) == _want, S.vat_basis_of(_text))

check("12p silence still means unknown",
      S.vat_basis_of("Roof tile 420x330") == S.VAT_UNKNOWN)
check("12q the forms that already worked still work",
      S.vat_basis_of("ex VAT") == S.VAT_EX
      and S.vat_basis_of("12.50+VAT") == S.VAT_EX
      and S.vat_basis_of("inc vat") == S.VAT_INC)

# An accessory names the product it is for. Filed under that product, its
# price corrupts the tier: £0.0156/m2 for screws against £3.40 for board.
for _acc in ["Drywall screws for plasterboard 38mm box of 200",
             "Plasterboard adhesive bag", "Copper pipe clips 15mm",
             "Jointing tape for plasterboard 90m"]:
    check(f"12r accessory refused: {_acc[:30]!r}",
          S.match_product(_acc)[0] is None, str(S.match_product(_acc)))

# The COVERAGE trap the module docstring has always named, and which nothing
# implemented — TILES_PER_M2 and COVERAGE_NOTE were referenced only by their
# own definitions. A merchant quoting slate by the covered square metre is
# not quoting what the catalogue prices, which is per tile.
for _desc, _per_m2 in [("Natural slate 500x250 roofing", 21.0),
                       ("Concrete interlocking roof tile", 9.7),
                       ("Concrete plain roof tile", 60.0)]:
    _line = S.normalise_line(
        S.Line(description=_desc, price=48.50, unit="m2", vat=S.VAT_EX),
        S.UK_VAT_RATE)
    check(f"12u {_desc[:28]!r} converts per m2 to per tile",
          abs(_line.unit_price_ex_vat - 48.50 / _per_m2) < 1e-6,
          str(_line.unit_price_ex_vat))
    check(f"12v and flags the gauge as an assumption: {_desc[:22]!r}",
          any("ASSUMED" in n and "check this line" in n
              for n in _line.notes), str(_line.notes))

# Interlocking is 9.7 per m2 and plain is 60 — a factor of six. Where the
# description does not say which, nothing is converted.
_vague = S.normalise_line(
    S.Line(description="Roof tile", price=48.50, unit="m2", vat=S.VAT_EX),
    S.UK_VAT_RATE)
check("12w an unidentifiable covering is NOT converted",
      not any("per m2 -> per tile" in n for n in _vague.notes),
      str(_vague.notes))
check("12x and says why, with the numbers",
      any("factor of six" in n for n in _vague.notes), str(_vague.notes))
# And because £48.50 cannot be a per-tile price either, the plausibility
# band stops it reaching the engine at all rather than passing it through.
check("12x2 and the unconverted figure is not filed as a price",
      _vague.unit_price_ex_vat is None, str(_vague.unit_price_ex_vat))

# THE GUARD THAT WAS MISSING, found by importing the government's own DBT
# building-materials tables as a price list. They are an INDEX (2015 = 100),
# not pounds. 29 of 30 lines were correctly refused as unmatched, but
# "Precast concrete: blocks, bricks, tiles and flagstones" matched `bricks`
# and its index value of 173.1 was filed as £173.10 PER BRICK, with no note.
# Every earlier check passed: each asks "is this line well-formed", none
# asked "is this number possible".
_index = S.normalise_line(
    S.Line(description="Cement and concrete - Precast concrete: blocks, "
                       "bricks, tiles and flagstones",
           price=173.1, unit="each", vat=S.VAT_EX), S.UK_VAT_RATE)
check("12y an index value is not filed as a price",
      _index.unit_price_ex_vat is None, str(_index.unit_price_ex_vat))
check("12z and the line says what it probably was",
      any("index or a rate" in n for n in _index.notes), str(_index.notes))

# Pence read as pounds is the same class of error in the other direction.
_pence = S.normalise_line(
    S.Line(description="Facing brick", price=0.004, unit="each",
           vat=S.VAT_EX), S.UK_VAT_RATE)
check("12z2 an implausibly LOW price is refused too",
      _pence.unit_price_ex_vat is None, str(_pence.unit_price_ex_vat))

# The band must not reject real prices. These are ordinary UK trade figures.
for _desc, _price, _unit in [("Facing brick", 0.62, "each"),
                             ("Handmade facing brick", 3.20, "each"),
                             ("Gyproc plasterboard 12.5mm", 3.40, "m2"),
                             ("Roofing batten 25x50 treated", 0.95, "m"),
                             ("Concrete interlocking roof tile", 1.10, "each"),
                             ("Breathable roofing membrane", 1.80, "m2")]:
    _ok = S.normalise_line(
        S.Line(description=_desc, price=_price, unit=_unit, vat=S.VAT_EX),
        S.UK_VAT_RATE)
    check(f"12z3 a real price passes: {_desc[:26]!r} at £{_price}",
          _ok.unit_price_ex_vat is not None,
          f"refused: {_ok.notes}")

check("12s the real product still matches",
      S.match_product("Gyproc plasterboard 12.5mm 2400x1200")[0]
      == "plasterboard")
check("12t and so does a batten",
      S.match_product("Roofing batten 25x50 treated")[0] == "battens")


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
