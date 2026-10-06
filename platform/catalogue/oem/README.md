# OEM parts catalogue (pilot: VW Golf family)

Our own parts catalogue: real OEM part numbers, where each part sits on the
factory exploded drawing, what it fits, a generated illustration per part
type, and VIN lookup. Built 2026-10-06.

## What is here

| file | what it holds |
|---|---|
| `parts.json` / `parts.csv` | one entry per OEM number: number (exact, e.g. `5Q0 698 151 M`), name, part type, system, US price, availability, every vehicle / category / drawing / callout it appears on, fitment notes, source link, illustration |
| `vehicles.json` | the vehicles crawled: year, make, model, trim, engine, market |
| `pages/<vehicle>/<category>.json` | each crawled dealer page, parsed: its drawings and every part row |
| `illustrations/<type>.webp` | one AI-generated image per part TYPE (all bolts share one) |
| `../vin/vin.py` | VIN → make, country, year, model/platform (+ trim and engine for US VINs) → catalogue parts |
| `../../trainer/data/golf_mk7_assemblies.json` | the Golf workshop manual: 296 exploded drawings, 2,902 parts, 517 tightening torques |

Tools: `parse_revolution.py` (page → parts), `build_catalogue.py` (pages →
parts/vehicles/CSV), `illustrate.py` (part types → images).

`catalogue.html` is the browser page (published as the "Golf Parts Desk"
artifact). It reads `parts.json`, `vehicles.json`, `illustrations/` and
`assemblies.json` (the workshop file, published under that name) from beside
itself. It searches by OEM number or name, filters by car and system,
decodes a VIN offline, and lists the workshop torques. To test it locally,
serve a folder holding those files and open the page.

## Where it comes from, and what that means

- **OEM numbers** are copied from US VW dealer catalogue pages
  (vw.oempartsonline.com, a RevolutionParts site), fetched through Firecrawl
  within the site's robots.txt (AI crawlers allowed on catalogue pages, one
  request per 10 s). A number is never generated or inferred. Where the page
  prints it, it is taken as printed; otherwise it is rebuilt from the part
  link, which drops leading zeros (`4e103623s` → `04E 103 623 S`).
- **US market.** Golf, GTI, Golf R, Jetta, Tiguan and Passat are covered by
  this source; Polo, Leon and Octavia were never sold in the US and need a
  European source. UK cars differ (RHD, engines, trims): a US number is a
  strong lead for a UK car, not a guarantee.
- **Prices** are US dealer prices on the day crawled.
- **Illustrations are AI images of the kind of part**, not photographs of
  the part with that number. Any page showing one must label it.
- **7zap is not used**: it blocks automated access.

## VIN

A VIN gives make and country (positions 1–3), model year (position 10) and,
for VW group cars, the platform (positions 7–8, e.g. `AU` = Golf Mk7). A
European VW VIN does **not** encode trim or engine; a US VIN does, through
NHTSA's free decoder (`--online`). A VIN alone cannot give the exact part for
one car — that needs the maker's build codes — so the catalogue lists parts
that fit the decoded model and year, to be confirmed. VINs are decoded and
dropped, never stored or logged.

## Status

7 vehicles, 1,113 OEM numbers, 100 crawled pages, 0 part links lost:

| car | generation (US) | categories |
|---|---|---|
| 2019 Golf S 1.4 TSI | Mk7 facelift | 21 |
| 2016 Golf S 1.8 TSI | Mk7 | 21 |
| 2012 Golf 2.5 | Mk6 | 20 |
| 2005 Golf GL 2.0 | Mk4 | 18 |
| 1999 Golf GL 2.0 | Mk4 | 18 |
| 2021 Golf 1.4 TSI | Mk7 facelift | front brakes |
| 2019 Golf Alltrack 1.8 | Mk7 | brakes |

The categories are the same set on every car: brakes, suspension and struts,
steering, engine mounts, filters, air intake, turbo, cooling, water pump,
alternator, starter, ignition, exterior lights, tail lamps, exhaust, A/C
compressor and wipers. 1,106 parts have an illustration. Four part types never
get one (`NO_IMAGE` in `illustrate.py`) because the image model kept drawing
the wrong part; the page shows "No picture yet" for them.

Add pages with `ingest_firecrawl.py <saved Firecrawl results>`, then
`build_catalogue.py`, then `illustrate.py`, and check the new pictures on a
contact sheet before committing them. Firecrawl allows about 10 pages a minute
on this plan. Faster calls are refused.
