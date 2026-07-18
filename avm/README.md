# BuildScan AI — UK Automated Valuation Model (baseline)

A working hedonic gradient-boosting AVM built entirely on **free, open** data
(HM Land Registry Price Paid, Open Government Licence). This is spec §6.9 / §13:
an automated estimate with a confidence range and its evidence — **not** a
regulated valuation.

## Result (trained on 4.3M sales, 2019–2023, held-out 20% test)

| Metric | Value |
|---|---|
| Median absolute % error | **17.5%** |
| Mean absolute % error | 24.2% |
| Predictions within 10% | 30.7% |
| Predictions within 20% | 55.4% |
| MAE | £83,517 |
| R² (log-price) | 0.757 |

## Read this honestly

17.5% median error is a **legitimate baseline but well short of a commercial
AVM** (those hit ~5–8%). The reason is specific and fixable: **HM Land Registry
records the sale price but not the property size.** This model sees only
location + property type + tenure + sale date — it has no floor area, no bedroom
count. That single missing feature is most of the error.

The fix is the **EPC join**: the EPC register (also open) provides total floor
area and habitable rooms keyed to address/postcode. Joining it typically cuts
median error to roughly 8–12% — the difference between "rough guide" and
"usable estimate." That's the highest-value next step and needs no paid data.

## Files

- `train_avm.py` — load Land Registry, clean, target-encode geography, train
- `predict.py` — point estimate + confidence range + evidence note
- `artifacts/metrics.json` — the metrics above (committed)
- `artifacts/avm_model.joblib` — trained model (git-ignored, regenerate below)

## Run it

```bash
./datasets/download.sh landregistry_2023          # + other years for more data
python3 avm/train_avm.py --data datasets/data --out avm/artifacts
python3 avm/predict.py --postcode "B16 9BL" --type S --duration F --year 2024
```

Example output:
```json
{
  "point_estimate_gbp": 261500.0,
  "likely_range_gbp": [215700.0, 307400.0],
  "confidence_note": "±18% band ... NO floor area (needs EPC join). Automated estimate, not a regulated valuation.",
  "model_r2_logprice": 0.7572
}
```

## Roadmap to production accuracy

1. **EPC join** (open) — floor area + rooms → biggest single accuracy gain.
2. **Comparable evidence** — surface the N nearest recent sales behind each
   estimate (spec §13.9: show every comparable, never one unexplained number).
3. **Condition & after-works adjustment** — feed BuildScan's own scan/defect
   data to model value uplift from proposed works.
4. **Professional-review gateway** — route lending/legal/tax reliance to a
   qualified valuer (spec §13.10).
