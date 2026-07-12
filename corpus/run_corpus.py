#!/usr/bin/env python3
"""
Corpus orchestrator — one command to train and serve the real regressor, then
open the prototype in a browser.

    python run_corpus.py

Steps: create a venv → install deps → download the public CDC NHANES files →
train the models if missing → start the FastAPI server → open prototype.html.
Cross-platform (Windows / macOS / Linux).
"""

import os
import sys
import time
import socket
import subprocess
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8000
ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
NHANES_DIR = ROOT / "nhanes_regressor"
HTML = ROOT / "prototype.html"

CDC_URLS = {
    "DEMO_J.XPT": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/DEMO_J.XPT",
    "BMX_J.XPT":  "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/BMX_J.XPT",
    "DXX_J.XPT":  "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/DXX_J.XPT",
}
PACKAGES = ["fastapi", "uvicorn[standard]", "xgboost", "pandas",
            "pyreadstat", "scikit-learn", "numpy"]
MODELS = ["total_pct_fat", "trunk_pct_fat", "arm_pct_fat", "leg_pct_fat"]


def banner(msg):
    print("\n" + "=" * 64 + f"\n [CORPUS] {msg}\n" + "=" * 64)


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def venv_python_pip():
    if not VENV_DIR.exists():
        banner("Creating virtual environment (.venv) ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe", VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "python", VENV_DIR / "bin" / "pip"


def install(pip):
    banner("Installing dependencies ...")
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(pip), "install", *PACKAGES], check=True)


def download_nhanes():
    NHANES_DIR.mkdir(exist_ok=True)
    banner("Checking CDC NHANES 2017-2018 files ...")
    for name, url in CDC_URLS.items():
        dest = NHANES_DIR / name
        if dest.exists() or (NHANES_DIR / name.lower()).exists():
            print(f"[CORPUS] cached: {name}")
            continue
        print(f"[CORPUS] downloading {name} ...")

        def hook(count, block, total):
            if total > 0:
                pct = min(100, int(count * block * 100 / total))
                print(f"\r  {name}: {pct}%", end="")

        try:
            urllib.request.urlretrieve(url, str(dest), reporthook=hook)
            print(f"\r[CORPUS] downloaded {name}        ")
        except Exception as e:
            print(f"\n[CORPUS] failed to download {name}: {e}")
            sys.exit(1)


def train_if_needed(python):
    if all((NHANES_DIR / f"model_{m}.json").exists() for m in MODELS):
        print("[CORPUS] models present — skipping training.")
        return
    banner("Training XGBoost models ...")
    script = NHANES_DIR / "train_regressor_final.py"
    if not script.exists():
        print(f"[CORPUS] missing {script}")
        sys.exit(1)
    subprocess.run([str(python), script.name], cwd=str(NHANES_DIR), check=True)


def launch(python):
    banner("Starting API + opening prototype ...")
    if port_in_use(PORT):
        print(f"[CORPUS] port {PORT} already in use — assuming server is up.")
    else:
        subprocess.Popen([str(python), "-m", "uvicorn", "app:app",
                          "--host", "127.0.0.1", "--port", str(PORT)],
                         cwd=str(NHANES_DIR))
        time.sleep(2.0)
    if HTML.exists():
        webbrowser.open(HTML.as_uri())
    else:
        print("[CORPUS] prototype.html not found.")


def main():
    banner("Corpus bootstrap")
    python, pip = venv_python_pip()
    install(pip)
    download_nhanes()
    train_if_needed(python)
    launch(python)
    banner("Up and running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[CORPUS] shutting down.")


if __name__ == "__main__":
    main()
