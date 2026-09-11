#!/usr/bin/env python3
"""
Geplantes Posting, 2x/Tag via GitHub-eigenem Cron (kein cron-job.org noetig):
- MODE=carousel (10 Uhr CEST): postet das naechste 5-Bild-Story-Karussell aus
  carousel_pool.json, zyklisch nach carousel_state.json.
- MODE=best_reel (14 Uhr CEST): postet den bestperformenden noch nicht so
  geposteten Trial-Reel als NORMALEN Post (kein Trial, kein Limit-Problem,
  da API-Graduierung von MANUAL-Trial-Reels technisch nicht moeglich ist).
"""
import json, os, time
import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300


def load_json(name):
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def save_json(name, data):
    with open(os.path.join(REPO_ROOT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check(r):
    if not r.ok:
        print("Graph-API-Fehler:", r.status_code, r.text)
    r.raise_for_status()
    return r


def poll_status(creation_id, token):
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        r = requests.get(f"{GRAPH_BASE}/{creation_id}",
                          params={"fields": "status_code", "access_token": token}, timeout=30)
        check(r)
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Verarbeitung fehlgeschlagen: {creation_id}")
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"Timeout bei {creation_id}")


def post_carousel(ig_user_id, token, media_urls, caption):
    child_ids = []
    for url in media_urls:
        data = {"is_carousel_item": "true", "media_type": "IMAGE", "image_url": url, "access_token": token}
        r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
        check(r)
        child_ids.append(r.json()["id"])
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media",
                       data={"media_type": "CAROUSEL", "caption": caption,
                             "children": ",".join(child_ids), "access_token": token}, timeout=60)
    check(r)
    creation_id = r.json()["id"]
    poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    check(r)
    return r.json()["id"]


def post_normal_reel(ig_user_id, token, video_url, caption):
    data = {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": token}
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
    check(r)
    creation_id = r.json()["id"]
    poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    check(r)
    return r.json()["id"]


def get_reach(media_id, token):
    r = requests.get(f"{GRAPH_BASE}/{media_id}/insights",
                      params={"metric": "reach", "access_token": token}, timeout=30)
    if not r.ok:
        return None
    data = r.json().get("data", [])
    if not data:
        return 0
    values = data[0].get("values", [])
    return values[0]["value"] if values else 0


def run_carousel(ig_user_id, token):
    pool = load_json("carousel_pool.json")
    state = load_json("carousel_state.json")
    order = state["order"]
    idx = state["next_index"] % len(order)
    k = order[idx]

    media_urls = pool["urls"][k]
    caption = pool["captions"][k]
    media_id = post_carousel(ig_user_id, token, media_urls, caption)
    print(f"Carousel {k} OK: media_id={media_id}")

    state["next_index"] = (idx + 1) % len(order)
    save_json("carousel_state.json", state)


def run_best_reel(ig_user_id, token):
    best_pool = load_json("best_reel_pool.json")  # {"09": media_id, "10": media_id, ...}
    posted = load_json("best_reel_posted.json") if os.path.exists(os.path.join(REPO_ROOT, "best_reel_posted.json")) else {"posted": []}
    hosted = load_json("hosted_urls.json")
    captions = load_json("captions_all.json")

    ranked = []
    for reel_nr, media_id in best_pool.items():
        if reel_nr in posted["posted"]:
            continue
        reach = get_reach(media_id, token)
        if reach is not None:
            ranked.append((reach, reel_nr))
    if not ranked:
        print("Kein unverbrauchter Reel mit Reach-Daten uebrig.")
        return

    ranked.sort(reverse=True)
    best_reach, best_nr = ranked[0]
    print(f"Bester noch nicht geposteter Reel: {best_nr}, reach={best_reach}")

    video_url = hosted[best_nr]
    caption = captions[best_nr]
    media_id = post_normal_reel(ig_user_id, token, video_url, caption)
    print(f"Best-Reel {best_nr} OK: media_id={media_id}")

    posted["posted"].append(best_nr)
    save_json("best_reel_posted.json", posted)


def main():
    mode = os.environ["MODE"]
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    if mode == "carousel":
        run_carousel(ig_user_id, token)
    elif mode == "best_reel":
        run_best_reel(ig_user_id, token)
    else:
        raise SystemExit(f"Unbekannter MODE: {mode}")


if __name__ == "__main__":
    main()
