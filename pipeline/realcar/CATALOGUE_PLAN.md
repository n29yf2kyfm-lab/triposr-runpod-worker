# Parts catalogue in Supabase: the plan

Waiting on the owner's Supabase project. Nothing is uploaded until its keys are in the
environment (below).

## What goes in

From the owner's MASTER OEM catalogue (kept out of git: this repository is public), one row
for each part on each car:

| column | from |
|---|---|
| `make` | Brand |
| `model` | Model (its years are in the name, e.g. "(2012-2015)") |
| `oem_number` | OEM Number |
| `part_name` | Part Name |
| `car_image` | the car's picture (below) |

Part 1 has 1,541,661 rows. They are the same part listed once for each year, engine and trim.
Kept once for each make, model and OEM number, that leaves 320,396 rows: 111,075 OEM numbers
on 1,480 models of 35 makes. That is roughly 100 MB with its indexes, inside Supabase's free
500 MB database. Part 2 (`master_oem_2.zip` in the Drive folder) is still empty and is added
when it is uploaded again.

## Tables

- `cars`: `id`, `make`, `model`, `car_image` (address in Supabase Storage),
  `image_credit` (author, licence, source page).
- `parts`: `id`, `car_id` (references `cars`), `make`, `model`, `oem_number`, `part_name`.
  - Unique on `car_id` and `oem_number`.
  - Indexed on `oem_number`, on make and model, and on `part_name` for word search.
- Row-level security on both tables: anyone may read and nobody may write. Writing uses the
  service key, which never goes in a page.

## Car images

One picture for each model, in a public Supabase Storage bucket `car-images`: about 800 px
wide, about 60 kB each, about 90 MB in all.

- They come from the licensed photos the 1,000-vehicle run already found, and for the
  other models from Wikimedia Commons.
- Each photo is stored with its author and licence, which most photos require to be shown.
- The catalogue's own picture links are part diagrams on a third-party site. They are not
  copied.
- A model with no licensed photo found is left blank.

## Upload

Over HTTPS, through Supabase's REST API:

- 1,000 rows a request, about 320 requests: a few minutes.
- The images go to Storage the same way.

Then a check: row counts match, and 20 OEM numbers picked at random read back right.

## Keys: in the environment's settings, never in the chat

Set these in the cloud environment's settings, as environment variables or network secrets:

- `SUPABASE_URL`: the project's address, `https://<project>.supabase.co`.
- `SUPABASE_SERVICE_ROLE_KEY`: writes the rows and images.
- `SUPABASE_ACCESS_TOKEN`: a personal access token, so the tables can be made here. This one is
  optional. Without it, the owner pastes one SQL script into Supabase's SQL editor.

A new session picks them up. In it, the Drive catalogue is fetched again, and the loader runs.

## Steps, once the keys are in

1. Make the tables and the bucket (with the access token, or the owner runs the SQL script).
2. Read the catalogue zip and collapse it to one row for each make, model and OEM number.
3. Gather and shrink one licensed picture for each model, and upload the pictures.
4. Upload `cars`, then `parts`.
5. Check the counts and the random sample, and report what is in and which models have no
   picture.
