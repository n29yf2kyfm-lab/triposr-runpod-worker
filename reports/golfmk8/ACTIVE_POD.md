# ACTIVE RENTED POD — kill this if it is still running

If you are reading this after a container rollback, a GPU may still be billing.

    pod id : wejjasj6i847wj
    name   : hunyuan-golf-shape
    gpu    : NVIDIA RTX A6000, $0.53/hr
    started: 2026-08-23
    purpose: Hunyuan3D-2 shape generation on the Golf Mk8 plate

Check it, and terminate it when the run is finished or if you cannot tell:

    set -a; . /root/.alam3d_env; set +a
    curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
      https://rest.runpod.io/v1/pods/wejjasj6i847wj \
      | python3 -c "import sys,json;d=json.load(sys.stdin);r=d.get('runtime') or {};\
print('status',d.get('desiredStatus'),'uptime',r.get('uptimeInSeconds'),\
'gpu%',[g.get('gpuUtilPercent') for g in (r.get('gpus') or [])])"

    curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" \
      https://rest.runpod.io/v1/pods/wejjasj6i847wj -w "\ndelete %{http_code}\n"

Results land at car-meshes/gen/v1/golf_a6000/ — mesh.glb, plate.png, boot.log,
and a DONE marker whose contents say either DONE or FAIL_NO_MESH.

POLL PROGRESS, NOT DESIRE. desiredStatus reads RUNNING straight through an
infinite restart loop; uptimeInSeconds resetting while the wall clock climbs IS
that loop, and gpuUtilPercent at 0 means nothing is computing. That distinction
cost this project 78 minutes of unwatched billing once already.

Delete this file when the pod is terminated.
