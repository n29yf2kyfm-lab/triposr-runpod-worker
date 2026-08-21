set -e
cd /tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/rear2
echo "RSTAGE stripped_cavity"
python3 tools/render_views.py build/stripped_v3.glb evidence clay 90,35 V3_CAVITY
echo "RSTAGE shaded"
python3 tools/render_views.py build/rear2_v3.glb evidence shaded 90,35,125 V3_shaded
echo "RSTAGE matid"
python3 tools/render_views.py build/rear2_v3.glb evidence matid 90,35 V3_matid
echo "RSTAGE clay"
python3 tools/render_views.py build/rear2_v3.glb evidence clay 90,35 V3_clay
echo "RSTAGE glasson"
python3 tools/render_views.py build/rear2_v3.glb evidence glasson 90 V3_glasson
echo "RSTAGE blue"
python3 tools/respray.py build/rear2_v3.glb build/rear2_v3_blue.glb 0.06 0.15 0.62
python3 tools/render_views.py build/rear2_v3_blue.glb evidence shaded 90,35 V3_blue
rm -f build/rear2_v3_blue.glb
echo "RSTAGE base_compare"
python3 tools/render_views.py rear_v3.glb evidence clay 90,35 BASE_clay
python3 tools/render_views.py rear_v3.glb evidence shaded 35 BASE_shaded35
echo "RSTAGE clipping"
python3 tools/clipping.py 'evidence/V3_*.png' 'evidence/BASE_*.png' 'evidence/STRIPPED_*.png'
echo "RENDER_CHAIN_DONE"
