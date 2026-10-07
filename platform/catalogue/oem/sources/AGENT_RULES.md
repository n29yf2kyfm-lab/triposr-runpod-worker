# Rules for every catalogue worker (one worker per brand)

Repo root: `/home/user/triposr-runpod-worker`. Catalogue: `platform/catalogue/oem/`.

## Hard rules
- Write ONLY inside your own folder `platform/catalogue/oem/sources/<brand>/`
  (VW's worker also uses `products/`, which `ingest_products.py` routes to by itself).
  Never edit any `.py` file in `platform/catalogue/oem/`; put helper scripts in
  your folder as `sources/<brand>/tools/*.py`. Never run git. The coordinator commits.
- Fetch dealer and shop sites ONLY with the Firecrawl MCP tools (load with
  ToolSearch `select:mcp__Firecrawl__firecrawl_scrape`). Never use curl, wget or
  python to fetch a dealer or shop site. Never use the stealth or enhanced proxy.
  Never try to get past a bot firewall or CAPTCHA. Honour robots.txt. 7zap is excluded.
- **Firecrawl budget: five workers share about 10 requests a minute.** Make at
  most ONE call at a time and **no more than 2 a minute**. Never make calls in
  parallel. On a 429, stop calling and do other work (parse, write) for a few
  minutes before you retry. Do not request the `links` format on a vehicle or
  category page (it returns hundreds of KB inline). Use `rawHtml` or `markdown`,
  which are saved to a file that you then parse.
- No prices, anywhere. Never store or log a VIN. Never invent a part number,
  model, trim, year, dimension or image. Everything recorded must come from a
  page you fetched, and its URL is kept as the source.
- Check `df -h /` every 100 pages. Stop and report if the disk is over 70%. Delete
  every raw Firecrawl file once it is parsed (`ingest_products.py` does this).

## What every brand folder should end up holding
1. `sitemap_parts.txt`: every part-page URL the source lists.
2. `products/<OEM>.json`: one per part page, written by `ingest_products.py
   <dir of saved Firecrawl file>` for oempartsonline.com sites. Other sites need
   your own parser in `tools/` that writes the SAME shape:
   `{oem, number, name, other_names, position, fitment_notes, superseded[],
   category, diagrams[], callout, fits[[year, model, trim, engine]], url}`
   (`year` may be 0 when the source gives a generation, not a year; put the
   generation in `trim`, e.g. "Octavia III (5E)"). The OEM is upper-case, with no
   spaces.
3. `vehicles.json`: **every model, trim and engine for every model year
   1995-2026** that the source lists, as
   `[{"year":2019,"make":"Audi","model":"Q7","trim":"Premium Plus","engine":"3.0L V6 Gas","url":"..."}]`.
   Get it from the source's vehicle sitemap or year/model pages, not from memory.
4. Diagrams: keep the exploded-diagram image URLs and callout numbers that a part
   page gives (`diagrams`, `callout`). Do not download the images.
5. Measurements: keep any dimension the source states (diameter, length,
   thickness, thread, size, capacity), verbatim, in `fitment_notes` or
   `other_names` as the page gives it. Never estimate one.

Work in this order: vehicles.json first (it is cheap, and it shows the coverage),
then part pages through your queue. Interior trim, glass and windscreens, body
panels and engine internals are all in scope. Nothing is skipped by category.

## Report when you stop
Give the counts (vehicles by year, part pages fetched, parsed, gone and
unparsed), any problems, and the exact files you wrote. Keep it short.
