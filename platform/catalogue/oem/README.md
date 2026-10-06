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

Pilot: the 2019 Golf S 1.4 TSI (22 categories), front brakes for the
1999, 2005, 2012, 2016 and 2021 Golf, and 2019 Golf Alltrack brakes —
7 vehicles, 27 pages, 389 OEM numbers. Add pages with
`ingest_firecrawl.py <saved Firecrawl results>` then `build_catalogue.py`. Scaling to 1995–2026 needs `FIRECRAWL_API_KEY` in the environment so
the crawl can run as a script at the site's pace (~390 category pages per
vehicle, plus one page per drawing).
