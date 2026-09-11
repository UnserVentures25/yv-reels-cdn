#!/usr/bin/env python3
"""Einmaliger Check: wann sind die Follower online (fuer beste Postzeit)."""
import os
import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"


def main():
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_USER_ID"]
    r = requests.get(f"{GRAPH_BASE}/{ig_user_id}/insights",
                      params={"metric": "online_followers", "period": "lifetime", "access_token": token},
                      timeout=30)
    if not r.ok:
        print("Fehler:", r.status_code, r.text)
        return
    data = r.json()["data"][0]["values"][0]["value"]
    ranked = sorted(data.items(), key=lambda kv: -int(kv[1]))
    print("Top 5 Stunden (UTC), nach Online-Followern:")
    for hour, count in ranked[:5]:
        print(f"  {hour}:00 UTC -> {count} Follower online")


if __name__ == "__main__":
    main()
