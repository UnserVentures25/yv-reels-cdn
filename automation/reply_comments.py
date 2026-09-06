#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (Cron). Antwortet auf neue Kommentare unter den
eigenen Reels/Posts mit einer neutralen, freundlichen Antwort.
Braucht instagram_manage_comments auf dem Token.
"""
import json, os, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
REPLIED_FILE = os.path.join(REPO_ROOT, "replied_comments.json")

GRAPH_BASE = "https://graph.facebook.com/v20.0"

# Neutrale, freundliche Antworten, ruhig und erwachsen, keine Ausrufezeichen/Emojis.
TEMPLATES = [
    "Danke dir.",
    "Freut mich, dass es dich erreicht.",
    "Danke fürs Lesen.",
    "Schön, dass du hier bist.",
    "Danke für deine Zeit.",
    "Das bedeutet mir was, danke.",
    "Danke, dass du dir das angeschaut hast.",
    "Gut, dass es ankommt.",
]


def load_replied():
    if os.path.exists(REPLIED_FILE):
        with open(REPLIED_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_replied(replied_ids):
    with open(REPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(replied_ids), f, indent=2)


def get_recent_media(ig_user_id, token, limit=25):
    r = requests.get(f"{GRAPH_BASE}/{ig_user_id}/media",
                      params={"fields": "id,timestamp", "limit": limit, "access_token": token},
                      timeout=30)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def get_comments(media_id, token):
    r = requests.get(f"{GRAPH_BASE}/{media_id}/comments",
                      params={"fields": "id,text,username", "access_token": token},
                      timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def reply_to_comment(comment_id, token, message):
    r = requests.post(f"{GRAPH_BASE}/{comment_id}/replies",
                       data={"message": message, "access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json().get("id")


def pick_template(comment_id):
    return TEMPLATES[hash(comment_id) % len(TEMPLATES)]


def main():
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    replied = load_replied()
    new_replies = 0

    for media_id in get_recent_media(ig_user_id, token):
        try:
            comments = get_comments(media_id, token)
        except requests.HTTPError as e:
            print(f"Konnte Kommentare fuer {media_id} nicht laden: {e}")
            continue

        for c in comments:
            cid = c["id"]
            if cid in replied:
                continue
            if c.get("username", "").lower() == "yvesunser":
                replied.add(cid)
                continue
            message = pick_template(cid)
            try:
                reply_to_comment(cid, token, message)
                print(f"Beantwortet: {cid} -> '{message}'")
                new_replies += 1
            except requests.HTTPError as e:
                print(f"Antwort fehlgeschlagen fuer {cid}: {e}")
            replied.add(cid)
            time.sleep(2)

    save_replied(replied)
    print(f"Fertig. {new_replies} neue Antworten gepostet.")


if __name__ == "__main__":
    main()
