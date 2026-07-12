"""
Call a deployed RunPod SAM 3D Body endpoint with a real photo, save the JSON.

    export RUNPOD_API_KEY="…"
    export RUNPOD_ENDPOINT_ID="…"
    python test_endpoint.py path/to/photo.jpg
"""

import os
import sys
import json
import time
import base64

import requests


def main():
    if len(sys.argv) != 2:
        print("Usage: python test_endpoint.py path/to/photo.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    api_key = os.environ["RUNPOD_API_KEY"]
    endpoint_id = os.environ["RUNPOD_ENDPOINT_ID"]

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"input": {"image_base64": img_b64}}

    print("Submitting job (first cold start can take a few minutes) ...")
    start = time.time()
    resp = requests.post(url, headers=headers, json=payload, timeout=600)
    resp.raise_for_status()
    result = resp.json()
    print(f"Done in {time.time() - start:.1f}s. Status: {result.get('status')}")

    with open("phase0_result.json", "w") as f:
        json.dump(result, f, indent=2)

    output = result.get("output", {})
    print(f"People detected: {output.get('num_people_detected')}")
    print("Full response saved to phase0_result.json")


if __name__ == "__main__":
    main()
