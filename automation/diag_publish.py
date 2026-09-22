#!/usr/bin/env python3
"""Diagnose fuer media_publish 2207085.
Phase A liest nur (kein Post). Phase B veroeffentlicht testweise, nur wenn
PUBLISH=true gesetzt ist."""
import json, os, sys, time, requests

ig = os.environ["IG_USER_ID"]
quelle = os.environ.get("TOKEN_SOURCE", "user")
tok = os.environ["FB_PAGE_ACCESS_TOKEN"] if quelle == "page" else os.environ["IG_ACCESS_TOKEN"]
print(f"### Token-Quelle: {quelle}")
url = os.environ["TEST_URL"]
ver = os.environ.get("API_VERSION", "v23.0")
do_publish = os.environ.get("PUBLISH", "").lower() == "true"
G = f"https://graph.facebook.com/{ver}"

def show(label, path, **params):
    params["access_token"] = tok
    r = requests.get(f"{G}/{path}", params=params, timeout=30)
    print(f"--- {label}: {r.status_code} {r.text[:500]}")
    return r

print(f"=== PHASE A (nur lesend), API {ver}")
show("Account", ig, fields="id,username,media_count,followers_count,profile_picture_url")
show("Publishing-Limit", f"{ig}/content_publishing_limit",
     fields="config,quota_usage,rate_limit_settings")
r = requests.get("https://graph.facebook.com/debug_token", timeout=30,
                 params={"input_token": tok, "access_token": tok})
d = r.json().get("data", {})
print("--- Token:", {k: d.get(k) for k in
      ("is_valid", "type", "app_id", "expires_at", "profile_id")})
print("--- Scopes:", d.get("scopes"))
for gs in d.get("granular_scopes", []):
    if "instagram" in gs.get("scope", ""):
        tids = gs.get("target_ids")
        print(f"--- granular {gs['scope']}: targets={tids} "
              f"enthaelt_IG={'JA' if tids and str(ig) in [str(t) for t in tids] else 'nein/alle'}")

r = requests.get(f"{G}/me/accounts", timeout=30, params={
    "fields": "id,name,access_token,instagram_business_account{id,username},"
              "connected_instagram_account{id,username},category,fan_count,"
              "is_published,link,verification_status,created_time",
    "access_token": tok})
print("--- /me/accounts:", r.status_code)
for p in r.json().get("data", []):
    igb = p.get("instagram_business_account") or {}
    con = p.get("connected_instagram_account") or {}
    print(f"    connected_instagram_account: {con.get('id')} ({con.get('username')}) "
          f"passt={'JA' if str(con.get('id')) == str(ig) else 'nein'}")
    pt = p.get("access_token")
    print(f"    -> Kategorie={p.get('category')} Fans={p.get('fan_count')} "
          f"published={p.get('is_published')} link={p.get('link')} "
          f"erstellt={p.get('created_time')}")
    print(f"    Seite {p.get('id')} '{p.get('name')}' "
          f"IG={igb.get('id')} ({igb.get('username')}) "
          f"passt={'JA' if str(igb.get('id')) == str(ig) else 'nein'} "
          f"Page-Token={'vorhanden' if pt else 'FEHLT'}")
    if pt:
        d2 = requests.get("https://graph.facebook.com/debug_token", timeout=30,
                          params={"input_token": pt, "access_token": tok}).json().get("data", {})
        print(f"      Page-Token-Typ: {d2.get('type')} valid={d2.get('is_valid')} "
              f"profile_id={d2.get('profile_id')}")

h = requests.head(url, allow_redirects=True, timeout=30)
print("--- Video-URL:", h.status_code, h.headers.get("content-type"),
      h.headers.get("content-length"))

if not do_publish:
    print("=== PHASE B uebersprungen (PUBLISH != true)")
    sys.exit(0)

print(f"=== PHASE B: Container + Publish mit {ver}")
r = requests.post(f"{G}/{ig}/media", timeout=60, data={
    "media_type": "REELS", "video_url": url,
    "caption": os.environ.get("CAPTION", "Test"), "access_token": tok})
print("POST /media:", r.status_code, r.text[:400])
r.raise_for_status()
cid = r.json()["id"]

for _ in range(60):
    s = requests.get(f"{G}/{cid}", timeout=30,
                     params={"fields": "status_code,status", "access_token": tok}).json()
    if s.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
        break
    time.sleep(5)
print("Container-Status:", s)
if s.get("status_code") != "FINISHED":
    sys.exit("Container nicht FINISHED")

r = requests.post(f"{G}/{ig}/media_publish", timeout=60,
                  data={"creation_id": cid, "access_token": tok})
print("POST /media_publish:", r.status_code, r.text[:600])
r.raise_for_status()
print("ERFOLG media_id:", r.json()["id"])
