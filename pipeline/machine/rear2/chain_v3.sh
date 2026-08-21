set -e
cd /tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/rear2
echo "== BUILD"
python3 tools/build_rear.py rear_v3.glb build > build/build_v3.json 2>&1
echo "== ASSEMBLE"
python3 tools/strip_assemble.py rear_v3.glb build/rear2_v3.glb build/stripped_v3.glb
echo "== INVENTORY"
python3 tools/inventory.py build/rear2_v3.glb measurements/inventory_v3.json | tail -30
echo "== GLASS"
python3 tools/glass_local.py build/rear2_v3.glb measurements/glass_v3.json > /dev/null
python3 -c "import json;d=json.load(open('measurements/glass_v3.json'));print('GLASS',d['verdict'],'/',d['certainty'],'flat_shell',d.get('flat_shell'),'alpha_shell',d.get('alpha_shell'))"
echo "== PROVENANCE"
python3 tools/verify_provenance.py rear_v3.glb build/rear2_v3.glb measurements/provenance_v3.json
echo "== LAMPS"
python3 tools/verify_lamps.py rear_v3.glb build/rear2_v3.glb measurements/lamps_v3.json
echo "== LEFTRIGHT"
python3 tools/verify_lr.py rear_v3.glb build/rear2_v3.glb measurements/lr_v3.json
echo "== NESTED (hidden melt under the new skin)"
python3 tools/layer_probe.py build/rear2_v3.glb measurements/layers_v3.json > measurements/layers_v3.txt 2>&1
tail -30 measurements/layers_v3.txt
echo "== HOLES"
python3 tools/verify_holes.py rear_v3.glb build/rear2_v3.glb measurements/holes_v3.json
echo "== HOLES SELFTEST (negative control)"
python3 tools/verify_holes.py rear_v3.glb build/rear2_v3.glb measurements/holes_selftest.json --selftest
echo "CHAIN_V3_DONE"
