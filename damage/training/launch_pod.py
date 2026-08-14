"""Rent a GPU, run train.sh on it, and let it stop itself.

Every previous pod in this project was created by hand, which is why the log is
full of runs that died on a detail nobody could reproduce. This makes the
launch a command with arguments instead.

THE POD STOPS ITSELF. train.sh's EXIT trap uploads the log, publishes any
checkpoint, and then calls the RunPod API to stop its own pod — on failure as
well as success. That matters more than it sounds: a watcher in the controlling
session is NOT a failsafe, because that process is frozen whenever the session
is idle, and this project has already paid for six hours of a pod that nothing
was awake to stop. So the pod is given its own API key and its own id, and the
launcher's job ends once the pod is running.

DISK IS SIZED FOR THE WHOLE PIPELINE, NOT THE CORPUS. The pod holds the 14GB
corpus download, ~20GB of materialised training samples, and ~10GB of torch and
CUDA wheels at once. Undersizing it fails partway through materialising, after
the download is paid for.

    python launch_pod.py --smoke          # ~25 min, LIMIT'd, proves the path
    python launch_pod.py --hours 14       # the real run
    python launch_pod.py --dry-run
"""
import argparse
import json
import os
import sys
GQL = "https://api.runpod.io/graphql"

# 48GB, ~$0.33/hr at the time of writing. The VRAM matters more than the clock
# here: RF-DETR's batch size is what it constrains, and a larger batch is worth
# more than a faster card that forces gradient accumulation.
# Availability churns constantly and a "Low"/"Medium" stock label does not
# predict deployability: A6000, A40 and 4090 all reported stock and all
# refused to deploy, while the Blackwell did. So this is a FALLBACK LIST tried
# in order, not one choice. All carry >=24GB, enough for RF-DETR at batch 8.
GPU_FALLBACKS = (
    "NVIDIA RTX A6000",              # 48GB
    "NVIDIA A40",                    # 48GB
    "NVIDIA RTX PRO 4500 Blackwell",  # 32GB
    "NVIDIA GeForce RTX 4090",       # 24GB
    "NVIDIA GeForce RTX 3090",       # 24GB
    "NVIDIA RTX A5000",              # 24GB
)
DEFAULT_GPU = GPU_FALLBACKS[0]

# Torch is upgraded by train.sh from the driver anyway, so the image only needs
# to be a sane CUDA base with python.
DEFAULT_IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"

BOOTSTRAP = r"""bash -lc '
set -x
export DEBIAN_FRONTEND=noninteractive
pip install -q huggingface_hub || exit 90
python - <<PY || exit 91
import os
from huggingface_hub import hf_hub_download
p = hf_hub_download(repo_id=os.environ["HF_REPO"], filename="train.sh",
                    token=os.environ["HF_TOKEN"], local_dir="/workspace")
print("train.sh at", p)
PY
bash /workspace/train.sh
'"""


def gql(query, variables, key):
    """POST to RunPod's GraphQL endpoint.

    Uses requests, not urllib: outbound HTTPS here goes through an agent proxy
    that requests picks up from the environment and urllib does not, so the
    urllib version returned 403 Forbidden on every call while curl to the same
    endpoint worked.
    """
    import requests
    r = requests.post(GQL, json={"query": query, "variables": variables},
                      headers={"Authorization": f"Bearer {key}"}, timeout=90)
    if r.status_code != 200:
        raise SystemExit(f"RunPod HTTP {r.status_code}: {r.text[:400]}")
    doc = r.json()
    if "errors" in doc:
        raise SystemExit("RunPod error: " + json.dumps(doc["errors"])[:600])
    return doc["data"]


def balance(key):
    return gql("query{myself{clientBalance currentSpendPerHr}}", {}, key)["myself"]


def launch(args, env, gpu):
    q = """
    mutation($in: PodFindAndDeployOnDemandInput) {
      podFindAndDeployOnDemand(input: $in) {
        id name desiredStatus imageName machineId
        runtime { uptimeInSeconds }
      }
    }"""
    payload = {
        "cloudType": args.cloud,
        "gpuCount": 1,
        "volumeInGb": 0,
        "containerDiskInGb": args.disk,
        "gpuTypeId": gpu,
        "name": args.name,
        "imageName": args.image,
        "dockerArgs": BOOTSTRAP,
        "ports": "8888/http",
        "env": [{"key": k, "value": v} for k, v in env.items()],
    }
    return gql(q, {"in": payload}, args.api_key)["podFindAndDeployOnDemand"]


# The pod runs what is in the HF repo, NOT what is on this disk. The smoke run
# died because train.sh had been edited locally and never re-uploaded: the pod
# fetched a version without allow_patterns, pulled 10,033 files instead of 32,
# and drove the Hub's read endpoint into HTTP 429. Publishing on every launch
# removes that whole class of failure rather than the one instance of it.
SCRIPTS = ("train.sh", "train_detector.py", "materialise_index.py",
           "augment.py", "watermark_aug.py", "class_map.py")


def publish_scripts(repo, token, here=None):
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    here = here or os.path.dirname(os.path.abspath(__file__))
    sent = []
    for f in SCRIPTS:
        path = os.path.join(here, f)
        if not os.path.exists(path):
            raise SystemExit(f"cannot publish: {path} is missing")
        api.upload_file(path_or_fileobj=path, path_in_repo=f,
                        repo_id=repo, repo_type="model")
        sent.append(f)
    return sent


def launch_with_fallback(args, env):
    """Try each GPU in turn. Returns (pod, gpu) or raises.

    A capacity refusal is not an error worth stopping for — it is the normal
    state of a spot market. Trying the next card beats making the operator
    probe by hand, which is how a bare pod with no environment and no script
    ended up running and billing.
    """
    tried = []
    order = ([args.gpu] + [g for g in GPU_FALLBACKS if g != args.gpu]
             if args.fallback else [args.gpu])
    for gpu in order:
        try:
            pod = launch(args, env, gpu)
            if pod and pod.get("id"):
                return pod, gpu
            tried.append((gpu, "empty response"))
        except SystemExit as e:
            msg = str(e)
            if "resources" not in msg and "no longer any instances" not in msg:
                raise
            tried.append((gpu, "no capacity"))
            print(f"  {gpu}: no capacity")
    raise SystemExit("no GPU available; tried " +
                     ", ".join(f"{g} ({w})" for g, w in tried))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("RUNPOD_API_KEY"))
    ap.add_argument("--hf-token", default=os.environ.get("HF_TOKEN"))
    ap.add_argument("--hf-repo", default="Alamj/damage-detector")
    ap.add_argument("--corpus-repo", default="Alamj/damage-corpus")
    ap.add_argument("--gpu", default=DEFAULT_GPU)
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--cloud", default="ALL", choices=["ALL", "SECURE",
                                                       "COMMUNITY"])
    ap.add_argument("--disk", type=int, default=120,
                    help="GB; holds corpus + materialised samples + wheels")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0,
                    help="cap materialised samples (smoke runs)")
    ap.add_argument("--hours", type=float, default=14.0,
                    help="only used to price the run and warn")
    ap.add_argument("--name", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-publish", dest="publish", action="store_false",
                    default=True,
                    help="do not upload the local scripts before launching "
                         "(the pod then runs whatever the repo already holds)")
    ap.add_argument("--no-fallback", dest="fallback", action="store_false",
                    default=True,
                    help="do not try other GPUs when capacity is refused")
    ap.add_argument("--smoke", action="store_true",
                    help="short proving run: 2000 samples, 1 epoch")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.smoke:
        a.limit = a.limit or 2000
        a.epochs = 1
        a.hours = 0.5
        a.name = a.name or "damage-smoke"
        a.tag = a.tag or "smoke"
    a.name = a.name or "damage-train"
    a.tag = a.tag or "train"

    missing = [n for n, v in (("--api-key/RUNPOD_API_KEY", a.api_key),
                              ("--hf-token/HF_TOKEN", a.hf_token)) if not v]
    if missing:
        raise SystemExit("missing: " + ", ".join(missing))

    bal = balance(a.api_key)
    have = float(bal["clientBalance"])
    print(f"balance      ${have:.2f}   currently spending "
          f"${float(bal['currentSpendPerHr']):.2f}/hr")

    env = {
        "HF_TOKEN": a.hf_token,
        "HF_REPO": a.hf_repo,
        "CORPUS_REPO": a.corpus_repo,
        "RUNPOD_API_KEY": a.api_key,      # so the pod can stop ITSELF
        "RUN_TAG": a.tag,
        "EPOCHS": str(a.epochs),
        "BATCH": str(a.batch),
    }
    if a.limit:
        env["LIMIT"] = str(a.limit)

    print(f"gpu          {a.gpu}   disk {a.disk}GB   cloud {a.cloud}")
    print(f"run          tag={a.tag} epochs={a.epochs} batch={a.batch}"
          + (f" limit={a.limit}" if a.limit else " (full corpus)"))
    print(f"corpus       {a.corpus_repo}")
    print(f"output       {a.hf_repo}")
    print("env keys     " + ", ".join(sorted(env)))

    if a.dry_run:
        print("\n(dry run — no pod created)")
        return 0

    if a.publish:
        sent = publish_scripts(a.hf_repo, a.hf_token)
        print(f"published     {len(sent)} scripts -> {a.hf_repo}")

    pod, gpu = launch_with_fallback(a, env)
    print(f"\npod {pod['id']}  {pod.get('name')}  {pod.get('desiredStatus')}"
          f"  on {gpu}")
    print(f"logs will land at https://huggingface.co/{a.hf_repo}"
          f"/blob/main/logs/{a.tag}.log")
    print("\nThe pod stops itself when train.sh exits, success or failure.")
    print(f"To stop it by hand:\n  python {os.path.basename(__file__)} "
          f"--stop {pod['id']}")
    return 0


if __name__ == "__main__":
    if "--stop" in sys.argv:
        i = sys.argv.index("--stop")
        pid = sys.argv[i + 1]
        key = os.environ.get("RUNPOD_API_KEY")
        gql("mutation($in: PodStopInput!){podStop(input:$in){id desiredStatus}}",
            {"in": {"podId": pid}}, key)
        print(f"stopped {pid}")
        sys.exit(0)
    sys.exit(main())
