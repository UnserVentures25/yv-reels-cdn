#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (Cron). Wertet Trial Reels nach WAIT_DAYS Tagen
anhand von Reach aus: ueber der Schwelle kommt der Reel in
best_reel_pool.json und wird vom taeglichen 14-Uhr-Slot
(post_scheduled.py MODE=best_reel) als normaler Post veroeffentlicht.
API-Graduierung von MANUAL-Trial-Reels ist nicht moeglich, deshalb der
Repost-Weg. Braucht instagram_manage_insights zusaetzlich auf dem Token.
"""
import json, os, statistics
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TRIAL_STATE_FILE = os.path.join(REPO_ROOT, "trial_state.json")
BEST_POOL_FILE = os.path.join(REPO_ROOT, "best_reel_pool.json")

GRAPH_BASE = "https://graph.facebook.com/v20.0"
WAIT_DAYS = 3

# Die Schwelle ist relativ, nicht absolut (17.09.26). Vorher standen hier feste
# 400. Das war doppelt falsch: im September lag der Median-Reach bei 119, also
# fiel fast alles durch und "rejected" ist endgueltig. Erholt sich die
# Reichweite auf Juli-Niveau (Median 2.580), qualifiziert dieselbe 400
# umgekehrt praktisch jeden Reel. Stattdessen: ein Reel muss besser sein als
# der Median der zuletzt bewerteten Reels.
HISTORY_SIZE = 30          # so viele frueher bewertete Reels bilden den Vergleich
MIN_REACH_FLOOR = 80       # darunter nie qualifizieren, egal wie schwach der Rest ist


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


def schwelle(state, batch_reach):
    """Median der zuletzt bewerteten Reels. Beim ersten Lauf gibt es keine
    Historie - dann dient der aktuelle Batch selbst als Vergleichsmassstab."""
    historie = [e["reach"] for e in state.values()
                if e.get("reach") is not None and e.get("status") in ("qualified", "rejected")]
    basis = historie[-HISTORY_SIZE:] if historie else batch_reach
    if not basis:
        return MIN_REACH_FLOOR
    return max(MIN_REACH_FLOOR, statistics.median(basis))


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

    # Erst alle faelligen Reels abfragen, dann bewerten: die Schwelle braucht
    # den kompletten Batch, falls noch keine Historie existiert.
    faellig = []
    skipped = 0
    for media_id, entry in state.items():
        if entry.get("status") != "pending":
            continue
        posted_at = datetime.fromisoformat(entry["posted_at"])
        if (now - posted_at).total_seconds() / 86400 < WAIT_DAYS:
            skipped += 1
            continue
        try:
            reach = get_reach(media_id, token)
        except requests.HTTPError as e:
            print(f"[{entry.get('reel_nr')}] Insights fehlgeschlagen fuer {media_id}: {e}")
            continue
        faellig.append((media_id, entry, reach))

    grenze = schwelle(state, [r for _, _, r in faellig])
    print(f"Schwelle fuer diesen Lauf: reach >= {grenze:.0f}")

    qualified, rejected = 0, 0
    for media_id, entry, reach in faellig:
        entry["reach"] = reach
        reel_nr = entry.get("reel_nr")
        if reach >= grenze:
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
            print(f"[{reel_nr}] Bleibt Trial: reach={reach} < {grenze:.0f} (media_id={media_id})")

    save_state(state)
    save_best_pool(best_pool)
    print(f"Fertig. {qualified} qualifiziert, {rejected} bleiben Trial, {skipped} noch nicht faellig.")


if __name__ == "__main__":
    main()
