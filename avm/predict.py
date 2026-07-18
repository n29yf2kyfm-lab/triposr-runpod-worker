#!/usr/bin/env python3
"""
BuildScan AI — AVM prediction with confidence range.

Loads the trained model (avm/artifacts/avm_model.joblib) and returns a point
estimate plus a likely range and the evidence behind it — never a single
unexplained number (spec section 13).

Usage:
  python3 avm/predict.py --postcode "B16 9BL" --type S --duration F --year 2024 --month 6
"""
import argparse, json, os
import numpy as np
import pandas as pd
import joblib

CAT_FEATURES = ["property_type", "old_new", "duration", "area"]
TE_FEATURES = ["outward", "town", "district", "county"]
ART = os.path.join(os.path.dirname(__file__), "artifacts")


def predict(prop):
    bundle = joblib.load(os.path.join(ART, "avm_model.joblib"))
    model, encoders, feature_cols = bundle["model"], bundle["encoders"], bundle["feature_cols"]
    metrics = json.load(open(os.path.join(ART, "metrics.json")))
    band = metrics["median_abs_pct_error"] / 100.0  # held-out median error as the ± band

    pc = prop["postcode"].upper().strip()
    row = {
        "property_type": prop.get("type", "S"),
        "old_new": prop.get("old_new", "N"),
        "duration": prop.get("duration", "F"),
        "area": pd.Series([pc]).str.extract(r"^([A-Z]{1,2})").iloc[0, 0],
        "outward": pc.split(" ")[0],
        "town": prop.get("town", np.nan),
        "district": prop.get("district", np.nan),
        "county": prop.get("county", np.nan),
        "year": prop.get("year", 2024),
        "month": prop.get("month", 6),
    }
    X = pd.DataFrame([row])
    for c in CAT_FEATURES:
        X[c] = X[c].astype("category")
    g = encoders["__global__"]
    for col in TE_FEATURES:
        X[col + "_te"] = X[col].map(encoders[col]).astype(float).fillna(g)
    point = float(np.exp(model.predict(X[feature_cols])[0]))

    return {
        "point_estimate_gbp": round(point, -2),
        "likely_range_gbp": [round(point * (1 - band), -2), round(point * (1 + band), -2)],
        "confidence_note": (
            f"±{band*100:.0f}% band = held-out median error of the model. "
            "Location + property type + sale date only; NO floor area (needs EPC join). "
            "Automated estimate, not a regulated valuation."),
        "model_r2_logprice": metrics["r2_logprice"],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--postcode", required=True)
    ap.add_argument("--type", default="S", help="D/S/T/F/O")
    ap.add_argument("--duration", default="F", help="F/L")
    ap.add_argument("--old_new", default="N", help="Y/N")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--month", type=int, default=6)
    a = ap.parse_args()
    out = predict({"postcode": a.postcode, "type": a.type, "duration": a.duration,
                   "old_new": a.old_new, "year": a.year, "month": a.month})
    print(json.dumps(out, indent=2))
