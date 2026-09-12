#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (Cron). Wertet Trial Reels nach WAIT_DAYS Tagen
anhand von Reach aus: ueber der Schwelle kommt der Reel in
best_reel_pool.json und wird vom taeglichen 14-Uhr-Slot
(post_scheduled.py MODE=best_reel) als normaler Post veroeffentlicht.
API-Graduierung von MANUAL-Trial-Reels ist nicht moeglich, deshalb der
Repost-Weg. Braucht instagram_manage_insights zusaetzlich auf dem Token.
"""
import json, os
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TRIAL_STATE_FILE = os.path.join(REPO_ROOT, "trial_state.json")
BEST_POOL_FILE = os.path.join(REPO_ROOT, "best_reel_pool.json")

GRAPH_BASE = "https://graph.facebook.com/v20.0"
WAIT_DAYS = 3
REACH_THRESHOLD = 400  # Richtwert zwischen deinem 200-1000 Normalbereich, bei Bedarf anpassen


def load_state():
    if os.path.exists(TRIAL_STATE_FILE):
        with open(TRIAL_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(TRIAL_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_reach(media_id, token):
    r = requests.get(f"{GRAPH_BASE}/{media_id}/insights",
                      params={"metric": "reach", "access_token": token}, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return 0
    values = data[0].get("values", [])
    return values[0]["value"] if values else 0


def load_best_pool():
    if os.path.exists(BEST_POOL_FILE):
        with open(BEST_POOL_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_best_pool(pool):
    with open(BEST_POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


def main():
    token = os.environ["IG_ACCESS_TOKEN"]
    state = load_state()
    best_pool = load_best_pool()
    now = datetime.now(timezone.utc)

    qualified, rejected, skipped = 0, 0, 0
    for media_id, entry in state.items():
        if entry.get("status") != "pending":
            continue
        posted_at = datetime.fromisoformat(entry["posted_at"])
        age_days = (now - posted_at).total_seconds() / 86400
        if age_days < WAIT_DAYS:
            skipped += 1
            continue

        try:
            reach = get_reach(media_id, token)
        except requests.HTTPError as e:
            print(f"[{entry.get('reel_nr')}] Insights fehlgeschlagen fuer {media_id}: {e}")
            continue

        entry["reach"] = reach
        reel_nr = entry.get("reel_nr")
        if reach >= REACH_THRESHOLD:
            # In den Best-Pool aufnehmen: der taegliche 14-Uhr-Slot
            # (post_scheduled.py MODE=best_reel) postet daraus den besten
            # noch nicht verwendeten Reel als normalen Post.
            if reel_nr and reel_nr not in best_pool:
                best_pool[reel_nr] = media_id
            entry["status"] = "qualified"
            qualified += 1
            print(f"[{reel_nr}] Qualifiziert fuer Best-Pool: reach={reach} (media_id={media_id})")
        else:
            entry["status"] = "rejected"
            rejected += 1
            print(f"[{reel_nr}] Bleibt Trial: reach={reach} < {REACH_THRESHOLD} (media_id={media_id})")

    save_state(state)
    save_best_pool(best_pool)
    print(f"Fertig. {qualified} qualifiziert, {rejected} bleiben Trial, {skipped} noch nicht faellig.")


if __name__ == "__main__":
    main()
