#!/usr/bin/env python3
"""
BuildScan AI — UK Automated Valuation Model (baseline).

Trains a gradient-boosting hedonic model on HM Land Registry Price Paid Data
(Open Government Licence) to estimate residential sale price, and reports the
confidence range the spec requires (never a single unexplained number — §13).

Data: run  ./datasets/download.sh landregistry_2023 (and other years) first,
or point --data at a folder of pp-YYYY.csv files.

Usage:
  python3 avm/train_avm.py --data datasets/data --out avm/artifacts
  python3 avm/train_avm.py --predict '{"postcode":"B16 9BL","property_type":"S",...}'
"""
import argparse, glob, json, os, sys
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

# HM Land Registry Price Paid column order (files have NO header row)
COLS = ["tuid", "price", "date", "postcode", "property_type", "old_new",
        "duration", "paon", "saon", "street", "locality", "town", "district",
        "county", "ppd_category", "record_status"]

# Low-cardinality (<255) → native categorical splits in the GBM.
CAT_FEATURES = ["property_type", "old_new", "duration", "area"]
# High-cardinality geography → smoothed target encoding (mean log-price), fit on
# the training split only to avoid leakage. This is the standard hedonic-model
# way to give the GBM strong location signal without 2000+ one-hot columns.
TE_FEATURES = ["outward", "town", "district", "county"]
NUM_FEATURES = ["year", "month"]
SMOOTHING = 30.0  # shrink small-sample geographies toward the global mean


def load(data_dir):
    files = sorted(glob.glob(os.path.join(data_dir, "pp-*.csv")))
    if not files:
        sys.exit(f"No pp-*.csv in {data_dir}. Run ./datasets/download.sh first.")
    print(f"Loading {len(files)} file(s): {[os.path.basename(f) for f in files]}")
    df = pd.concat(
        (pd.read_csv(f, header=None, names=COLS,
                     usecols=["price", "date", "postcode", "property_type",
                              "old_new", "duration", "town", "district",
                              "county", "ppd_category"],
                     dtype=str) for f in files),
        ignore_index=True)
    print(f"  {len(df):,} raw rows")
    return df


def engineer(df):
    df = df[df["ppd_category"] == "A"].copy()          # standard price-paid only
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df[(df["price"] >= 20_000) & (df["price"] <= 5_000_000)]
    df = df.dropna(subset=["postcode", "price"])
    dt = pd.to_datetime(df["date"], errors="coerce")
    df["year"] = dt.dt.year
    df["month"] = dt.dt.month
    pc = df["postcode"].str.upper().str.strip()
    df["outward"] = pc.str.split(" ").str[0]           # e.g. B16
    df["area"] = pc.str.extract(r"^([A-Z]{1,2})")      # e.g. B
    df = df.dropna(subset=["year", "outward", "area"])
    for c in CAT_FEATURES:
        df[c] = df[c].astype("category")
    df["logprice"] = np.log(df["price"])
    print(f"  {len(df):,} rows after cleaning")
    return df


def fit_target_encoders(Xtr, ytr):
    """Smoothed mean-log-price per geography, computed on the training split."""
    global_mean = ytr.mean()
    encoders = {"__global__": float(global_mean)}
    for col in TE_FEATURES:
        stats = ytr.groupby(Xtr[col], observed=True).agg(["mean", "count"])
        enc = (stats["mean"] * stats["count"] + global_mean * SMOOTHING) / \
              (stats["count"] + SMOOTHING)
        encoders[col] = enc.to_dict()
    return encoders


def apply_target_encoders(X, encoders):
    X = X.copy()
    g = encoders["__global__"]
    for col in TE_FEATURES:
        X[col + "_te"] = X[col].map(encoders[col]).astype(float).fillna(g)
    return X


def train(df, out):
    X = df[CAT_FEATURES + TE_FEATURES + NUM_FEATURES]
    y = df["logprice"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)

    encoders = fit_target_encoders(Xtr, ytr)
    Xtr = apply_target_encoders(Xtr, encoders)
    Xte = apply_target_encoders(Xte, encoders)
    feature_cols = CAT_FEATURES + [c + "_te" for c in TE_FEATURES] + NUM_FEATURES
    Xtr, Xte = Xtr[feature_cols], Xte[feature_cols]

    model = HistGradientBoostingRegressor(
        loss="squared_error", learning_rate=0.1, max_iter=500,
        max_leaf_nodes=255, min_samples_leaf=50, l2_regularization=1.0,
        categorical_features=CAT_FEATURES, random_state=42)
    print("Training HistGradientBoostingRegressor ...")
    model.fit(Xtr, ytr)

    pred = np.exp(model.predict(Xte))
    true = np.exp(yte.values)
    ape = np.abs(pred - true) / true
    metrics = {
        "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
        "median_abs_pct_error": round(float(np.median(ape)) * 100, 2),
        "mean_abs_pct_error": round(float(np.mean(ape)) * 100, 2),
        "within_10pct": round(float((ape <= 0.10).mean()) * 100, 1),
        "within_20pct": round(float((ape <= 0.20).mean()) * 100, 1),
        "mae_gbp": int(mean_absolute_error(true, pred)),
        "r2_logprice": round(float(r2_score(yte, model.predict(Xte))), 4),
    }
    os.makedirs(out, exist_ok=True)
    import joblib
    joblib.dump({"model": model, "encoders": encoders,
                 "feature_cols": feature_cols}, os.path.join(out, "avm_model.joblib"))
    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=2)
    print("\n=== AVM baseline metrics (held-out 20%) ===")
    for k, v in metrics.items():
        print(f"  {k:22} {v}")
    print(f"\nSaved model + metrics to {out}/")
    return model


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="datasets/data")
    ap.add_argument("--out", default="avm/artifacts")
    args = ap.parse_args()
    df = engineer(load(args.data))
    train(df, args.out)
