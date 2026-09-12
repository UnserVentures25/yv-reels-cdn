#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (stuendlicher Cron in daily-trial-reels.yml).
Postet pro Aufruf 1 Reel aus state.json als Instagram Trial Reel,
optional als Facebook-Video-Crosspost.
Ein Zeitfenster-Guard verhindert Doppel-Posts, falls mehrere Trigger
(z.B. GitHub-Cron + externer Dienst) denselben Stunden-Slot feuern.
Zugangsdaten kommen ausschliesslich aus GitHub Actions Secrets (Env-Vars).
"""
import json, os, sys, time
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TRIAL_STATE_FILE = os.path.join(REPO_ROOT, "trial_state.json")

GRAPH_BASE = "https://graph.facebook.com/v20.0"
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300
PAUSE_BETWEEN_POSTS_S = 45

# Auf 1 Reel/Trigger reduziert (Yves' Entscheidung, 09.09.26, wegen Trial-Reel-Limit).
REELS_PER_TRIGGER = 1

# Doppel-Trigger-Guard: liegt der letzte Trial-Post weniger als so viele
# Minuten zurueck, wird dieser Lauf uebersprungen (statt doppelt zu posten).
MIN_MINUTES_BETWEEN_POSTS = 45


def reels_per_trigger(today=None):
    return REELS_PER_TRIGGER


def next_available(state, hosted, captions):
    """Liefert die naechste vorhandene Reel-Nummer und ueberspringt Luecken in
    der Nummerierung (z.B. fehlt #46). Ohne das Ueberspringen bleibt der
    Zaehler an der ersten Luecke haengen und die Pipeline postet nie wieder.
    None, wenn hinter der aktuellen Position nichts mehr kommt."""
    highest = max(int(k) for k in hosted)
    while state["next_reel"] <= highest:
        nr = f"{state['next_reel']:02d}"
        if nr in hosted and nr in captions:
            return nr
        print(f"Nummer {nr} fehlt im Pool - uebersprungen.")
        state["next_reel"] += 1
    return None


def load_json(name):
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def save_json(name, data):
    with open(os.path.join(REPO_ROOT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def poll_status(creation_id, token):
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        r = requests.get(f"{GRAPH_BASE}/{creation_id}",
                          params={"fields": "status_code", "access_token": token}, timeout=30)
        r.raise_for_status()
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Verarbeitung fehlgeschlagen: {creation_id}")
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"Timeout bei {creation_id}")


def post_instagram_trial(ig_user_id, token, video_url, caption):
    data = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "trial_params": json.dumps({"graduation_strategy": "MANUAL"}),
        "access_token": token,
    }
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
    if not r.ok:
        print("Graph-API-Fehler (media):", r.status_code, r.text)
    r.raise_for_status()
    creation_id = r.json()["id"]
    poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    if not r.ok:
        print("Graph-API-Fehler (media_publish):", r.status_code, r.text)
    r.raise_for_status()
    return r.json()["id"]


def record_trial(trial_state, media_id, reel_nr):
    trial_state[media_id] = {
        "reel_nr": reel_nr,
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "reach": None,
    }


def post_facebook_video(page_id, token, video_url, caption):
    data = {
        "file_url": video_url,
        "description": caption,
        "access_token": token,
    }
    r = requests.post(f"{GRAPH_BASE}/{page_id}/videos", data=data, timeout=120)
    r.raise_for_status()
    return r.json().get("id")


def post_one(reel_nr, hosted, captions, ig_user_id, ig_token, do_facebook, fb_page_id, fb_token,
             trial_state):
    video_url = hosted[reel_nr]
    caption = captions[reel_nr]

    print(f"[{reel_nr}] Posting Instagram Trial Reel...")
    media_id = post_instagram_trial(ig_user_id, ig_token, video_url, caption)
    print(f"[{reel_nr}] Instagram OK: media_id={media_id}")
    record_trial(trial_state, media_id, reel_nr)

    if do_facebook and fb_page_id and fb_token:
        try:
            fb_id = post_facebook_video(fb_page_id, fb_token, video_url, caption)
            print(f"[{reel_nr}] Facebook OK: video_id={fb_id}")
        except Exception as e:
            print(f"[{reel_nr}] Facebook Crosspost fehlgeschlagen (Instagram lief trotzdem durch): {e}")


def main():
    ig_user_id = os.environ["IG_USER_ID"]
    ig_token = os.environ["IG_ACCESS_TOKEN"]
    fb_page_id = os.environ.get("FB_PAGE_ID")
    fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    do_facebook = os.environ.get("CROSSPOST_FACEBOOK", "false").lower() == "true"

    batch_size = reels_per_trigger()
    print(f"Reels in diesem Lauf (Ramp-Stand): {batch_size}")

    state = load_json("state.json")
    hosted = load_json("hosted_urls.json")
    captions = load_json("captions_all.json")
    trial_state = load_json("trial_state.json") if os.path.exists(TRIAL_STATE_FILE) else {}

    # Doppel-Trigger-Guard (GitHub-Cron + evtl. externer Trigger im selben Slot)
    last_posted = max((e.get("posted_at") for e in trial_state.values() if e.get("posted_at")),
                      default=None)
    if last_posted:
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(last_posted)).total_seconds() / 60
        if age_min < MIN_MINUTES_BETWEEN_POSTS:
            print(f"Letzter Trial-Post liegt erst {age_min:.0f} min zurueck "
                  f"(< {MIN_MINUTES_BETWEEN_POSTS} min) - Doppel-Trigger, ueberspringe Lauf.")
            return

    posted_this_run = 0
    for i in range(batch_size):
        reel_nr = next_available(state, hosted, captions)
        if reel_nr is None:
            print("Pool erschoepft, kein weiterer Reel vorhanden. Stoppe.")
            break

        post_one(reel_nr, hosted, captions, ig_user_id, ig_token, do_facebook, fb_page_id, fb_token,
                  trial_state)

        state["posted"].append(reel_nr)
        state["next_reel"] += 1
        posted_this_run += 1

        if i < batch_size - 1:
            time.sleep(PAUSE_BETWEEN_POSTS_S)

    save_json("state.json", state)
    save_json("trial_state.json", trial_state)
    print(f"Lauf beendet: {posted_this_run} Reel(s) gepostet. Naechster Reel: {state['next_reel']:02d}")


if __name__ == "__main__":
    main()
