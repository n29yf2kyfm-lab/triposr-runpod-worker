---
name: car
description: Build a car from one request and show it as a page, in under a minute from the request. Use whenever the user asks for a car in plain words ("make me a Golf 2017 red", "do Peugeot 307 in blue 2001", "/car BMW 3 Series 2019"), with or without a year, colour, doors or trim, or sends one photo of a car to build (a dealer listing, a street photo), with or without words.
---

# One request, one page, under a minute

The user times this from their message to the link. Do exactly these three
steps, in this order, and nothing before the link: no reading files, no
renders, no checks, no thinking aloud about the car.

0. **A photo instead of words** (or with a few): read the car off it, at a
   glance, as one request line, and use that line as the request below:
   - make and model, with the maker's own body name when it is not the
     usual one: `M5 Touring`, `RS6 Avant`, `Octavia Estate`, `308 SW`;
   - the year: one inside the generation it shows (the 2025 M5 Touring's
     grille and lamps: 2025); a UK plate's age figures give it exactly;
   - the colour, and `matt` or `satin` when the paint is not glossy;
   - the wheels' colour when they are not silver alloys: `black wheels`;
   - `right hand drive` when the photo shows a UK plate or the wheel on the
     right.
   The user's own words win over the photo. The photo is a reference only:
   looked at, never saved, passed to the machine or put in the page. In the
   reply, say the line read ("From the photo: BMW M5 Touring 2025 matt dark
   grey black wheels right hand drive") so the user can correct it.

1. **Build** with one Bash call, from the repository root (keep the user's
   words as they typed them, spelling slips and all: the machine reads them):

   ```
   python3 pipeline/realcar/glbmachine.py car <the request, as typed>
   ```

   It prints one JSON answer. A car the machine has rigged before takes about
   5 s; a first build about 10-40 s. (`$GLBMACHINE_HOME` is used if set. The
   first run on a new machine also installs the Node tools: say so if that
   happens.)

2. **If the answer has `error`**: reply in two lines: what went wrong (its
   `error`, `match`) and what the catalogue has instead (`catalogue_has`,
   `nearest`). Stop.

3. **Publish** with the Artifact tool, nothing else first:
   - `file_path`: the answer's `index`
   - `files`: the answer's `files` map, as it is (car1.json … and views.jpg if there)
   - `icon`: `car`
   - `description`: the answer's `summary`

   Then reply: the link, and one line from the answer: `title`, the time to
   the file (`seconds_to_file`), and any `notes` in a few words.

Only after the link, and only if the user asks, look at the car, find faults
or fix the machine.

The four-view check sheet costs about 25 s more: add `--sheet` only when the
user asks for pictures.
