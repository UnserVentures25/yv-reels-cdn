#!/usr/bin/env python3
"""
Einmal-Export aller Media-Insights (Feed, Karussells, Reels, Trial Reels)
als JSON-Artifact. Laeuft nur per workflow_dispatch, committet nichts.
"""
import json, os
import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"

METRIC_SETS = [
    ["views", "reach", "likes", "comments", "shares", "saved",
     "total_interactions", "ig_reels_avg_watch_time"],
    ["views", "reach", "likes", "comments", "shares", "saved",
     "total_interactions"],
    ["reach", "saved", "shares", "total_interactions"],
    ["reach"],
]


def get_insights(media_id, token):
    for metrics in METRIC_SETS:
        r = requests.get(f"{GRAPH_BASE}/{media_id}/insights",
                         params={"metric": ",".join(metrics),
                                 "access_token": token}, timeout=30)
        if r.status_code == 200:
            out = {}
            for item in r.json().get("data", []):
                values = item.get("values", [])
                out[item["name"]] = values[0]["value"] if values else None
            return out
    return {"error": r.json().get("error", {}).get("message", "unknown")}


def main():
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user = os.environ["IG_USER_ID"]

    profile = requests.get(
        f"{GRAPH_BASE}/{ig_user}",
        params={"fields": "followers_count,media_count,username",
                "access_token": token}, timeout=30).json()

    media = []
    url = f"{GRAPH_BASE}/{ig_user}/media"
    params = {"fields": "id,caption,media_type,media_product_type,"
                        "timestamp,like_count,comments_count,permalink",
              "limit": 100, "access_token": token}
    while url and len(media) < 400:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        media.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None

    for m in media:
        m["insights"] = get_insights(m["id"], token)

    known_ids = {m["id"] for m in media}
    trial = {}
    if os.path.exists("trial_state.json"):
        with open("trial_state.json", encoding="utf-8") as f:
            trial = json.load(f)
    trial_media = []
    for media_id, entry in trial.items():
        if media_id in known_ids:
            continue
        item = {"id": media_id, "trial_entry": entry}
        r = requests.get(f"{GRAPH_BASE}/{media_id}",
                         params={"fields": "caption,timestamp,media_type,"
                                           "like_count,comments_count",
                                 "access_token": token}, timeout=30)
        if r.status_code == 200:
            item.update(r.json())
        item["insights"] = get_insights(media_id, token)
        trial_media.append(item)

    with open("insights_export.json", "w", encoding="utf-8") as f:
        json.dump({"profile": profile, "media": media,
                   "trial_media": trial_media, "trial_state": trial},
                  f, ensure_ascii=False, indent=2)
    print(f"Export fertig: {len(media)} Media, {len(trial_media)} Trial-only.")


if __name__ == "__main__":
    main()
