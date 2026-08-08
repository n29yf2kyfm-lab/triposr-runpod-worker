#!/usr/bin/env python3
"""backfill_index.py — make live entries reachable by a DVLA decode.

A car can be published, rendered, colour-verified and serving, and still be
unreachable: `resolveVehicle` gates on make + modelFamily before it scores
anything, so an entry whose modelFamily does not match what the decode sends is
never a candidate at all. Two faults do that, and this fixes both. It touches
metadata only — no GLB, no render, no GPU.

**1. modelFamily that a decode can never produce.**
`publish_batch` builds modelFamily as `f"{make} {model}"`, and several older
waves also wrote the make into `model` itself ("Audi A1", "Honda Civic"). The
vehicle side carries no make prefix, so `slug(asset.modelFamily) === v.modelFamily`
fails, and the aliases — copied from the same make-prefixed string — fail with
it. Measured on the live catalogue: 42 of 677 approved entries could not be
reached by their own bare model name. The repair is additive: append the bare
slug to `modelAliases`. `modelFamilyMatches` tests aliases against both
`v.modelFamily` and `v.model`, so one alias restores the entry without
rewriting the fields anything else may depend on.

**2. A bodyStyle the vehicle side never emits.**
`scoreAsset` compares body styles as raw strings — `v.bodyStyle !== asset.bodyStyle`
— and hard-rejects on a difference. `v.bodyStyle` has already been normalised
through `data/body-style-aliases.json`, so it is always one of that file's ten
canonical values. An asset carrying "sportback", "liftback", "Combi" or "targa"
therefore cannot match; it can only ever reject. 11 live entries were in that
state.

The mapping is not a judgement call and is deliberately not one: a value that is
a KEY in the alias file is replaced by the canonical value that file maps it to
(combi -> estate, sportback -> hatchback). Anything the file does not know
becomes null. Null is strictly safer than a guess — a blank body style cannot
conflict, so the entry stays in the running and merely forgoes the +15, whereas a
wrong value hard-rejects the exact lookup it was meant to serve.

Usage:
    backfill_index.py            # dry run, prints every change
    backfill_index.py --apply    # write platform/catalogue/catalogue.v2.json
"""
import argparse, json, os, re, sys, unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
BSA = os.path.join(REPO, "data", "body-style-aliases.json")


def clean(s):
    """Mirror of clean() in src/lib/vehicle-normalisation.ts."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[._/]+", " ", s)
    s = re.sub(r"[^a-z0-9 -]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def slug(s):
    """Mirror of slug() in src/lib/vehicle-normalisation.ts."""
    return re.sub(r"(^-|-$)", "", re.sub(r"-+", "-", clean(s).replace(" ", "-")))


def bare_cleaned(entry):
    """The model with the make stripped, spaces intact."""
    m = clean(entry.get("model"))
    mk = clean(entry.get("make")).split("-")[0]
    if mk:
        m = re.sub(r"^" + re.escape(mk) + r"\s+", "", m)
    return m


def bare_model(entry):
    """What a DVLA decode would send: the model with the make stripped off."""
    return slug(bare_cleaned(entry))


# Suffixes a source title bolts onto a nameplate. Stripping a KNOWN suffix is
# safe; guessing where a nameplate ends is not. A first-token split turned
# "gt-r" into "gt", "s-max" into "s" and "t-roc" into "t" -- junk aliases on
# cars that were already reachable. Hyphenated names are single nameplates and
# are never split.
SUFFIX = {
    # body / variant
    "estate", "combi", "touring", "tourer", "sw", "avant", "sportback",
    "coupe", "cabriolet", "convertible", "cabrio", "roadster", "spider",
    "saloon", "sedan", "hatchback", "wagon", "cross", "allroad", "scout",
    # trim / performance
    "jcw", "gti", "gtd", "gte", "quattro", "cupra", "classic", "sport",
    "s-line", "r-line", "fr", "vrs", "rs", "gt-line", "st-line", "amg",
    "competition", "performance", "black", "edition", "line", "pack",
    # powertrain
    "hybrid", "phev", "ev", "electric", "tdi", "tsi", "tfsi", "hdi", "crdi",
    "bluemotion", "ecoboost", "mhev", "plug-in",
    # drivetrain
    "all4", "4motion", "xdrive", "quattro", "awd", "4wd", "4x4", "4matic",
}
CHASSIS = re.compile(r"^(?:[a-z]{1,3}\d{1,3}[a-z]?|mk\d+|w\d{3}|\d{4})$")


def _nameplate(cleaned):
    """Drop known trailing suffixes, splitting ONLY on the source title's spaces.

    Takes the cleaned model with its spaces intact, not the slug. Splitting a
    slug on hyphens turned "t-cross" into "t", "s-cross" into "s" and "e-c3"
    into "e" — a hyphen belongs to the nameplate (cx-5, gt-r, f-type, t-roc),
    a space is what separates a nameplate from a suffix.

    Returns the name unchanged when nothing recognised trails it, so an
    unfamiliar nameplate is never mangled into something shorter and wrong.
    """
    out = cleaned.split()
    while len(out) > 1 and (out[-1] in SUFFIX or CHASSIS.match(out[-1])):
        out.pop()
    return slug(" ".join(out))


def reachable(entry, target):
    if slug(entry.get("modelFamily")) == target:
        return True
    return any(slug(a) == target for a in (entry.get("modelAliases") or []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    aliases = json.load(open(BSA))
    canonical = set(aliases.values())

    fixed_alias, fixed_body, cleared_body = [], [], []
    widened, undiscriminated = [], []
    for e in cat:
        if e.get("publicationStatus") != "approved":
            continue

        target = bare_model(e)
        if target and not reachable(e, target):
            e.setdefault("modelAliases", [])
            if target not in e["modelAliases"]:
                e["modelAliases"].append(target)
                fixed_alias.append((e["assetId"], e.get("model"), target))

        # Stripping the make is not always enough. "Skoda Octavia Combi" becomes
        # "octavia-combi", but a decode sends "octavia" with bodyStyle estate, so
        # the entry is still unreachable. Add the nameplate itself -- but ONLY
        # when the entry carries a year range or a body style to be discriminated
        # by. An alias widens what the entry answers to and cannot reject
        # anything, so an undiscriminated entry aliased to a bare nameplate can
        # win a lookup for a completely different generation. "No model" beats
        # "wrong model", so those are left alone and reported instead.
        nameplate = _nameplate(bare_cleaned(e))
        if (nameplate and nameplate != target and not reachable(e, nameplate)
                and (e.get("yearStart") or e.get("bodyStyle"))):
            if nameplate not in e["modelAliases"]:
                e["modelAliases"].append(nameplate)
                widened.append((e["assetId"], e.get("model"), nameplate))
        elif nameplate and nameplate != target and not reachable(e, nameplate):
            undiscriminated.append((e["assetId"], e.get("model"), nameplate))

        bs = e.get("bodyStyle")
        if bs and bs not in canonical:
            mapped = aliases.get(clean(bs))
            if mapped:
                e["bodyStyle"] = mapped
                fixed_body.append((e["assetId"], bs, mapped))
            else:
                e["bodyStyle"] = None
                cleared_body.append((e["assetId"], bs))

    print(f"modelAliases added — {len(fixed_alias)} entries made reachable")
    for aid, model, target in fixed_alias:
        print(f"   {aid:<42} {model!r:<26} + alias {target!r}")
    print(f"\nnameplate alias added (entry has a year or body style to discriminate "
          f"with) — {len(widened)}")
    for aid, model, np_ in widened:
        print(f"   {aid:<42} {model!r:<26} + alias {np_!r}")
    print(f"\nleft alone — nameplate alias would be unsafe, no year and no body "
          f"style to tell it apart — {len(undiscriminated)}")
    for aid, model, np_ in undiscriminated:
        print(f"   {aid:<42} {model!r:<26} would need {np_!r}")
    print(f"\nbodyStyle remapped through the alias file — {len(fixed_body)}")
    for aid, old, new in fixed_body:
        print(f"   {aid:<42} {old!r} -> {new!r}")
    print(f"\nbodyStyle cleared (alias file does not know it) — {len(cleared_body)}")
    for aid, old in cleared_body:
        print(f"   {aid:<42} {old!r} -> null")

    if not a.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)
    print(f"\nwritten to {CAT}")

    # Prove it: every approved entry must now be reachable by its bare model,
    # and no approved entry may carry a body style the vehicle side cannot emit.
    cat = json.load(open(CAT))
    app = [e for e in cat if e.get("publicationStatus") == "approved"]
    bad = [e["assetId"] for e in app if bare_model(e) and not reachable(e, bare_model(e))]
    badbs = [e["assetId"] for e in app
             if e.get("bodyStyle") and e["bodyStyle"] not in canonical]
    print(f"verify: {len(bad)} unreachable, {len(badbs)} non-canonical bodyStyle")
    if bad or badbs:
        print("  ", (bad + badbs)[:6], file=sys.stderr)
        sys.exit(1)
    print("VERIFY PASS — every approved entry is reachable and canonically bodied.")


if __name__ == "__main__":
    main()
