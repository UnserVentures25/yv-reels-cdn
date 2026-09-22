#!/usr/bin/env python3
"""Testet, ob Meta eine Video-URL als REELS-Container verarbeiten kann.
Erstellt NUR den Container und pollt den Status - es wird nichts veroeffentlicht."""
import os, sys, time, requests

GRAPH = "https://graph.facebook.com/v20.0"
url = os.environ["TEST_URL"]
ig = os.environ["IG_USER_ID"]
tok = os.environ["IG_ACCESS_TOKEN"]

print("URL:", url)
h = requests.head(url, allow_redirects=True, timeout=30)
print("HEAD:", h.status_code, "content-type:", h.headers.get("content-type"),
      "length:", h.headers.get("content-length"))

r = requests.post(f"{GRAPH}/{ig}/media", timeout=60, data={
    "media_type": "REELS", "video_url": url,
    "caption": "diagnose - wird nicht veroeffentlicht", "access_token": tok})
print("POST /media:", r.status_code, r.text[:600])
if not r.ok:
    sys.exit("Container-Erstellung fehlgeschlagen")

cid = r.json()["id"]
for _ in range(40):
    s = requests.get(f"{GRAPH}/{cid}", timeout=30,
                     params={"fields": "status_code,status", "access_token": tok}).json()
    print("  status:", s)
    if s.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
        break
    time.sleep(5)
print("ERGEBNIS:", s.get("status_code"))
print("Container-ID (nicht veroeffentlicht):", cid)
