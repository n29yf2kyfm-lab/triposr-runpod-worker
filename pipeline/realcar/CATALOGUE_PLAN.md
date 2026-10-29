# Parts catalogue in Supabase: the plan

Waiting on the owner's Supabase keys. Nothing is uploaded until they are in the environment
(below).

## Where it goes

The owner's Supabase project is `tfkvthprsntexrcuqpyd` (`https://tfkvthprsntexrcuqpyd.supabase.co`).
It already holds a catalogue that another Claude session on the owner's Mac imported from
their Drive (checkpoint 206, 21 October). That catalogue has:

- 271,326 records: Volkswagen, Audi, brakes, AC and more.
- Its own private schema, `catalogue_drive_private`, with the tables `observations`,
  `assets`, `observation_images` and `batches`.
- Its own private bucket, `catalogue-source-captures`.

That work is left alone: nothing here writes to its schema or its bucket.

The MASTER OEM catalogue goes beside it in its own schema, `catalogue_master_oem`, with its
own buckets. The two can then be read together by OEM number; Volkswagen and Audi are in
both. Merging them into one set of tables is the owner's call, made later.

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
| `part_image` | the catalogue's own picture of the part; an AI-made one where it has none (below) |

Part 1 has 1,541,661 rows. They are the same part listed once for each year, engine and trim.
Kept once for each make, model and OEM number, that leaves 321,021 rows: about 111,000 OEM
numbers on 1,480 models of 35 makes. That is roughly 100 MB with its indexes, inside Supabase's free
500 MB database. Part 2 (`master_oem_2.zip` in the Drive folder) is still empty and is added
when it is uploaded again.

## Tables

- `cars`: `id`, `make`, `model`, `car_image` (address in Supabase Storage),
  `image_credit` (author, licence, source page).
- `parts`: `id`, `car_id` (references `cars`), `make`, `model`, `oem_number`, `part_name`, `part_type`
  (references `part_types`).
  - Unique on `car_id` and `oem_number`.
  - Indexed on `oem_number`, on make and model, and on `part_name` for word search.
- `part_types`: `id`, `name` (e.g. "disc brake caliper"), `part_image`.
- Row-level security on every table: anyone may read and nobody may write. Writing uses the
  service key, which never goes in a page.

## Car images

One picture for each model, in a public Supabase Storage bucket `car-images`: about 800 px
wide, about 60 kB each, about 90 MB in all.

- They come from the licensed photos the 1,000-vehicle run already found, and for the
  other models from Wikimedia Commons.
- Each photo is stored with its author and licence, which most photos require to be shown.
- A model with no licensed photo found is left blank.

## Part pictures

### The catalogue's own

The owner says they hold full rights to all the catalogue's pictures (29 October), so they are
used. Each row's own picture is copied into the owner's Supabase Storage (bucket `part-images`),
so the catalogue does not depend on other sites' links.

- 298,147 of the 321,021 rows (93%) have a working picture: 63,119 different pictures on the
  Revolution Parts image servers, about 3 kB each, about 200 MB in all.
- They are fetched one at a time, a few a second: a few hours, in the background.
- Some rows' pictures are on 7zap.com. Those links are dead (404 on every one tried).

### Made by AI, where the catalogue has none

That leaves 22,874 rows (7%), mostly Alfa Romeo and Abarth, under 1,993 part names. They get
one AI picture for each kind of part, not one for each OEM number:

- An AI cannot know what an exact OEM part looks like.
- Each picture is labelled "illustration: the kind of part, not this exact part".

The names are first tidied into kinds of part ("disc brake caliper" and "brake caliper, front"
are one). Then:

1. The most common kinds each get a picture. The commonest are bracket, screw, support,
   solenoid, pipe and clip.
2. Every other kind shows its group's picture (brakes, filters, belts, sensors...), so no row
   is left without one.
3. All pictures use one look: a single part on a plain white background, the same light and
   angle. They are made with Higgsfield (the owner's account), Recraft V4.1 in its "utility"
   mode, which is for clean product shots.
4. Five test pictures come first, to see their look and their price per picture, before any
   batch. The batch size is the owner's call, within their credits.

These go in `part-images` too, about 40 kB each.

## Upload

Over HTTPS, through Supabase's REST API:

- 1,000 rows a request, about 320 requests: a few minutes.
- The part pictures take longer: the few hours to fetch them.
- The images go to Storage the same way.

Then a check: row counts match, and 20 OEM numbers picked at random read back right.

## Keys: in the environment's settings, never in the chat

Set these in the cloud environment's settings, as environment variables or network secrets:

- `SUPABASE_URL`: `https://tfkvthprsntexrcuqpyd.supabase.co`.
- `SUPABASE_SERVICE_ROLE_KEY`: writes the rows and images.
- `SUPABASE_ACCESS_TOKEN`: a personal access token, so the tables can be made here. This one is
  optional. Without it, the owner pastes one SQL script into Supabase's SQL editor.

A new session picks them up. In it, the Drive catalogue is fetched again, and the loader runs.

## Steps, once the keys are in

1. Make the tables and the bucket (with the access token, or the owner runs the SQL script).
2. Read the catalogue zip and collapse it to one row for each make, model and OEM number.
3. Gather and shrink one licensed picture for each model, and upload the pictures.
   Copy the catalogue's part pictures into Storage. Make the AI pictures for the rows with
   none (after the five-picture test) and upload them.
4. Upload `cars`, then `parts`.
5. Check the counts and the random sample, and report what is in and which models have no
   picture.
