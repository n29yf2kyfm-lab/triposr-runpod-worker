set -eu
cd /tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/rear2
echo "STAGE cavity"
python3 tools/render_views.py build/stripped_only.glb evidence clay 90,35 STRIPPED_cavity
echo "STAGE v1_shaded"
python3 tools/render_views.py build/rear2_v1.glb evidence shaded 90,35,125 v1_shaded
echo "STAGE v1_matid"
python3 tools/render_views.py build/rear2_v1.glb evidence matid 90,35 v1_matid
echo "STAGE v1_clay"
python3 tools/render_views.py build/rear2_v1.glb evidence clay 90,35 v1_clay
echo "STAGE respray"
python3 tools/respray.py build/rear2_v1.glb build/rear2_v1_blue.glb 0.06 0.15 0.62
python3 tools/render_views.py build/rear2_v1_blue.glb evidence shaded 90,35 v1_blue
rm -f build/rear2_v1_blue.glb
echo "BATCH1_ALL_DONE"
