"""Rate-limited MediaWiki API client (Wikipedia + Commons). Max 1 request/second.
Fetches JSON metadata only; never downloads image files."""
import json, time, urllib.parse, urllib.request, urllib.error, os, hashlib

UA = "VWGroupPartsCatalogue/1.0 (research; metadata-only)"
WP = "https://en.wikipedia.org/w/api.php"
CM = "https://commons.wikimedia.org/w/api.php"
_last = [0.0]
CACHE = os.path.join(os.path.dirname(__file__), "..", ".cache")
os.makedirs(CACHE, exist_ok=True)
NREQ = [0]

def api(endpoint, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    q = urllib.parse.urlencode(params)
    key = hashlib.sha1((endpoint + "?" + q).encode()).hexdigest()
    cp = os.path.join(CACHE, key + ".json")
    if os.path.exists(cp):
        with open(cp) as f:
            return json.load(f)
    for attempt in range(5):
        wait = 1.05 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        NREQ[0] += 1
        try:
            req = urllib.request.Request(endpoint + "?" + q, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            if "error" in data and data["error"].get("code") == "maxlag":
                time.sleep(5); continue
            with open(cp, "w") as f:
                json.dump(data, f)
            return data
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After")
            print("  retry", attempt, e, "retry-after", ra)
            time.sleep(max(int(ra) if ra and ra.isdigit() else 0, 10 * (attempt + 1)))
        except Exception as e:
            print("  retry", attempt, e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("API failed: " + q[:200])
