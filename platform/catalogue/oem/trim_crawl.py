#!/usr/bin/env python3
"""Run the trim_pages.py queue unattended through the official Firecrawl CLI.

    python3 trim_crawl.py [MAX_PAGES]

Takes one page per brand in turn (vw, audi, porsche), so each dealer host is
hit at most once every DELAY seconds (their robots.txt asks for a 10 s crawl
delay). Each result is saved where trim_pages.py ingest looks for it, then
ingested. Works without an API key on Firecrawl's keyless tier; uses one if the
CLI is logged in. Stops on a credit, auth or rate-limit error that does not
clear after a back-off, or when every queue is empty. Resumable: state lives in
sources/<brand>/trim_pages.json.
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trim_pages as tp   # noqa: E402

DELAY = 12          # seconds between requests to the SAME host
FATAL = ('insufficient credits', 'unauthorized', 'invalid token', 'payment required')


def fetch(url):
    out = os.path.join(tp.TR, f'mcp-Firecrawl-firecrawl_scrape-cli-{time.time_ns()}.txt')
    env = dict(os.environ, FIRECRAWL_NO_ENDPOINT_FEEDBACK='1')
    r = subprocess.run(['firecrawl', 'scrape', url, '-f', 'rawHtml', '--json', '-o', out],
                       capture_output=True, text=True, timeout=180, env=env)
    msg = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1000
    if not ok and os.path.exists(out):
        os.remove(out)
    return ok, msg


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 6
    os.makedirs(tp.TR, exist_ok=True)
    last, done, fails = {}, 0, 0
    while done < limit:
        brands = [b for b in tp.BRANDS if tp.queue(b)]
        if not brands:
            print('TRIM_CRAWL_DONE queues empty', flush=True)
            return
        for b in brands:
            url = tp.queue(b)[0]
            wait = DELAY - (time.time() - last.get(b, 0))
            if wait > 0:
                time.sleep(wait)
            last[b] = time.time()
            ok, msg = fetch(url)
            if ok:
                tp.ingest()
                done += 1
                fails = 0
                print(f'TRIM_CRAWL {done} {url}', flush=True)
            else:
                fails += 1
                low = msg.lower()
                print(f'TRIM_CRAWL fail {fails} {url}: {msg[-200:]}', flush=True)
                if any(f in low for f in FATAL):
                    print('TRIM_CRAWL_STOP fatal error', flush=True)
                    return
                if fails >= 6:
                    print('TRIM_CRAWL_STOP six failures in a row', flush=True)
                    return
                time.sleep(30 * fails)   # back off; rate limits clear with time
            if done >= limit:
                break
    print(f'TRIM_CRAWL_DONE limit {limit} reached', flush=True)


if __name__ == '__main__':
    main()
