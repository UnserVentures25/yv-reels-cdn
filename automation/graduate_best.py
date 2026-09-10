#!/usr/bin/env python3
"""
Einmaliges Recovery-Skript: nimmt eine Liste rekonstruierter media_ids
(reel_nr:media_id), fragt Reach ab, graduiert NUR den besten Performer,
um zu testen ob das das Trial-Reel-Limit befreit. Rest bleibt unberuehrt.
"""
import os
import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"


def get_reach(media_id, token):
    r = requests.get(f"{GRAPH_BASE}/{media_id}/insights",
                      params={"metric": "reach", "access_token": token}, timeout=30)
    if not r.ok:
        print(f"  Insights-Fehler {media_id}: {r.status_code} {r.text}")
        return None
    data = r.json().get("data", [])
    if not data:
        return 0
    values = data[0].get("values", [])
    return values[0]["value"] if values else 0


def graduate(media_id, token):
    r = requests.post(f"{GRAPH_BASE}/{media_id}",
                       data={"trial_reel_graduation": "GRADUATED", "access_token": token}, timeout=30)
    if not r.ok:
        print(f"Graduierung-Fehler {media_id}: {r.status_code} {r.text}")
    r.raise_for_status()


def main():
    token = os.environ["IG_ACCESS_TOKEN"]
    pairs_raw = os.environ["MEDIA_PAIRS"]  # "reelnr:mediaid,reelnr:mediaid,..."

    results = []
    for pair in pairs_raw.split(","):
        reel_nr, media_id = pair.split(":")
        reach = get_reach(media_id, token)
        print(f"[{reel_nr}] media_id={media_id} reach={reach}")
        if reach is not None:
            results.append((reach, reel_nr, media_id))

    if not results:
        raise SystemExit("Keine Reach-Daten erhalten, breche ab.")

    results.sort(reverse=True)
    best_reach, best_reel, best_media_id = results[0]
    print(f"\nBester Performer: Reel {best_reel}, media_id={best_media_id}, reach={best_reach}")
    print("Graduiere...")
    graduate(best_media_id, token)
    print(f"Graduiert: Reel {best_reel} (media_id={best_media_id})")


if __name__ == "__main__":
    main()
