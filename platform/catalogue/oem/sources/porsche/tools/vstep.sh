# ingest any saved porsche year/model page results, pace to <=2 calls/min, print next page
TR=/root/.claude/projects/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/tool-results
T=$(dirname "$0")
F=$(grep -l '"sourceURL":"https://porsche.oempartsonline.com/v-' $TR/mcp-Firecrawl-firecrawl_scrape-*.txt 2>/dev/null)
[ -n "$F" ] && python3 -I $T/vehicle_pages.py ingest $F | tail -2
sleep 22
python3 -I $T/vehicle_pages.py next
