set -e
cd /tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/rear2
echo "R4 cavity";  python3 tools/render_views.py build/stripped_v4.glb evidence clay 90,35 V4_CAVITY
echo "R4 shaded";  python3 tools/render_views.py build/rear2_v4.glb evidence shaded 90,35,125 V4_shaded
echo "R4 matid";   python3 tools/render_views.py build/rear2_v4.glb evidence matid 90,35 V4_matid
echo "R4 clay";    python3 tools/render_views.py build/rear2_v4.glb evidence clay 90,35 V4_clay
echo "R4 glasson"; python3 tools/render_views.py build/rear2_v4.glb evidence glasson 90 V4_glasson
echo "R4 blue";    python3 tools/respray.py build/rear2_v4.glb build/rear2_v4_blue.glb 0.06 0.15 0.62
python3 tools/render_views.py build/rear2_v4_blue.glb evidence shaded 90,35 V4_blue
echo "R4 red";     python3 tools/respray.py build/rear2_v4.glb build/rear2_v4_red.glb 0.62 0.05 0.05
python3 tools/render_views.py build/rear2_v4_red.glb evidence shaded 90 V4_red
rm -f build/rear2_v4_blue.glb build/rear2_v4_red.glb
echo "R4 clipping"; python3 tools/clipping.py 'evidence/V4_*.png' 'evidence/BASE_*.png'
echo R4_DONE
