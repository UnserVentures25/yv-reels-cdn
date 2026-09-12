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


def get_conversations(candidates):
    """Conversations haengen bei Meta am Page-Objekt und brauchen den
    Page Access Token. candidates ist eine Liste (owner_id, token);
    die erste funktionierende Kombination wird zurueckgegeben und fuer
    alle weiteren Calls dieses Laufs verwendet."""
    last_err = None
    for owner_id, token in candidates:
        if not owner_id or not token:
            continue
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
            return conversations, owner_id, token
        except requests.HTTPError as e:
            print(f"Conversations ueber {owner_id} fehlgeschlagen: {e}")
            last_err = e
    raise last_err


def get_last_message(conversation_id, own_ids, token):
    """Liefert die Absender-ID der letzten Nachricht, oder None wenn die
    letzte Nachricht bereits vom eigenen Account/der eigenen Page kam."""
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
    if sender_id in own_ids:
        return None
    return sender_id


def send_message(owner_id, token, recipient_id, text):
    r = requests.post(
        f"{GRAPH_BASE}/{owner_id}/messages",
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
    ig_token = os.environ["IG_ACCESS_TOKEN"]
    page_id = os.environ.get("FB_PAGE_ID")
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")

    replied = load_json_set(REPLIED_FILE)
    new_replies = 0

    conversations, owner_id, token = get_conversations([
        (page_id, page_token),
        (ig_user_id, ig_token),
        (page_id, ig_token),
    ])
    print(f"Conversations geladen ueber {owner_id}: {len(conversations)}")
    own_ids = {str(ig_user_id)} | ({str(page_id)} if page_id else set())

    for conv in conversations:
        try:
            sender_id = get_last_message(conv["id"], own_ids, token)
        except requests.HTTPError as e:
            print(f"Konnte Conversation {conv['id']} nicht laden: {e}")
            continue

        if not sender_id or sender_id in replied:
            continue

        try:
            send_message(owner_id, token, sender_id, MESSAGE_TEXT)
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
