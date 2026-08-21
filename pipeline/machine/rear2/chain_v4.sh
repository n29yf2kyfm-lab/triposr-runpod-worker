set -e
cd /tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/rear2
echo "V4 == inventory";   python3 tools/inventory.py build/rear2_v4.glb measurements/inventory_v4.json | tail -30
echo "V4 == glass";       python3 tools/glass_local.py build/rear2_v4.glb measurements/glass_v4.json >/dev/null
python3 -c "import json;d=json.load(open('measurements/glass_v4.json'));print('GLASS',d['verdict'],'/',d['certainty'],'flat_shell',d.get('flat_shell'),'alpha_shell',d.get('alpha_shell'))"
echo "V4 == provenance";  python3 tools/verify_provenance.py rear_v3.glb build/rear2_v4.glb measurements/provenance_v4.json
echo "V4 == lamps";       python3 tools/verify_lamps.py rear_v3.glb build/rear2_v4.glb measurements/lamps_v4.json
echo "V4 == leftright";   python3 tools/verify_lr.py rear_v3.glb build/rear2_v4.glb measurements/lr_v4.json | tail -22
echo "V4 == underskin";   python3 tools/under_skin.py build/rear2_v4.glb measurements/under_skin_v4.json | grep -E "pct_rays_with_melt|first_surface|rays\"" 
echo "V4 == holes";       python3 tools/verify_holes.py rear_v3.glb build/rear2_v4.glb measurements/holes_v4.json 2>/dev/null | head -8
echo "V4 == holes selftest"; python3 tools/verify_holes.py rear_v3.glb build/rear2_v4.glb measurements/holes_v4_selftest.json --selftest 2>/dev/null | head -8
echo "V4 == freshimport"; python3 tools/fresh_import.py build/rear2_v4.glb measurements/fresh_import_v4.json
echo V4_VERIFY_DONE
