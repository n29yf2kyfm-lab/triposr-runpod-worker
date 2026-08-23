# ACTIVE RENTED POD — kill this if it is still running

    pod id : efih2qx042vujg
    launch : pipeline/trellis/launch_pixal_batch.py  (Pixal3D, A100 80GB)
    car    : golffresh  (fresh Golf Mk8 RGBA cutout, front 3/4)
    started: 2026-08-23
    expect : ~3 min boot + deps, ~12 min inference, ~$0.65

The launcher deletes the pod on a terminal marker and verifies it is gone. It
cannot do that if this container rolls back mid-run -- which has happened six
times in one session -- so the id lives here where a rollback cannot reach it.

    set -a; . /root/.alam3d_env; set +a
    curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
      https://rest.runpod.io/v1/pods/efih2qx042vujg \
      | python3 -c "import sys,json;d=json.load(sys.stdin);r=d.get('runtime') or {};\
print('uptime',r.get('uptimeInSeconds'),'gpu%',[g.get('gpuUtilPercent') for g in (r.get('gpus') or [])])"

    curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" \
      https://rest.runpod.io/v1/pods/efih2qx042vujg -w "\ndelete %{http_code}\n"

Progress and result land in car-meshes/pixal_batch/ : log.txt, out_golffresh.glb,
crease.txt. POLL THE BUCKET LOG, never desiredStatus -- it reads RUNNING straight
through a restart loop.

Delete this file when the pod is terminated.
