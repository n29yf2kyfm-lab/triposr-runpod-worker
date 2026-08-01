# Getting real prices in

The quote engine is only as good as the prices behind it. This is how to
feed it, in order of how much the numbers can be trusted.

## 1. Your own trade prices — best

Your negotiated account prices are the only ones that are actually true for
your quotes. Trade runs roughly **15–40% under published retail**, so a quote
built on B&Q shelf prices is wrong in the direction that loses you the job.

Send any of these and the importer will read it:

- **A CSV export** from your merchant's trade portal (Travis Perkins, Jewson,
  Selco, Buildbase and MKM all export one).
- **A photo or PDF of a printed price sheet** — OCR it to text first, then it
  goes through the same path.
- **Invoices.** A price you actually paid outranks any list price, and the
  engine weights it accordingly (`prices.INVOICE`, trust 100 vs 40 for a
  published list).

`PRICE_LIST_TEMPLATE.csv` in this directory is the shape that needs no
guessing. You do **not** have to match it — the importer detects columns from
whatever headers your export happens to use. It only genuinely needs a
**description** and a **price**.

### The one thing you must tell it

**Whether the prices include VAT.** A trade list is normally ex-VAT and a
retail price inc-VAT, and getting it wrong is a 20% error on every material
in the quote — bigger than the whole margin on the job. The importer refuses
to guess: pass `vat: "ex"` or `vat: "inc"`, or make sure the file says so.

## 2. Licensed product feeds — for breadth

B&Q (Kingfisher), Screwfix and Toolstation publish product feeds through
affiliate networks such as Awin. Signing up gives a **licensed** feed with
SKUs, EANs, live prices and stock, refreshed daily.

This is better data than scraping and it cannot be cut off without notice.
Scraping merchant catalogues in the UK runs into the *sui generis* database
right, which protects the compiled catalogue itself regardless of whether any
individual price is copyrightable — and the feed gives more fields anyway.

Import with `channel: "affiliate_feed"`, `vat: "inc"` (consumer feeds quote
inc-VAT).

## 3. DBT price indices — for trend and forecast

The Department for Business and Trade publishes **Construction Material Price
Indices** monthly, free, under the Open Government Licence. It does not give
you a price for a specific product, but it tells you which way a material is
moving and by how much — which is what `prices.trend()` and
`prices.forecast()` use to age a quote forward.

Free, official, no key, no scraping: <https://www.gov.uk/government/collections/building-materials-and-components-monthly-statistics>

## What the importer does with it

```
raw line
  → detect columns          description, price, unit, pack, sku, supplier
  → strip VAT               to a common ex-VAT footing
  → divide the pack         "pack of 3" is not one board
  → convert the unit        per sheet → per m² via an assumed sheet area
  → match to the catalogue  8 products x 3 quality tiers
  → Observation             weighted by source trust, decayed by age
```

Order matters. VAT first, pack second, unit last — any other order is wrong.

Anything it cannot do confidently it **says**, rather than guessing:

- a line it cannot match to a catalogue product is reported, not dropped
- a price whose unit it cannot convert is flagged "check this line"
- a "per pack" price with no readable pack count is flagged, because that
  price is still for the whole pack and is several times too high while
  looking completely ordinary
- a basket with a product it has no price for lists the gap instead of
  quietly leaving the line out

## Many suppliers

Import the same catalogue from several merchants and `compare_suppliers()`
ranks them per product and tier, with the spread and the per-unit saving.
With only one supplier it returns nothing — a comparison of one is a price,
and dressing it up as a comparison would be misleading.

## Quality tiers

Every product carries three: **economy / standard / premium**. Tier is about
specification, not just price — choosing economy means accepting a shorter
life or a plainer finish, and the engine says which. Some economy choices
carry an explicit warning: ungraded batten does not meet BS 5534 and is a
common cause of premature roof failure, and the saving is a few pounds a
roof.
