#!/usr/bin/env python3
"""
Diagnose fuer das DM-Autoreply: zeigt welche Scopes auf den Tokens liegen und
welche Messaging-Endpunkte antworten. Gibt nie den Token selbst aus.
Nur manuell via workflow_dispatch.
"""
import os
import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"


def debug_token(label, token):
    print(f"\n=== {label} ===")
    if not token:
        print("  nicht gesetzt")
        return
    r = requests.get(f"{GRAPH_BASE}/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=30)
    if not r.ok:
        print(f"  debug_token fehlgeschlagen: {r.status_code} {r.text[:200]}")
        return
    d = r.json().get("data", {})
    print(f"  Typ:       {d.get('type')}")
    print(f"  App-ID:    {d.get('app_id')}")
    print(f"  Gueltig:   {d.get('is_valid')}")
    print(f"  Laeuft ab: {d.get('expires_at')} (0 = nie)")
    scopes = d.get("scopes", [])
    print(f"  Scopes ({len(scopes)}):")
    for s in sorted(scopes):
        print(f"    - {s}")
    for need in ["instagram_manage_messages", "pages_messaging", "pages_show_list",
                 "instagram_basic", "instagram_manage_comments"]:
        mark = "OK   " if need in scopes else "FEHLT"
        print(f"  [{mark}] {need}")


def probe(label, url, token, params=None):
    p = {"access_token": token}
    p.update(params or {})
    r = requests.get(url, params=p, timeout=30)
    status = "OK    " if r.ok else "FEHLER"
    print(f"  [{status}] {label}: HTTP {r.status_code}")
    if not r.ok:
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        print(f"           msg:  {err.get('message')}")
        print(f"           code: {err.get('code')} subcode: {err.get('error_subcode')}")
    return r.ok


def main():
    ig_id = os.environ["IG_USER_ID"]
    ig_token = os.environ["IG_ACCESS_TOKEN"]
    page_id = os.environ.get("FB_PAGE_ID")
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")

    debug_token("IG_ACCESS_TOKEN", ig_token)
    debug_token("FB_PAGE_ACCESS_TOKEN", page_token)

    print("\n=== Endpunkt-Tests (Messaging) ===")
    probe("IG-User /conversations", f"{GRAPH_BASE}/{ig_id}/conversations", ig_token,
          {"platform": "instagram", "limit": 1})
    if page_id:
        probe("Page /conversations (IG-Token)", f"{GRAPH_BASE}/{page_id}/conversations", ig_token,
              {"platform": "instagram", "limit": 1})
        if page_token:
            probe("Page /conversations (Page-Token)", f"{GRAPH_BASE}/{page_id}/conversations", page_token,
                  {"platform": "instagram", "limit": 1})
            probe("Page /conversations ohne platform", f"{GRAPH_BASE}/{page_id}/conversations", page_token,
                  {"limit": 1})

    print("\n=== Kontrolle: was FUNKTIONIERT (Vergleich) ===")
    probe("IG-User /media (Posting laeuft)", f"{GRAPH_BASE}/{ig_id}/media", ig_token, {"limit": 1})

    print("\n=== Verknuepfung Page <-> IG ===")
    if page_id and page_token:
        probe("Page -> instagram_business_account", f"{GRAPH_BASE}/{page_id}", page_token,
              {"fields": "instagram_business_account,name"})


if __name__ == "__main__":
    main()
