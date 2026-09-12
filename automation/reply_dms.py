#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (Cron). Beantwortet neue eingehende Instagram-DMs
einmalig pro Absender mit einer festen Nachricht. Braucht
instagram_manage_messages auf dem Token (zusaetzlich zu den bestehenden
Scopes fuer Posting/Kommentare).
"""
import json, os, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
REPLIED_FILE = os.path.join(REPO_ROOT, "dm_replied.json")

GRAPH_BASE = "https://graph.facebook.com/v20.0"

MESSAGE_TEXT = (
    "Hey, how are you? \U0001F60A I hope you're doing well!\n\n"
    "Thanks for being around. My AI clone is replying right now, but I'm trying "
    "to read your message personally and reply myself as soon as I can. "
    "It's on my list! \U0001F64F\n\n"
    "How can I help you? What's going on in your life at the moment? "
    "Feel free to let me know.\n\n"
    "And could you do me a little favor? It would honestly mean a lot to me. "
    "I'm competing for the Mister Universe title in November, representing Serbia \U0001F1F7\U0001F1F8.\n\n"
    "If you have a moment, I'd really appreciate your vote:\n"
    "https://misteruniverse.1voting.com/candidate/bx39v/yves%E2%80%93len-unser-Rd6z\n\n"
    "Thank you so much! ❤️"
)


def load_json_set(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_json_set(path, items):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(items), f, ensure_ascii=False, indent=2)


def get_conversations(ig_user_id, token, page_id=None):
    """Conversations haengen bei Meta am Page-Objekt. Wir versuchen erst die
    IG-User-ID; schlaegt das fehl und FB_PAGE_ID ist gesetzt, fallen wir
    darauf zurueck."""
    last_err = None
    for owner_id in [ig_user_id] + ([page_id] if page_id else []):
        conversations = []
        url = f"{GRAPH_BASE}/{owner_id}/conversations"
        params = {"platform": "instagram", "fields": "id,updated_time",
                  "limit": 50, "access_token": token}
        try:
            while url:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                payload = r.json()
                conversations.extend(payload.get("data", []))
                url = payload.get("paging", {}).get("next")
                params = None
            return conversations
        except requests.HTTPError as e:
            print(f"Conversations ueber {owner_id} fehlgeschlagen: {e}")
            last_err = e
    raise last_err


def get_last_message(conversation_id, ig_user_id, token):
    """Liefert die Absender-ID der letzten Nachricht, oder None wenn die
    letzte Nachricht bereits vom eigenen Account kam."""
    r = requests.get(
        f"{GRAPH_BASE}/{conversation_id}",
        params={"fields": "messages.limit(1){id,from}", "access_token": token},
        timeout=30,
    )
    r.raise_for_status()
    messages = r.json().get("messages", {}).get("data", [])
    if not messages:
        return None
    sender_id = str(messages[0].get("from", {}).get("id", ""))
    if sender_id == str(ig_user_id):
        return None
    return sender_id


def send_message(ig_user_id, token, recipient_id, text):
    r = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/messages",
        data={
            "recipient": json.dumps({"id": recipient_id}),
            "message": json.dumps({"text": text}),
            "access_token": token,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main():
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]
    page_id = os.environ.get("FB_PAGE_ID")

    replied = load_json_set(REPLIED_FILE)
    new_replies = 0

    for conv in get_conversations(ig_user_id, token, page_id=page_id):
        try:
            sender_id = get_last_message(conv["id"], ig_user_id, token)
        except requests.HTTPError as e:
            print(f"Konnte Conversation {conv['id']} nicht laden: {e}")
            continue

        if not sender_id or sender_id in replied:
            continue

        try:
            send_message(ig_user_id, token, sender_id, MESSAGE_TEXT)
            print(f"Beantwortet: {sender_id}")
            new_replies += 1
        except requests.HTTPError as e:
            print(f"Antwort fehlgeschlagen fuer {sender_id}: {e}")
            continue

        replied.add(sender_id)
        # Nach jeder Antwort sichern, damit ein Abbruch mitten im Lauf keine
        # bereits gesendeten Antworten verliert und keine Doppel-Antworten
        # beim naechsten Lauf entstehen.
        save_json_set(REPLIED_FILE, replied)
        time.sleep(5)

    print(f"Fertig. {new_replies} neue DM-Antworten gesendet.")


if __name__ == "__main__":
    main()
