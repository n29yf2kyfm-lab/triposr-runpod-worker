# Visual audit, 60 images, three classes
Read by eye from stratified contact sheets of rows the master chart marked `keep`.
Sample is 20 per class, random within class, seed 101.

## scratch_scuff (38,468 keep)
| verdict | n |
|---|---|
| correct | 6 |
| plausible | 3 |
| wrong class, looks like dent/structural | 8 |
| no damage visible at all | 2 |
| watermarked (alamy) | 1 |

Notable: one image is a person's hands demonstrating on a headlight (a
tutorial/product frame, not an inspection photo); one is a parked Corolla with
no discernible damage.

## dent (29,463 keep)
| verdict | n |
|---|---|
| correct | 3 |
| plausible | 3 |
| wrong class, is structural/total loss | 3 |
| SHIPPING CONTAINERS, not cars | 2 |
| no damage visible | 2 |
| watermarked (shutterstock) | 2 |
| remainder ambiguous under heavy augmentation noise | 5 |

Notable: two shipping containers, one of them a product shot on a white
background. They come from container-damage-ke5bc/dent-detection-4qxiu, a
project about CONTAINER dents that was ingested as if it were cars. Two frames
carry the same shutterstock id (1107699365) and both survived deduplication,
so they are the same photograph counted twice.

## panel_gap (78 keep) -- THE SERIOUS ONE
| verdict | n |
|---|---|
| plausibly a panel gap / shut-line misalignment | 3 |
| major collision damage, not a gap | 14 |
| off-domain news photography | 2 |
| watermarked (alamy) | 5-6 |

Notable: one frame shows soldiers beside a burnt-out pickup; another is an
accident scene with emergency responders attending a crushed car. These are
press photographs, not vehicle inspections.

## The class definition is wrong

class_map documents panel_gap as shut-line misalignment, distinguishing
"realign versus replace". The four source spellings (Misalignment,
Dislocation, Disalocation, separation) do not mean that in practice: the
annotators applied them to panels DISPLACED BY COLLISION. That is structural
damage, and a detector trained on it will learn to fire on wrecks rather than
on a door that sits proud by four millimetres.

v17 is training on this class right now.

## Watermarks are far more common than measured

Visibly watermarked across the 60: 8 or 9, so roughly 15%. The master chart
records 86 watermark scraps across 175,524 images, which is 0.05%. The OCR
detector is therefore missing something like 99% of them in practice, not the
65% its 35%-recall figure implies -- because the heavy augmentation noise on
this corpus is exactly the input tesseract cannot read.

The earlier "about 1% true contamination" estimate was wrong. On this sample
it is nearer 15%, which is consistent with the original 7.3% eyeball estimate
and inconsistent with every OCR-derived number since.
