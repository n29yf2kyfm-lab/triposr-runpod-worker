"""Supply mode — turn a real merchant price list into usable prices.

prices.py is the engine: given Observations it produces a defensible price
per product and tier. This module is what FEEDS it. It takes a price list in
whatever shape it actually arrived in — a merchant CSV, an affiliate product
feed, a trade account statement, a photographed price sheet run through
OCR — and turns it into Observations that prices.py can reason about.

Nothing here scrapes anything. Sources, best first:

  TRADE ACCOUNT   the user's own negotiated prices, from their own account.
                  The only prices that are actually true for their quotes:
                  trade runs roughly 15-40% under published retail, so a
                  quote built on shelf prices is wrong in the direction that
                  loses the job.
  AFFILIATE FEED  Kingfisher (B&Q), Screwfix and Toolstation publish
                  licensed product feeds through affiliate networks. Real
                  SKUs, EANs and live prices, updated daily, with permission.
  PUBLISHED       list prices a merchant publishes for anyone.

Three traps live in this file, and each of them is worth more than the
parsing code around it:

  VAT      a trade list is ex-VAT and a retail shelf price is inc-VAT. Mixing
           them silently is a 20% error — larger than the whole margin on the
           job. This module refuses to guess.
  PACKS    "plasterboard, pack of 3, £30" is not £30 a board, and it is not
           £30 a square metre either. Comparing a pack price against an each
           price is the most common way a materials list comes out nonsense.
  COVERAGE a tile price per tile only becomes a price per square metre once
           you know the gauge. That conversion is an assumption and is
           labelled as one.

Pure stdlib. Network fetches are lazy and always behind validation.
"""
import csv
import io
import os
import re
from datetime import date

import prices

# --- how the price was obtained -------------------------------------------
# Maps onto prices.SOURCE_TRUST. A trade-account price is an invoice-grade
# fact about what this user pays; a feed is a published list price.
SOURCE_FOR_CHANNEL = {
    "trade_account": prices.INVOICE,
    "invoice": prices.INVOICE,
    "quote": prices.QUOTE,
    "affiliate_feed": prices.PUBLISHED,
    "published": prices.PUBLISHED,
}

CHANNELS = tuple(sorted(SOURCE_FOR_CHANNEL))

# --- VAT ------------------------------------------------------------------
VAT_EX = "ex"
VAT_INC = "inc"
VAT_UNKNOWN = "unknown"
VAT_BASES = (VAT_EX, VAT_INC, VAT_UNKNOWN)

UK_VAT_RATE = 0.20

# Conventions, used only to SUGGEST a basis — never to assume one silently.
CHANNEL_VAT_HINT = {
    "trade_account": VAT_EX,
    "invoice": VAT_EX,
    "quote": VAT_EX,
    "affiliate_feed": VAT_INC,   # consumer-facing feeds quote inc-VAT
    "published": VAT_INC,
}


class SupplyError(ValueError):
    """Raised when a price list cannot be read honestly.

    Deliberately fatal. A half-understood price list is worse than none: it
    produces a quote that looks complete and is quietly 20% out.
    """


# --- column detection ------------------------------------------------------
# Real merchant exports use whatever headers the export tool felt like. These
# are the ones actually seen in the wild, lowercased and stripped of
# punctuation before matching.
COLUMN_PATTERNS = {
    "description": ("description", "product", "productname", "item",
                    "itemname", "itemdescription", "name", "title",
                    "productdescription", "detail"),
    "price": ("price", "unitprice", "netprice", "tradeprice", "cost",
              "unitcost", "net", "each", "priceeach", "amount", "rate",
              "sellprice", "yourprice", "gbp"),
    "sku": ("sku", "code", "productcode", "itemcode", "partno", "partnumber",
            "ref", "reference", "stockcode", "mpn", "ean", "barcode"),
    "unit": ("unit", "uom", "unitofmeasure", "per", "measure", "packsize",
             "pack", "qty", "quantity"),
    "supplier": ("supplier", "merchant", "vendor", "brand", "manufacturer",
                 "stockist"),
}


def _norm_header(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def detect_columns(header):
    """Map a real CSV header row onto the fields we need.

    Returns {field: index}. Matching is exact-first then prefix, because
    "price" must not lose to "priceincludingvat" simply by being shorter,
    and "unit" must not swallow "unitprice".
    """
    normed = [_norm_header(h) for h in header]
    found = {}
    taken = set()

    for field, patterns in COLUMN_PATTERNS.items():
        for pattern in patterns:                      # exact match wins
            for i, h in enumerate(normed):
                if i not in taken and h == pattern:
                    found[field], _ = i, taken.add(i)
                    break
            if field in found:
                break

    for field, patterns in COLUMN_PATTERNS.items():   # then containment
        if field in found:
            continue
        for pattern in patterns:
            for i, h in enumerate(normed):
                if i not in taken and h and pattern in h:
                    found[field], _ = i, taken.add(i)
                    break
            if field in found:
                break

    return found


# --- money -----------------------------------------------------------------
# Grab the whole numeric token INCLUDING its separators, so the decimal
# convention can be worked out from the token rather than guessed at.
_MONEY = re.compile(r"-?\d[\d.,]*\d|-?\d")

# A comma followed by exactly two digits at the end of a number is a decimal
# comma: no UK convention writes "12,50" for twelve pounds fifty, but half of
# Europe does, and reading it as 1250 is a hundredfold error in the direction
# that quietly wrecks a quote.
_DECIMAL_COMMA = re.compile(r",\d{2}$")


def _normalise_decimal(token):
    """Put a numeric token into a form float() reads correctly.

    Merchant exports carry whatever locale the export tool was set to, and
    the two conventions collide exactly where it hurts:

        1,234.56   UK/US   comma groups thousands
        1.234,56   EU      dot groups thousands
        12,50      EU      twelve and a half, NOT one thousand two hundred

    When both separators appear the LAST one is the decimal point, which
    resolves the first two without ambiguity. With only commas, two trailing
    digits mean a decimal comma and anything else means thousands grouping.
    """
    if "." in token and "," in token:
        if token.rfind(",") > token.rfind("."):        # 1.234,56 — European
            return token.replace(".", "").replace(",", ".")
        return token.replace(",", "")                  # 1,234.56 — UK/US
    if "," in token:
        if _DECIMAL_COMMA.search(token):               # 12,50 — European
            return token.replace(",", ".")
        return token.replace(",", "")                  # 1,234 — thousands
    return token


def parse_money(text):
    """Read a price out of a cell. Returns pounds as a float, or None.

    Handles "£12.50", "12.50", "1,234.56", "£12.50 ea", "12.50 ex VAT",
    "GBP 4.99". Refuses anything with no number in it at all, and treats a
    zero as missing — a genuinely free material is not a thing, and a zero in
    a price column is almost always an export artefact.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        value = float(text)
        return value if value > 0 else None

    cleaned = str(text).strip()
    if not cleaned:
        return None
    # Strip a trailing "p" pence convention only when there is no decimal
    # point and no pound sign: "85p" is 0.85, but "£85p" is a typo we ignore.
    pence = bool(re.fullmatch(r"\d+\s*p", cleaned, re.I))

    match = _MONEY.search(cleaned.replace("£", " "))
    if not match:
        return None
    try:
        value = float(_normalise_decimal(match.group(0)))
    except ValueError:
        # A token that is not a readable number at all — "12.50.60" and the
        # like. Refuse it rather than salvaging a prefix, which is how a
        # mangled cell becomes a confident wrong price.
        return None
    if pence:
        value /= 100.0
    return value if value > 0 else None


def vat_basis_of(text, default=VAT_UNKNOWN):
    """Read an explicit VAT statement out of free text.

    Only an EXPLICIT statement counts. Silence means unknown, and unknown
    stays unknown all the way to the caller rather than defaulting to
    whichever basis happens to make the numbers look reasonable.
    """
    if not text:
        return default
    blob = str(text).lower()
    if re.search(r"\b(?:ex|excl|excluding|plus|nett?)\b[\s.]*(?:of\s+)?vat",
                 blob) or \
            "+vat" in blob.replace(" ", "") or "exvat" in blob.replace(" ", ""):
        return VAT_EX
    if re.search(r"\b(inc|incl|including)[\s.]*vat", blob) or \
            "incvat" in blob.replace(" ", "") or "vat inclusive" in blob:
        return VAT_INC
    return default


def to_ex_vat(amount, basis, rate=UK_VAT_RATE):
    """Put a price on a common footing: ex-VAT, always.

    Quotes are built ex-VAT and VAT is applied once at the end (see
    takeoff.py), so a material price carrying VAT inside it would be taxed
    twice. Refuses on an unknown basis rather than picking one.
    """
    if basis == VAT_EX:
        return amount
    if basis == VAT_INC:
        return amount / (1.0 + rate)
    raise SupplyError(
        "cannot use a price without knowing whether it includes VAT. A trade "
        "list is normally ex-VAT and a retail price inc-VAT, and guessing "
        "wrong is a 20% error on every line. Pass vat='ex' or vat='inc' for "
        "this list, or state it in the file.")


# --- pack sizes ------------------------------------------------------------
# Ordered: the first pattern to match wins, so the explicit forms are tried
# before the bare parenthesised number.
_PACK_PATTERNS = (
    re.compile(r"\b(?:pack|box|bag|bundle|case|carton|crate)\s*of\s*(\d+)", re.I),
    re.compile(r"\b(\d+)\s*(?:per\s*)?(?:pack|pk|box|bag|bundle|case)\b", re.I),
    re.compile(r"\bpack\s*(?:size)?\s*[:=]?\s*(\d+)\b", re.I),
    re.compile(r"\bper\s*(\d+)\b", re.I),
    re.compile(r"\((\d{2,4})\)\s*$"),
)


def parse_pack(text):
    """How many sellable units are in one priced item.

    Returns an int >= 1. A pack of 1 is the common case and is not an error;
    what IS an error is treating a pack of 24 as a single unit, which turns a
    materials list into fiction.
    """
    if not text:
        return 1
    blob = str(text)
    for pattern in _PACK_PATTERNS:
        match = pattern.search(blob)
        if match:
            try:
                count = int(match.group(1))
            except ValueError:
                continue
            # A "pack of 1" is meaningless and a five-digit "pack" is a
            # product code that happened to sit in brackets.
            if 1 < count <= 5000:
                return count
    return 1


# --- units -----------------------------------------------------------------
UNIT_ALIASES = {
    "each": ("each", "ea", "unit", "no", "nr", "item", "pc", "pcs", "piece",
             "1", "per each"),
    "m": ("m", "metre", "meter", "metres", "meters", "lm", "linear metre",
          "linearmetre", "lin m", "per m", "mtr"),
    "m2": ("m2", "m²", "sqm", "sq m", "squaremetre", "square metre",
           "sq metre", "persqm", "per m2"),
    "m3": ("m3", "m³", "cubicmetre", "cubic metre", "cu m"),
    "kg": ("kg", "kilo", "kilogram", "kgs"),
    "tonne": ("tonne", "tonnes", "t", "ton", "tons"),
    "litre": ("litre", "litres", "l", "ltr", "liter"),
    "roll": ("roll", "rolls"),
    "sheet": ("sheet", "sheets", "board", "boards"),
    "bag": ("bag", "bags"),
    # A price quoted "per pack" becomes a price per ITEM once the pack count
    # has been divided out, so it resolves to `each` — not to a unit of its
    # own. Getting this wrong is how a pack of three boards gets priced as
    # one board and then converted as if it were already a square metre.
    "each_from_pack": ("pack", "packs", "pk", "box", "boxes", "bundle",
                       "case", "carton"),
}

# Units that only mean anything after the pack count has been divided out.
PACK_UNITS = "each_from_pack"

_ALIAS_TO_UNIT = {alias: unit
                  for unit, aliases in UNIT_ALIASES.items()
                  for alias in aliases}


def normalise_unit(text):
    """Map a merchant's unit string onto our vocabulary. None if unreadable."""
    if not text:
        return None
    key = re.sub(r"[^a-z0-9²³ ]", "", str(text).lower()).strip()
    if key in _ALIAS_TO_UNIT:
        return _ALIAS_TO_UNIT[key]
    for alias, unit in _ALIAS_TO_UNIT.items():
        if re.search(rf"\b{re.escape(alias)}\b", key):
            return unit
    return None


# Fallback sheet and roll sizes, used only when the description does not
# state its own dimensions. These are the common sizes, not the only ones —
# a 100mm mineral wool loft roll covers nearer 5.5 m2 than a PIR board's
# 2.88 — so anything priced off them is flagged rather than trusted.
SHEET_AREAS_M2 = {
    "plasterboard": 2.88,       # 2400 x 1200
    "insulation": 2.88,         # 2400 x 1200 PIR board
    "membrane": 75.0,           # 1.5m x 50m roll
}

# Merchants nearly always state the size, so read it rather than assume it.
# Two conventions, both universal: metres for rolls ("1.5m x 50m") and
# millimetres for boards ("2400x1200").
_DIM_METRES = re.compile(
    r"(\d+(?:\.\d+)?)\s*m\s*[x×]\s*(\d+(?:\.\d+)?)\s*m\b", re.I)
_DIM_MM = re.compile(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b")


def parse_area_m2(description):
    """Area of one sheet or roll, read off the description. None if absent.

    Preferred over the fallback table every time it succeeds: the stated size
    is a fact about the actual product, and the table is an average over
    products that genuinely differ by a factor of two.
    """
    if not description:
        return None
    blob = str(description)

    match = _DIM_METRES.search(blob)
    if match:
        area = float(match.group(1)) * float(match.group(2))
        return area if 0.1 <= area <= 200.0 else None

    match = _DIM_MM.search(blob)
    if match:
        area = (float(match.group(1)) / 1000.0) * (float(match.group(2)) / 1000.0)
        return area if 0.05 <= area <= 20.0 else None

    return None

# Tiles per square metre at typical gauge. These are ASSUMPTIONS — the true
# figure depends on the batten gauge chosen for the actual roof pitch and
# headlap — so anything derived from them is flagged.
TILES_PER_M2 = {
    "concrete_interlocking": 9.7,
    "concrete_plain": 60.0,
    "natural_slate": 21.0,      # 500x250 at 75mm lap
}

COVERAGE_NOTE = (
    "converted from a per-unit price using a typical coverage rate; the true "
    "rate depends on the gauge set for this roof's pitch and headlap")


# --- product matching ------------------------------------------------------
# Scored keyword matching onto prices.CATALOGUE. Deliberately conservative:
# an unmatched line is reported as unmatched rather than filed under a
# plausible-looking key, because a mis-filed price silently corrupts a tier.
PRODUCT_KEYWORDS = {
    "roof_covering": (("roof tile", 6), ("rooftile", 6), ("slate", 5),
                      ("interlocking", 5), ("plain tile", 5), ("ridge", 3),
                      ("pantile", 5), ("tile", 2)),
    "battens": (("batten", 6), ("roofing batten", 8), ("tile batten", 8),
                ("counter batten", 6)),
    "membrane": (("membrane", 6), ("breathable", 5), ("felt", 4),
                 ("underlay", 5), ("breather", 5), ("vapour", 3)),
    "plasterboard": (("plasterboard", 8), ("wallboard", 6),
                     ("gyproc", 6), ("moisture board", 6), ("drylining", 4),
                     ("fireline", 5), ("soundbloc", 5)),
    "insulation": (("insulation", 6), ("pir", 5), ("celotex", 6),
                   ("kingspan", 6), ("rockwool", 6), ("mineral wool", 6),
                   ("phenolic", 6), ("loft roll", 5)),
    "structural_timber": (("c16", 6), ("c24", 6), ("joist", 5), ("cls", 4),
                          ("carcassing", 6), ("sawn timber", 6),
                          ("studwork", 4), ("timber", 2)),
    "bricks": (("brick", 6), ("facing brick", 8), ("common brick", 8),
               ("engineering brick", 7), ("block", 3)),
    "guttering": (("gutter", 6), ("guttering", 7), ("downpipe", 5),
                  ("half round", 5), ("deepflow", 6), ("hopper", 3),
                  ("fascia", 2)),
}

# Tier keywords. Absent any signal a line is STANDARD — the honest default,
# since most of what a merchant stocks in volume is the standard spec.
TIER_KEYWORDS = {
    prices.ECONOMY: ("economy", "budget", "basic", "value", "untreated",
                     "ungraded", "common", "9.5mm", "c16", "standard felt"),
    prices.PREMIUM: ("premium", "heavy duty", "hd ", "natural slate",
                     "handmade", "reclaimed", "aluminium", "cast iron",
                     "phenolic", "engineered", "fire", "moisture", "acoustic",
                     "high performance"),
}

MIN_MATCH_SCORE = 4


def match_product(description):
    """Best (product, score) for a description, or (None, 0).

    Scores are summed over every keyword present, so "roofing batten" beats a
    bare "batten" and a line mentioning both "tile" and "batten" lands on
    battens, which is the correct reading of "tile batten".
    """
    if not description:
        return None, 0
    blob = str(description).lower()
    best, best_score = None, 0
    for product, keywords in PRODUCT_KEYWORDS.items():
        score = sum(weight for word, weight in keywords if word in blob)
        if score > best_score:
            best, best_score = product, score
    if best_score < MIN_MATCH_SCORE:
        return None, best_score
    return best, best_score


# Words that carry no discriminating power between tiers.
_STOPWORDS = {"a", "an", "and", "or", "the", "for", "of", "not", "with",
              "incl", "including", "per", "mm", "weak"}

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.]*")


def _tokens(text):
    """Word tokens, keeping "12.5mm" and "c24" intact.

    Whole tokens, never substrings: "treated" is a substring of "untreated"
    and "graded" of "ungraded", so substring matching reads an economy batten
    as the standard one — precisely backwards, and on the item where the
    economy choice carries a BS 5534 failure warning.
    """
    return {t for t in _TOKEN.findall((text or "").lower())
            if t not in _STOPWORDS and len(t) > 1}


def _spec_tokens(product, tier):
    return _tokens(prices.CATALOGUE[product][tier]["spec"])


def match_tier(description, product=None):
    """Which quality tier a description implies. Defaults to standard.

    Scored against the CATALOGUE's own spec strings for that product, which
    is the only place the tiers are actually defined. A product-blind keyword
    list cannot work here: "natural slate" is premium as a roof covering and
    meaningless as a batten, and "half-round" is the economy gutter while
    "deepflow" is the standard one — none of that generalises across
    products, and a hand-maintained list drifts out of step with the
    catalogue the moment either changes.

    Generic keywords still apply, for the case where the product is unknown.
    """
    blob = (description or "").lower()
    tokens = _tokens(blob)
    scores = dict.fromkeys(prices.TIERS, 0)

    if product in prices.CATALOGUE:
        for tier in prices.TIERS:
            # Weighted above the generic keywords: the catalogue is the
            # definition, the keyword list is a fallback.
            scores[tier] += 2 * len(tokens & _spec_tokens(product, tier))

    for tier in (prices.ECONOMY, prices.PREMIUM):
        scores[tier] += sum(1 for word in TIER_KEYWORDS[tier] if word in blob)

    best = max(scores.values())
    if best == 0:
        return prices.STANDARD
    winners = [t for t in prices.TIERS if scores[t] == best]
    # A tie is not evidence. Standard is the honest default — it is what most
    # of what a merchant stocks in volume actually is.
    return prices.STANDARD if len(winners) > 1 else winners[0]


# --- normalising one line --------------------------------------------------

class Line:
    """One row of a price list, understood.

    Carries how it was understood as well as what it says, because the
    conversions applied here — VAT, pack division, coverage — are exactly
    what someone will want to audit when a quantity looks wrong.
    """

    def __init__(self, description, price, unit=None, sku=None,
                 supplier=None, pack=1, vat=VAT_UNKNOWN, notes=None):
        self.description = description
        self.price = price
        self.unit = unit
        self.sku = sku
        self.supplier = supplier
        self.pack = pack
        self.vat = vat
        self.notes = list(notes or [])
        self.product = None
        self.tier = None
        self.unit_price_ex_vat = None
        self.catalogue_unit = None

    def as_dict(self):
        return {
            "description": self.description, "sku": self.sku,
            "supplier": self.supplier, "product": self.product,
            "tier": self.tier, "pack": self.pack,
            "listed_price": round(self.price, 4) if self.price else None,
            "vat_basis": self.vat,
            "unit_price_ex_vat": (round(self.unit_price_ex_vat, 4)
                                  if self.unit_price_ex_vat else None),
            "unit": self.catalogue_unit,
            "notes": self.notes,
        }


def normalise_line(line, vat_rate=UK_VAT_RATE):
    """Take a raw Line to a per-catalogue-unit, ex-VAT price.

    Order matters and is the whole point: VAT off first, then divide by the
    pack, then convert the unit. Doing the pack division after a coverage
    conversion — or forgetting it — is how a pack of three boards ends up
    priced as one.
    """
    product, score = match_product(line.description)
    if not product:
        line.notes.append(f"no catalogue match (best score {score})")
        return line

    line.product = product
    line.tier = match_tier(line.description, product)

    if line.price is None:
        line.notes.append("no readable price")
        return line

    price = to_ex_vat(line.price, line.vat, vat_rate)      # 1. VAT off

    if line.pack > 1:                                      # 2. per unit
        price /= line.pack
        line.notes.append(f"divided by pack of {line.pack}")

    wanted = prices.CATALOGUE[product]["unit"]             # 3. unit convert
    line.catalogue_unit = wanted
    have = normalise_unit(line.unit) or _unit_from_description(line.description)

    if have == PACK_UNITS:
        # Priced per pack. After step 2 that is a price per item; if no pack
        # count was found, step 2 did nothing and this price is still for the
        # whole pack — silently several times too high.
        if line.pack == 1:
            line.notes.append(
                "priced per pack but the pack size could not be read — this "
                "price is for the whole pack, check this line")
        have = "each"

    price = _convert_unit(price, have, wanted, product, line)
    line.unit_price_ex_vat = price
    return line


def _unit_from_description(description):
    """Last resort: some lists put the unit only in the description."""
    return normalise_unit(description) if description else None


def _convert_unit(price, have, wanted, product, line):
    """Convert a per-`have` price to a per-`wanted` one, or flag it."""
    if have is None or have == wanted:
        if have is None and product in SHEET_AREAS_M2:
            # The high-consequence case. Sheet goods are sold per board and
            # priced per square metre, and the two differ by ~3x, so an
            # unstated unit here is genuinely ambiguous rather than merely
            # untidy. Assume the catalogue unit but say plainly that it is
            # a guess worth checking.
            line.notes.append(
                f"unit not stated and this product is sold both per sheet "
                f"and per {wanted} — assumed per {wanted}, check this line")
        elif have is None:
            line.notes.append(
                f"unit not stated — assumed the catalogue unit ({wanted})")
        return price

    if have in ("sheet", "each", "roll") and wanted == "m2" \
            and product in SHEET_AREAS_M2:
        stated = parse_area_m2(line.description)
        if stated:
            line.notes.append(
                f"per {have} -> per m2 at {round(stated, 3)} m2, read from "
                f"the stated size")
            return price / stated
        area = SHEET_AREAS_M2[product]
        # No stated size: the fallback can be a factor of two out (a loft
        # roll against a PIR board), so this is a guess and must read as one.
        line.notes.append(
            f"per {have} -> per m2 at an ASSUMED {area} m2 — no size given "
            f"in the description, check this line")
        return price / area

    if have == "each" and wanted == "each":
        return price

    line.notes.append(
        f"priced per {have} but the catalogue wants per {wanted} — not "
        f"converted, check this line")
    return price


# --- reading a whole list --------------------------------------------------

def read_csv(text, vat=VAT_UNKNOWN, channel="published", supplier=None):
    """Parse a merchant CSV into Lines.

    `vat` states the basis for the whole file. An explicit statement in a
    row's own text overrides it, since mixed files exist — a trade list with
    a handful of inc-VAT consumer lines is common.
    """
    if channel not in SOURCE_FOR_CHANNEL:
        raise SupplyError(
            f"unknown channel {channel!r}; expected one of "
            f"{', '.join(CHANNELS)}")
    if vat not in VAT_BASES:
        raise SupplyError(f"vat must be one of {', '.join(VAT_BASES)}")

    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        raise SupplyError("price list is empty")

    columns = detect_columns(rows[0])
    if "description" not in columns or "price" not in columns:
        raise SupplyError(
            f"could not find a description and a price column in "
            f"{rows[0]!r}. Recognised headers include "
            f"{', '.join(COLUMN_PATTERNS['description'][:4])} for the item "
            f"and {', '.join(COLUMN_PATTERNS['price'][:4])} for the price.")

    # A header row with a readable price in it is not a header row.
    body = rows[1:] if parse_money(_cell(rows[0], columns["price"])) is None \
        else rows

    out = []
    for row in body:
        description = _cell(row, columns.get("description"))
        if not description:
            continue
        raw_unit = _cell(row, columns.get("unit"))
        blob = f"{description} {raw_unit or ''}"
        out.append(Line(
            description=description.strip(),
            price=parse_money(_cell(row, columns.get("price"))),
            unit=raw_unit,
            sku=_cell(row, columns.get("sku")),
            supplier=_cell(row, columns.get("supplier")) or supplier,
            pack=parse_pack(blob),
            vat=vat_basis_of(blob, default=vat),
        ))
    return out


def _cell(row, index):
    if index is None or index >= len(row):
        return None
    return (row[index] or "").strip() or None


def to_observations(lines, channel="published", when=None):
    """Turn understood Lines into prices.Observation records.

    Lines that did not match a product, or that carry no usable price, are
    returned separately rather than dropped — the gaps in a merchant list are
    information, and silently discarding them makes coverage look better than
    it is.
    """
    if channel not in SOURCE_FOR_CHANNEL:
        raise SupplyError(f"unknown channel {channel!r}")
    source = SOURCE_FOR_CHANNEL[channel]
    when = when or date.today()

    observations, skipped = [], []
    for line in lines:
        if not line.product or line.unit_price_ex_vat is None:
            skipped.append(line)
            continue
        try:
            observations.append(prices.Observation(
                product=line.product, tier=line.tier,
                price=line.unit_price_ex_vat, source=source, observed_on=when,
                merchant=line.supplier, unit=line.catalogue_unit))
        except prices.PriceError as e:
            # The price engine has its own guards — a non-positive price is
            # the one that bites. Let a bad line become a visible skip rather
            # than an exception from another module: this function promises
            # SupplyError, and skipped lines are already surfaced in the
            # report, so one unusable row does not lose the other forty-nine.
            line.notes.append(f"rejected by the price engine: {e}")
            skipped.append(line)
    return observations, skipped


def import_price_list(text, vat=VAT_UNKNOWN, channel="published",
                      supplier=None, when=None, vat_rate=UK_VAT_RATE):
    """The whole path: CSV text in, Observations and a report out."""
    lines = read_csv(text, vat=vat, channel=channel, supplier=supplier)

    unknown_vat = [l for l in lines if l.vat == VAT_UNKNOWN and l.price]
    if unknown_vat:
        raise SupplyError(
            f"{len(unknown_vat)} of {len(lines)} lines do not say whether the "
            f"price includes VAT, and neither does the file. Pass vat='ex' "
            f"for a trade list or vat='inc' for retail prices. Guessing wrong "
            f"is a 20% error on every material in the quote.")

    for line in lines:
        normalise_line(line, vat_rate=vat_rate)

    observations, skipped = to_observations(lines, channel=channel, when=when)

    hint = CHANNEL_VAT_HINT.get(channel)
    warnings = []
    if hint and vat != VAT_UNKNOWN and vat != hint:
        warnings.append(
            f"this list is marked {vat}-VAT but a {channel} list is usually "
            f"{hint}-VAT — worth a second look before quoting from it.")
    if skipped:
        warnings.append(
            f"{len(skipped)} of {len(lines)} lines were not matched to a "
            f"catalogue product and carry no price into the quote.")
    flagged = [l for l in lines if any("check this line" in n for n in l.notes)]
    if flagged:
        warnings.append(
            f"{len(flagged)} of {len(lines)} lines needed a guess about the "
            f"unit, pack size or sheet area, and are only right if the guess "
            f"was. Each one says which guess it made — check them before "
            f"quoting from this list.")

    return {
        "lines": [l.as_dict() for l in lines],
        "observations": observations,
        "matched": len(observations),
        "skipped": len(skipped),
        "channel": channel,
        "source_trust": SOURCE_FOR_CHANNEL[channel],
        "vat_basis": vat,
        "supplier": supplier,
        "warnings": warnings,
    }


def compare_suppliers(observations, product, tier):
    """What each supplier charges for the same thing, cheapest first.

    The point of holding many suppliers rather than one. Returns None when
    only one supplier has the line — a "comparison" of one is a price, not a
    comparison, and dressing it up as the latter is misleading.
    """
    relevant = [o for o in observations
                if o.product == product and o.tier == tier]
    by_supplier = {}
    for observation in relevant:
        name = observation.merchant or "unnamed"
        if name not in by_supplier or observation.price < by_supplier[name].price:
            by_supplier[name] = observation

    if len(by_supplier) < 2:
        return None

    ranked = sorted(by_supplier.values(), key=lambda o: o.price)
    cheapest, dearest = ranked[0], ranked[-1]
    return {
        "product": product,
        "tier": tier,
        "unit": prices.CATALOGUE[product]["unit"],
        "suppliers": [{"supplier": o.merchant or "unnamed",
                       "price": round(o.price, 4)} for o in ranked],
        "cheapest": cheapest.merchant or "unnamed",
        "spread_pct": (round((dearest.price - cheapest.price)
                             / cheapest.price * 100, 1)
                       if cheapest.price else None),
        "saving_per_unit": round(dearest.price - cheapest.price, 4),
    }


def basket(quantities, observations, tier=prices.STANDARD, today=None):
    """Price a set of quantities against the imported prices.

    Quantities come from the scan (roof mode) or a takeoff. Anything without
    a price is listed as a gap rather than assumed — an incomplete basket the
    user can see is useful, and one that quietly omits lines is not.
    """
    out, gaps, total = [], [], 0.0
    for product, quantity in sorted(quantities.items()):
        # Roof mode reports every element it measures, so a plain gable comes
        # through with hip_m: 0 and valley_m: 0. An element that is not there
        # is not a basket line, and pricing it at £0 would put an item on a
        # materials list that nobody needs to buy.
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            continue
        if product not in prices.CATALOGUE:
            gaps.append({"product": product, "reason": "not in the catalogue"})
            continue
        estimate = prices.estimate(observations, product, tier, today=today)
        # estimate() reports "no usable price" rather than raising, so an
        # absent price is a normal outcome that must become a visible gap.
        if estimate.get("price") is None:
            gaps.append({"product": product, "quantity": quantity,
                         "reason": estimate.get("message", "no usable price")})
            continue
        cost = estimate["price"] * quantity
        total += cost
        out.append({
            "product": product, "tier": tier, "quantity": quantity,
            "unit": estimate["unit"], "unit_price": estimate["price"],
            "total": round(cost, 2), "confidence": estimate["confidence"],
            "spec": estimate.get("spec"),
            "warning": estimate.get("warning"),
        })

    return {
        "tier": tier,
        "lines": out,
        "gaps": gaps,
        "materials_total_ex_vat": round(total, 2),
        "currency": "GBP",
        "complete": not gaps,
        "note": "Materials only, ex-VAT. Labour, prelims, margin and VAT are "
                "applied by price mode.",
    }


# --- handler entry point ---------------------------------------------------

def run(spec, prog, output_dir):
    """Supply mode entry point.

    Accepts a price list inline (`price_list_csv`) or by URL
    (`price_list_url`). The URL path is fetched lazily and only after the
    input has been validated, so a malformed job fails as a SupplyError the
    caller can act on rather than an import error from the HTTP library.
    """
    import json

    prog.stage("fetching")
    text = spec.get("price_list_csv")
    url = spec.get("price_list_url")
    if not text and not url:
        raise SupplyError(
            "supply mode needs a price list: pass price_list_csv inline, or "
            "price_list_url pointing at a CSV export from your merchant "
            "account or an affiliate product feed.")

    channel = spec.get("channel", "published")
    vat = spec.get("vat", VAT_UNKNOWN)
    if channel not in SOURCE_FOR_CHANNEL:
        raise SupplyError(f"unknown channel {channel!r}; expected one of "
                          f"{', '.join(CHANNELS)}")
    if vat not in VAT_BASES:
        raise SupplyError(f"vat must be one of {', '.join(VAT_BASES)}")

    if not text:
        if os.path.exists(url):
            with open(url) as f:
                text = f.read()
        else:
            import requests
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            text = response.text

    prog.stage("matching_products")
    report = import_price_list(text, vat=vat, channel=channel,
                               supplier=spec.get("supplier"))
    observations = report.pop("observations")

    prog.stage("quoting")
    quantities = spec.get("quantities") or {}
    if quantities:
        report["basket"] = basket(quantities, observations,
                                  tier=spec.get("tier", prices.STANDARD))
    report["comparisons"] = [
        c for c in (compare_suppliers(observations, p, t)
                    for p in prices.CATALOGUE for t in prices.TIERS)
        if c]
    report["coverage"] = prices.coverage(observations)

    prog.stage("exporting")
    os.makedirs(output_dir, exist_ok=True)
    scan = spec.get("scan_id") or "supply"
    path = os.path.join(output_dir, f"supply_{scan}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)

    return ([(path, f"supply/{scan}.json", None)],
            {"supply": report, "warnings": report["warnings"]})
