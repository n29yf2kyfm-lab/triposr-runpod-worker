"""
Phase 1 — real NHANES 2017-2018 body-composition regressor.

Downloads nothing itself; expects the three public-domain CDC XPT files to be
present in this folder (run_corpus.py / build steps fetch them, or grab them
by hand from wwwn.cdc.gov). Handles both `demo_j.xpt` and `DEMO_J.XPT` casing.

Trains four XGBoost regressors (total / trunk / arm / leg % fat) with 5-fold
cross-validation and writes:
    model_total_pct_fat.json, model_trunk_pct_fat.json,
    model_arm_pct_fat.json,   model_leg_pct_fat.json,
    training_report.json  (real record count + real CV MAE)
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import xgboost as xgb
from sklearn.model_selection import KFold
from sklearn.metrics import mean_absolute_error

# NHANES has arm circumference and upper-leg *length* — but no thigh
# circumference. This feature list is what NHANES actually measures.
FEATURES = ["RIAGENDR", "RIDAGEYR", "BMXWT", "BMXHT",
            "BMXWAIST", "BMXHIP", "BMXARMC", "BMXLEG"]

TARGETS = {
    "total_pct_fat": "DXDTOPF",
    "trunk_pct_fat": "DXDTRPF",
    "arm_pct_fat": "arm_pf",   # mean of left/right arm % fat
    "leg_pct_fat": "leg_pf",   # mean of left/right leg % fat
}


def load(name):
    """Load an XPT file, tolerating upper/lowercase names."""
    for cand in (Path(f"{name.lower()}.xpt"), Path(f"{name.upper()}.XPT"),
                 Path(f"{name}.XPT"), Path(f"{name}.xpt")):
        if cand.exists():
            df, _ = pyreadstat.read_xport(str(cand))
            return df
    raise FileNotFoundError(
        f"Missing CDC file for {name}. Expected e.g. {name.upper()}.XPT in {Path.cwd()}"
    )


def make_model():
    return xgb.XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42,
    )


def main():
    print("[TRAINER] Merging CDC datasets ...")
    demo = load("DEMO_J")[["SEQN", "RIAGENDR", "RIDAGEYR"]]
    bmx = load("BMX_J")[["SEQN", "BMXWT", "BMXHT", "BMXWAIST",
                         "BMXHIP", "BMXARMC", "BMXLEG"]]
    dxx = load("DXX_J")[["SEQN", "DXDTOPF", "DXDTRPF",
                         "DXDLAPF", "DXDRAPF", "DXDLLPF", "DXDRLPF"]]

    df = demo.merge(bmx, on="SEQN").merge(dxx, on="SEQN")
    df = df[df["RIDAGEYR"] >= 18].copy()

    df["arm_pf"] = df[["DXDLAPF", "DXDRAPF"]].mean(axis=1)
    df["leg_pf"] = df[["DXDLLPF", "DXDRLPF"]].mean(axis=1)

    df = df.dropna(subset=FEATURES + list(TARGETS.values()))
    print(f"[TRAINER] Usable adult records: {len(df)}")

    X = df[FEATURES].values
    report = {}

    for label, col in TARGETS.items():
        y = df[col].values
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        maes = []
        for tr, te in kf.split(X):
            m = make_model()
            m.fit(X[tr], y[tr])
            maes.append(mean_absolute_error(y[te], m.predict(X[te])))
        report[label] = round(float(np.mean(maes)), 3)
        print(f"  {label:16s} CV MAE = {report[label]}")

        # Fit final model on all data and save (fixes prior bug where every
        # model file was overwritten with the last target's estimator).
        final = make_model()
        final.fit(X, y)
        final.save_model(f"model_{label}.json")

    with open("training_report.json", "w") as f:
        json.dump({"n_records": int(len(df)), "features": FEATURES,
                   "cv_mae": report}, f, indent=2)

    print("\n[TRAINER] Done. Wrote 4 model files + training_report.json.")


if __name__ == "__main__":
    main()
