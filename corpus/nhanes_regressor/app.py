"""
Real inference API for the NHANES-trained body-composition regressor.

No photos yet (that needs the phase0 RunPod pipeline) — but given manual
measurements it returns genuine model predictions.

Run:
    pip install fastapi "uvicorn[standard]" xgboost numpy
    python train_regressor_final.py     # once, produces model_*.json
    uvicorn app:app --reload --port 8000
"""

from pathlib import Path

import numpy as np
import xgboost as xgb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Corpus Body-Composition Regressor (NHANES-trained)")

# Let the local prototype.html (opened from file:// or localhost) call this.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LABELS = ["total_pct_fat", "trunk_pct_fat", "arm_pct_fat", "leg_pct_fat"]
MODELS = {}


@app.on_event("startup")
def _load_models():
    here = Path(__file__).parent
    for label in LABELS:
        path = here / f"model_{label}.json"
        if not path.exists():
            print(f"[WARN] {path.name} missing — run train_regressor_final.py first.")
            continue
        m = xgb.XGBRegressor()
        m.load_model(str(path))
        MODELS[label] = m
    print(f"[startup] models loaded: {list(MODELS)}")


class Measurements(BaseModel):
    sex: str = Field(..., description="'male' or 'female'")
    age: float
    weight_kg: float
    height_cm: float
    waist_cm: float
    hip_cm: float
    arm_circ_cm: float
    leg_length_cm: float


@app.post("/predict")
def predict(m: Measurements):
    if len(MODELS) < len(LABELS):
        raise HTTPException(503, "Models not loaded. Run train_regressor_final.py.")
    # RIAGENDR: 1 = male, 2 = female
    sex_code = 1 if m.sex.lower().startswith("m") else 2
    X = np.array([[sex_code, m.age, m.weight_kg, m.height_cm,
                   m.waist_cm, m.hip_cm, m.arm_circ_cm, m.leg_length_cm]])
    out = {label: round(float(model.predict(X)[0]), 1) for label, model in MODELS.items()}
    return {
        "body_fat_percent": out["total_pct_fat"],
        "regional_percent_fat": {
            "trunk": out["trunk_pct_fat"],
            "arms": out["arm_pct_fat"],
            "legs": out["leg_pct_fat"],
        },
        "model_mae_reference": "NHANES 2017-2018, 5-fold CV; see training_report.json",
        "note": "Wellness estimate, not a diagnostic measurement.",
    }


@app.get("/health")
def health():
    return {"status": "ok", "models_loaded": list(MODELS)}
