#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (Cron). Antwortet auf neue Kommentare unter den
eigenen Reels/Posts mit einer neutralen, freundlichen Antwort, passend zur
Art des Kommentars (Frage / kurz-positiv / generisch).
Braucht instagram_manage_comments auf dem Token.
"""
import json, os, re, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
REPLIED_FILE = os.path.join(REPO_ROOT, "replied_comments.json")
RECENT_FILE = os.path.join(REPO_ROOT, "recent_replies.json")
RECENT_MAX = 8

# Nur die juengsten Medien pruefen: neue Kommentare kommen praktisch nur auf
# aktuelle Posts. Ohne dieses Limit lief der Job ueber ALLE Medien des
# Accounts (2500+) und haengte sich regelmaessig in GitHubs 6h-Limit.
MEDIA_LIMIT = 30

GRAPH_BASE = "https://graph.facebook.com/v20.0"

# Neutrale, freundliche Antworten, ruhig und erwachsen, dezente Emojis.
GENERIC_TEMPLATES = [
    "Danke für deinen Kommentar 🙏",
    "Danke dir 🤍",
    "Freut mich, dass es dich erreicht ✨",
    "Danke fürs Anschauen 🙏",
    "Schön, dass du hier bist 🤍",
    "Danke für deine Zeit 🙏",
    "Das bedeutet mir was, danke 🤍",
    "Danke, dass du dir das angeschaut hast 🙏",
    "Schön, dass du reinschaust 🤍",
    "Danke, dass du dir die Zeit nimmst 🙏",
    "Freut mich sehr, danke dir 🤍",
    "Danke für dein Kommentar, gerne teilen, wenn's dir was gibt 🤍",
]

# Fuer sehr kurze Kommentare (Emoji-only, ein Wort, "top"/"nice"/"🔥" etc.)
SHORT_TEMPLATES = [
    "🙏",
    "🤍",
    "✨",
    "Danke dir 🙏",
    "🙏🤍",
    "Danke ✨",
]

# Fuer Kommentare mit Frage (enthaelt "?")
QUESTION_TEMPLATES = [
    "Gute Frage, schau ich mir an 🙏",
    "Danke fürs Nachfragen, melde mich dazu 🤍",
    "Guter Punkt, dazu bald mehr ✨",
    "Danke, gehe ich nach 🙏",
    "Schaue ich mir genauer an, danke dir 🤍",
]


def load_json_list(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return list(json.load(f))
    return []


def save_json_list(path, items):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def get_recent_media(ig_user_id, token):
    media_ids = []
    url = f"{GRAPH_BASE}/{ig_user_id}/media"
    params = {"fields": "id,timestamp", "limit": 100, "access_token": token}
    while url and len(media_ids) < MEDIA_LIMIT:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        media_ids.extend(m["id"] for m in payload.get("data", []))
        url = payload.get("paging", {}).get("next")
        params = None
    return media_ids[:MEDIA_LIMIT]


def get_comments(media_id, token):
    comments = []
    url = f"{GRAPH_BASE}/{media_id}/comments"
    params = {"fields": "id,text,username,from", "limit": 50, "access_token": token}
    while url:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        comments.extend(payload.get("data", []))
        url = payload.get("paging", {}).get("next")
        params = None
    return comments


def already_replied(comment_id, ig_user_id, token):
    """Fragt Instagram direkt, ob unter diesem Kommentar schon eine Antwort vom
    eigenen Account existiert. Das ist die verlaessliche Quelle, unabhaengig
    davon, ob replied_comments.json wegen ueberlappender Workflow-Laeufe
    (z.B. GitHub-Schedule + externer Trigger) noch nicht aktuell ist."""
    r = requests.get(f"{GRAPH_BASE}/{comment_id}/replies",
                      params={"fields": "id,from", "limit": 50, "access_token": token}, timeout=30)
    if r.status_code != 200:
        return False
    for reply in r.json().get("data", []):
        if str(reply.get("from", {}).get("id")) == str(ig_user_id):
            return True
    return False


def reply_to_comment(comment_id, token, message):
    r = requests.post(f"{GRAPH_BASE}/{comment_id}/replies",
                       data={"message": message, "access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json().get("id")


def classify(text):
    stripped = re.sub(r"[^\w]", "", text or "", flags=re.UNICODE)
    if "?" in (text or ""):
        return QUESTION_TEMPLATES
    if len(stripped) <= 3:
        return SHORT_TEMPLATES
    return GENERIC_TEMPLATES


def pick_template(comment_id, text, recent):
    pool = classify(text)
    candidates = [t for t in pool if t not in recent] or pool
    return candidates[hash(comment_id) % len(candidates)]


def main():
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    replied = set(load_json_list(REPLIED_FILE))
    recent = load_json_list(RECENT_FILE)
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
            if str(c.get("from", {}).get("id", "")) == str(ig_user_id):
                replied.add(cid)
                continue
            # Verlaessliche Quelle statt nur der lokalen Datei: erst bei Instagram
            # nachfragen, ob unter diesem Kommentar schon geantwortet wurde
            # (schuetzt vor Doppel-Antworten bei ueberlappenden Workflow-Laeufen).
            if already_replied(cid, ig_user_id, token):
                replied.add(cid)
                save_json_list(REPLIED_FILE, sorted(replied))
                continue
            message = pick_template(cid, c.get("text", ""), recent)
            try:
                reply_to_comment(cid, token, message)
                print(f"Beantwortet: {cid} -> '{message}'")
                new_replies += 1
                recent.append(message)
                recent = recent[-RECENT_MAX:]
            except requests.HTTPError as e:
                print(f"Antwort fehlgeschlagen fuer {cid}: {e}")
            replied.add(cid)
            # Nach jeder Antwort sichern, damit ein Abbruch mitten im Lauf
            # (z.B. Cancel, Timeout) keine bereits gesendeten Antworten verliert
            # und beim naechsten Lauf keine Doppel-Antworten entstehen.
            save_json_list(REPLIED_FILE, sorted(replied))
            save_json_list(RECENT_FILE, recent)
            time.sleep(10)

    # Immer speichern, damit beide State-Dateien existieren und der
    # Commit-Schritt im Workflow sie bedingungslos adden kann.
    save_json_list(REPLIED_FILE, sorted(replied))
    save_json_list(RECENT_FILE, recent)
    print(f"Fertig. {new_replies} neue Antworten gepostet.")


if __name__ == "__main__":
    main()
