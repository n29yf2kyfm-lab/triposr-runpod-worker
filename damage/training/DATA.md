# Where the data lives

Nothing in this directory ships the data itself — the corpus is ~22 GB and
carries licences that forbid redistribution. Both archives are **private repos
on the `Alamj` HuggingFace account**; log in at huggingface.co and they appear
under Datasets and Models.

| | |
|---|---|
| Corpus, indexes, audit record | `https://huggingface.co/datasets/Alamj/damage-corpus` |
| Trained models and training logs | `https://huggingface.co/Alamj/damage-detector` |

The dataset repo's own README is the map: every folder, its size, what it is
for, and copy-paste download commands. Start there.

## Keep both repos private

The corpus contains CarDD (non-commercial research only, and not the copyright
holder of its own Flickr/Shutterstock source images), stock photographs carrying
Shutterstock / Getty / Dreamstime / Alamy credit bars, and Roboflow projects of
unknown provenance. Private storage is backup; publishing would redistribute
other people's copyrighted work. The licence section at the top of `README.md`
in this directory explains why that matters commercially as well as legally.

## The short version

```bash
pip install -U "huggingface_hub[cli]"
hf auth login

# the index and the audit record -- ~250 MB, usually all you need
hf download Alamj/damage-corpus --repo-type dataset --local-dir ./damage-corpus \
    --include "idx/*" "meta/*"

# the external test set -- the only honest accuracy number
hf download Alamj/damage-corpus --repo-type dataset --local-dir . \
    --include "raw/ecc.tar.gz" && tar xzf raw/ecc.tar.gz

# the images -- 16.3 GB in ~30 tars
hf download Alamj/damage-corpus --repo-type dataset --local-dir . --include "shards/*"
mkdir -p merged640 && for t in shards/images_*.tar; do tar xf "$t" -C merged640; done

# the best model so far (v12-clone)
hf download Alamj/damage-detector --local-dir . \
    --include "detector/v12-clone/*"
python3 eval_external.py --model detector/v12-clone/rfdetr-base.onnx \
    --root ecc/ECC_Car_Damage_Test_Set_1000_compact_part_*_of_3
```

## What to read first

`meta/audit/project_verdicts.md` in the dataset repo. It is the written record
of every cleaning decision and, more usefully, of the ones that turned out to be
wrong — including the finding that the cleaned index produces a *worse* model on
external data than the older, dirtier corpus did.
