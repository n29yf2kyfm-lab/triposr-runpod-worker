# OEM part-number sources per VW Group brand

Checked 2026-10-07 through Firecrawl only (basic proxy, no bot-wall evasion),
about 15 calls in all. Each verdict below rests on a robots.txt that was
actually fetched and on one test scrape, unless the row says otherwise.
Nothing was bulk-crawled. Prices on these sites are not to be kept.

## Usable

| brand / range | source | covers | robots.txt (quoted) | Firecrawl test | part / sitemap URLs |
|---|---|---|---|---|---|
| Porsche | porsche.oempartsonline.com (US dealer, RevolutionParts, same platform as vw.oempartsonline.com) | US-market Porsche: 911, Cayenne, Macan, Panamera, Taycan, Boxster/Cayman… Full schema.org fitment (year, model, trim, engine), diagrams, callouts | AI crawlers incl. `ClaudeBot`, `anthropic-ai` listed with `Crawl-delay: 10`, `Disallow: /search*`, `/cart*`, `/checkout*`, `/account*`, some `/ajax/...`; `Allow: /` | OK. The .gz sitemaps come back decompressed, and part pages parse with `ingest_products.py` | Index `/sitemap.xml` → `sitemaps/products/products_0002..0019.xml.gz` (no `sitemap_` prefix; `sitemap_products_0001.xml.gz` holds only `/p-` kits). Parts: `/oem-parts/porsche-<name>-<oem>`. 261,761 URLs in `porsche/sitemap_parts.txt` |
| Skoda | www.skoda-parts.com (Czech dealer, online-dily.cz s.r.o.) | Every Skoda model and generation (105/120/130 to Elroq, Octavia 1-4, Superb 1-4, Fabia 1-4, Kodiaq 1-2…). Each part lists its VW Group OEM number (e.g. `6C0 698 151 B`) and the Skoda models it fits, BY GENERATION (not by year or engine). Many listings hold several offers, genuine and aftermarket (ATE, Zimmermann, TRW…), under one OEM number. Keep the number and fitment, never the brand offers or prices | `User-agent: *` / `Disallow:` (empty, i.e. everything allowed) / `Sitemap: http://www.skoda-parts.com/sitemap.xml` | OK. `catalog/octavia/spare-parts/brake-system-11.html` returned 20 parts per page (179 in that category) with number and fitment in the markdown | Category: `/catalog/<model>/spare-parts/<group>-<id>.html?strana=N`. Part: `/spare-part/<oem-lowercase>-<name>-<brand>-<id>.html`. **The OEM is the FIRST slug field, not the last**, so `next_brand.py` / `ingest_products.py` would mis-key it: it needs its own parser. Sitemap `/sitemap.xml` not yet fetched |
| VW Commercial (Transporter, Crafter, Amarok, Caddy, LT), EU-only VW (Polo, Scirocco, Up, Touran, Sharan, T-Roc, T-Cross, Arteon, Lupo, Fox), SEAT, Cupra, Skoda | www.vag247.com (Polish genuine-parts shop, Shoper platform) | Genuine VAG parts; the menu has every one of those model lines plus Cupra (Born, Formentor, Leon, Tavascan, Terramar, Raval). **Small**: product ids reach only ~7,800, so it is a spot source, not a catalogue. Fitment is in the product title (e.g. "VW Tiguan, Skoda Superb 5N0831402"), not structured | `Crawl-delay: 1`, `Request-rate: 1/1s`; disallows `/application`, `/environment`, `/libraries`, `/*/fav/add`, `/*/p/comment/add`, `/*/p/mail/recommend`, `/*/p/q`, `/*/reg`, `/*/login`, `/*/basket`, `/*/searchquery`. Product and category pages allowed | Homepage OK (links format). Product page not test-scraped | Product: `/en_US/p/<title-slug-incl-OEM>/<id>`. Category: `/en_US/c/<Name>/<id>` or `/<brand>/<model>`. No sitemap in robots.txt; not looked for |

## Checked and NOT usable

| source | why |
|---|---|
| bentley.oempartsonline.com | Does not exist (DNS resolution failed). `lamborghini.` was not tried after that |
| partsouq.com | robots.txt allows all (`Disallow: /cdn-cgi/` only) and has a huge product sitemap (`productmap-0-50000.xml` … `-5550000.xml`), BUT its genuine-catalogue index lists no VW Group brand (Toyota, Lexus, Nissan, Infiniti, Mitsubishi, Subaru, Hyundai, Suzuki, Mazda, Honda, Isuzu, Renault, Volvo, Chrysler, Jeep, Dodge, Ram). VW pages exist only as opaque `ssd=` session-token URLs, the catalogue page carries `robots: noindex, nofollow`, and a Cloudflare Turnstile is on the page. Its search results mix aftermarket brands (Stellox, Febi) |
| seat.catalogs-parts.com | robots.txt `Allow: /`, but every model link goes to 7zap.com (excluded), so it is a 7zap front end |
| partslink24 | Login-only official portal. Noted, not used, not fetched |

## Not found within the budget (open)

- **Bentley, Lamborghini**: no RevolutionParts-style dealer catalogue found. A
  web search returned only dealer request-a-part pages (bentleypasadena.com,
  bramanbentley.net, orlandobentley.com) and resellers (bentleyparts.net,
  europarts360.com, masparts.net, scuderiacarparts.com). None of their
  robots.txt files were checked. Many Bentley and Lamborghini parts share VW/Audi
  numbers (e.g. the 0BZ DL801 gearbox), so the vw./audi. sources give partial
  coverage.
- **SEAT / Cupra with full fitment**: only vag247.com (small) was found. Try
  seat-parts style dealer sites next (a skoda-parts.com sibling may exist).
- **parts.vw.com, amayama**: not checked (budget).

## 7zap.com — model generations by market (fetched 2026-10-07)

`sources/7zap/generations.json`: every generation 7zap lists for Volkswagen, Audi,
Skoda, SEAT, Cupra and Porsche, in every market it carries (Global/Europe, USA,
China, South Africa, Mexico, Brazil, Argentina). Fields: make, series, generation,
yearFrom, yearTo, region, type, url. Read from the generation data embedded in each
public brand page (`/en/catalog/cars/<brand>/`), fetched once per brand through the
String web-access connector; robots.txt allows these pages. "Global" (VW, Audi,
SEAT, Cupra) and "Europe" (Skoda, Porsche) are the European catalogues. Audi rows
carry no URL: its brand page does not link generation pages by slug. 7zap's year
ranges run to 2027 for current models. Engines and trims are not on these public
pages; they sit behind the catalogue's parameter picker, which is limited on free
accounts.
