#!/usr/bin/env python3
"""
Manuelles Test-Posting fuer neue Format-Typen (Story, Karussell, normaler Post).
Getrennt von automation/post_daily.py (Trial-Reel-Ramp), damit die produktive
Pipeline unberuehrt bleibt. Nur ueber workflow_dispatch, kein Schedule.
Story-Umfrage-Sticker sind ueber die Graph API nicht moeglich (Meta erlaubt
interaktive Sticker nur manuell in der App).
"""
import os, time
import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300


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


def is_video_url(url):
    return url.lower().split("?")[0].endswith((".mp4", ".mov"))


def post_story(ig_user_id, token, media_url):
    video = is_video_url(media_url)
    data = {"media_type": "STORIES", "access_token": token}
    data["video_url" if video else "image_url"] = media_url
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
    check(r)
    creation_id = r.json()["id"]
    if video:
        poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    check(r)
    return r.json()["id"]


def post_carousel(ig_user_id, token, media_urls, caption):
    child_ids = []
    for url in media_urls:
        video = is_video_url(url)
        data = {"is_carousel_item": "true", "access_token": token}
        data["video_url" if video else "image_url"] = url
        r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
        check(r)
        cid = r.json()["id"]
        if video:
            poll_status(cid, token)
        child_ids.append(cid)
        print("child ok:", cid)

    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data={
        "media_type": "CAROUSEL",
        "caption": caption,
        "children": ",".join(child_ids),
        "access_token": token,
    }, timeout=60)
    check(r)
    creation_id = r.json()["id"]
    poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    check(r)
    return r.json()["id"]


def post_normal(ig_user_id, token, media_url, caption):
    video = is_video_url(media_url)
    data = {"caption": caption, "access_token": token}
    if video:
        data["media_type"] = "REELS"
        data["video_url"] = media_url
    else:
        data["image_url"] = media_url
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
    check(r)
    creation_id = r.json()["id"]
    poll_status(creation_id, token)
    r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    check(r)
    return r.json()["id"]


def main():
    post_type = os.environ["POST_TYPE"]
    ig_user_id = os.environ["IG_USER_ID"]
    ig_token = os.environ["IG_ACCESS_TOKEN"]
    media_urls = [u.strip() for u in os.environ.get("MEDIA_URLS", "").split(",") if u.strip()]
    caption = os.environ.get("CAPTION", "")

    if not media_urls:
        raise SystemExit("MEDIA_URLS ist leer")

    if post_type == "story":
        media_id = post_story(ig_user_id, ig_token, media_urls[0])
        print("Story OK, media_id:", media_id)
    elif post_type == "carousel":
        if len(media_urls) < 2:
            raise SystemExit("Karussell braucht mindestens 2 MEDIA_URLS")
        media_id = post_carousel(ig_user_id, ig_token, media_urls, caption)
        print("Carousel OK, media_id:", media_id)
    elif post_type == "normal":
        media_id = post_normal(ig_user_id, ig_token, media_urls[0], caption)
        print("Normal Post OK, media_id:", media_id)
    else:
        raise SystemExit(f"Unbekannter POST_TYPE: {post_type}")


if __name__ == "__main__":
    main()
