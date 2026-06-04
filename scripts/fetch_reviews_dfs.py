#!/usr/bin/env python3
"""Pull live Google reviews for an Allo clinic via DataForSEO (no owner OAuth / no API allowlist).
Auth: DATAFORSEO_AUTH (Basic token) in env. Task-based: post -> poll -> get.
Usage: python3 scripts/fetch_reviews_dfs.py "Allo Health Bellandur" "Bengaluru,Karnataka,India"
"""
import os, sys, json, time, urllib.request

AUTH = os.environ.get("DATAFORSEO_AUTH", "")
BASE = "https://api.dataforseo.com/v3/business_data/google/reviews"

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Basic " + AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def main(keyword, location):
    if not AUTH: sys.exit("no DATAFORSEO_AUTH in env")
    post = call("POST", "/task_post", [{"keyword": keyword, "location_name": location,
              "language_name": "English", "depth": 60, "sort_by": "newest"}])
    task = (post.get("tasks") or [{}])[0]
    tid = task.get("id")
    if not tid:
        sys.exit("task_post failed: " + str(task.get("status_message")))
    print("task posted:", tid, "· polling…", flush=True)
    res = None
    for i in range(24):                       # up to ~6 min
        time.sleep(15)
        got = call("GET", "/task_get/" + tid)
        t = (got.get("tasks") or [{}])[0]
        if t.get("status_code") == 20000 and t.get("result"):
            res = t["result"][0]; break
        print("  …not ready (%s)" % t.get("status_message"), flush=True)
    if not res:
        sys.exit("timed out waiting for reviews")
    items = res.get("items") or []
    print("BUSINESS:", res.get("title"), "· rating", res.get("rating", {}).get("value"),
          "· total reviews", res.get("reviews_count"))
    print("pulled %d review items (newest first):" % len(items))
    out = []
    for it in items:
        out.append({"rating": (it.get("rating") or {}).get("value"),
                    "date": it.get("timestamp"), "author": it.get("profile_name"),
                    "text": (it.get("review_text") or "")[:240],
                    "replied": bool(it.get("owner_answer"))})
    for r in out[:15]:
        print(f"  {r['date']} · {r['rating']}★ · {r['author']} · {r['text'][:80]}")
    json.dump({"business": res.get("title"), "items": out},
              open("/tmp/bellandur_reviews_dfs.json", "w"), indent=2)
    s = json.dumps(out)
    print("\nAnurag present:", "Anurag" in s, "· 'workaround' present:", "workaround" in s.lower())

if __name__ == "__main__":
    kw = sys.argv[1] if len(sys.argv) > 1 else "Allo Health Bellandur"
    loc = sys.argv[2] if len(sys.argv) > 2 else "Bengaluru,Karnataka,India"
    main(kw, loc)
