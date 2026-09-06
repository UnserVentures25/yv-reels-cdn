#!/usr/bin/env python3
"""
Läuft in GitHub Actions (Cron). Postet den naechsten Reel aus state.json
als Instagram Trial Reel, optional als Facebook-Video-Crosspost.
Zugangsdaten kommen ausschliesslich aus GitHub Actions Secrets (Env-Vars).
"""
import json, os, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

GRAPH_BASE = "https://graph.facebook.com/v20.0"
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300


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
    r.raise_for_status()
    creation_id = r.json()["id"]
    poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def post_facebook_video(page_id, token, video_url, caption):
    data = {
        "file_url": video_url,
        "description": caption,
        "access_token": token,
    }
    r = requests.post(f"{GRAPH_BASE}/{page_id}/videos", data=data, timeout=120)
    r.raise_for_status()
    return r.json().get("id")


def main():
    ig_user_id = os.environ["IG_USER_ID"]
    ig_token = os.environ["IG_ACCESS_TOKEN"]
    fb_page_id = os.environ.get("FB_PAGE_ID")
    fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    do_facebook = os.environ.get("CROSSPOST_FACEBOOK", "false").lower() == "true"

    state = load_json("state.json")
    hosted = load_json("hosted_urls.json")
    captions = load_json("captions_all.json")

    reel_nr = f"{state['next_reel']:02d}"
    if reel_nr not in hosted:
        print(f"Kein weiterer Reel vorhanden (naechste Nummer {reel_nr} nicht in hosted_urls.json). Stoppe.")
        return

    video_url = hosted[reel_nr]
    caption = captions[reel_nr]

    print(f"[{reel_nr}] Posting Instagram Trial Reel...")
    media_id = post_instagram_trial(ig_user_id, ig_token, video_url, caption)
    print(f"[{reel_nr}] Instagram OK: media_id={media_id}")

    if do_facebook and fb_page_id and fb_token:
        try:
            fb_id = post_facebook_video(fb_page_id, fb_token, video_url, caption)
            print(f"[{reel_nr}] Facebook OK: video_id={fb_id}")
        except Exception as e:
            print(f"[{reel_nr}] Facebook Crosspost fehlgeschlagen (Instagram lief trotzdem durch): {e}")

    state["posted"].append(reel_nr)
    state["next_reel"] += 1
    save_json("state.json", state)
    print(f"[{reel_nr}] state.json aktualisiert, naechster Reel: {state['next_reel']:02d}")


if __name__ == "__main__":
    main()
