#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (Cron). Wertet Trial Reels nach WAIT_DAYS Tagen
anhand von Reach aus: ueber der Schwelle wird der Trial Reel graduiert
(wird zum normalen, oeffentlichen Post ohne erneutes Hochladen), sonst
bleibt er einfach als Trial liegen. Braucht instagram_manage_insights
zusaetzlich auf dem Token.
"""
import json, os
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TRIAL_STATE_FILE = os.path.join(REPO_ROOT, "trial_state.json")

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


def graduate(media_id, token):
    r = requests.post(f"{GRAPH_BASE}/{media_id}",
                       data={"trial_reel_graduation": "GRADUATED", "access_token": token}, timeout=30)
    r.raise_for_status()


def main():
    token = os.environ["IG_ACCESS_TOKEN"]
    state = load_state()
    now = datetime.now(timezone.utc)

    graduated, rejected, skipped = 0, 0, 0
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
        if reach >= REACH_THRESHOLD:
            try:
                graduate(media_id, token)
                entry["status"] = "graduated"
                graduated += 1
                print(f"[{entry.get('reel_nr')}] Graduiert: reach={reach} (media_id={media_id})")
            except requests.HTTPError as e:
                print(f"[{entry.get('reel_nr')}] Graduierung fehlgeschlagen fuer {media_id}: {e}")
        else:
            entry["status"] = "rejected"
            rejected += 1
            print(f"[{entry.get('reel_nr')}] Bleibt Trial: reach={reach} < {REACH_THRESHOLD} (media_id={media_id})")

    save_state(state)
    print(f"Fertig. {graduated} graduiert, {rejected} bleiben Trial, {skipped} noch nicht faellig.")


if __name__ == "__main__":
    main()
