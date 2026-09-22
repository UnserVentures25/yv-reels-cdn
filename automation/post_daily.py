#!/usr/bin/env python3
"""
Laeuft in GitHub Actions (stuendlicher Cron in daily-trial-reels.yml).
Postet pro Aufruf 1 Reel aus state.json als Instagram Trial Reel,
optional als Facebook-Video-Crosspost.
Ein Zeitfenster-Guard verhindert Doppel-Posts, falls mehrere Trigger
(z.B. GitHub-Cron + externer Dienst) denselben Stunden-Slot feuern.
Zugangsdaten kommen ausschliesslich aus GitHub Actions Secrets (Env-Vars).
"""
import json, os, random, sys, time
from datetime import datetime, timedelta, timezone
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

# Doppel-Trigger-Guard: liegt der letzte Trial-Post ODER -Versuch weniger als
# so viele Minuten zurueck, wird dieser Lauf uebersprungen.
# Mindestens 10 h Abstand (17.09.26, war 2 h). Der externe Stunden-Dispatcher
# ist weiterhin nicht gefunden - der Guard muss ihn allein abfangen.
MIN_MINUTES_BETWEEN_POSTS = 600

# Harte Obergrenze im rollierenden 24-h-Fenster. 1 statt 5 (17.09.26):
# Die Insights-Auswertung vom 17.09. zeigt Median-Reach 1.407 bei 1-2 Posts/Tag
# gegen 120 bei 5-9 Posts/Tag - Faktor 9. Zusammen mit den zwei Slots aus
# scheduled-posting.py bleibt der Account damit bei hoechstens 3 Posts/Tag.
# Ohne Cap kam der Stunden-Dispatcher auf 17 und lief in Metas Trial-Reel-Limit.
MAX_POSTS_PER_24H = 1

# Metas Fehler-Subcode fuer das Trial-Reel-Limit: erwartete Drosselung, kein Bug.
TRIAL_LIMIT_SUBCODE = 2207078


class TrialLimitReached(Exception):
    """Meta lehnt media_publish wegen des Trial-Reel-Limits ab."""


def _ist_trial_limit(response):
    try:
        err = response.json().get("error", {})
    except ValueError:
        return False
    return err.get("code") == 9 and err.get("error_subcode") == TRIAL_LIMIT_SUBCODE


def _zeitstempel(trial_state, *felder):
    """Alle gesetzten Zeitstempel aus trial_state als datetime-Liste."""
    out = []
    for e in trial_state.values():
        for f in felder:
            if e.get(f):
                out.append(datetime.fromisoformat(e[f]))
    return out


def reels_per_trigger(today=None):
    return REELS_PER_TRIGGER


def next_available(state, hosted, captions):
    """Waehlt zufaellig einen noch nicht geposteten Reel aus dem Pool.
    Zufall statt Reihenfolge, damit das Profil nicht thematisch blockweise
    aussieht und aeltere Reels dieselbe Chance haben wie neue.
    None, wenn alle Reels durch sind."""
    posted = set(state.get("posted", []))
    kandidaten = sorted(nr for nr in hosted if nr in captions and nr not in posted)
    if not kandidaten:
        print("Alle Reels aus dem Pool sind gepostet.")
        return None
    nr = random.choice(kandidaten)
    print(f"Zufallsauswahl: Reel {nr} aus {len(kandidaten)} verfuegbaren.")
    return nr


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
        if _ist_trial_limit(r):
            raise TrialLimitReached(r.text)
    r.raise_for_status()
    return r.json()["id"]


def record_trial(trial_state, media_id, reel_nr):
    trial_state[media_id] = {
        "reel_nr": reel_nr,
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "reach": None,
    }


def record_attempt(trial_state, reel_nr, grund):
    """Fehlversuch protokollieren, damit der Guard ihn sieht. Status != pending,
    darum ignoriert evaluate_reels.py den Eintrag."""
    ts = datetime.now(timezone.utc)
    trial_state[f"failed_{reel_nr}_{int(ts.timestamp())}"] = {
        "reel_nr": reel_nr,
        "attempted_at": ts.isoformat(),
        "status": "failed",
        "grund": grund,
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

    now = datetime.now(timezone.utc)

    # Cap im rollierenden 24-h-Fenster. Bremst auch Trigger, die den
    # Cron-Rhythmus ignorieren (externer Stunden-Dispatch, 16.09.26).
    im_fenster = [t for t in _zeitstempel(trial_state, "posted_at") if now - t < timedelta(hours=24)]
    if len(im_fenster) >= MAX_POSTS_PER_24H:
        frei_ab = min(im_fenster) + timedelta(hours=24)
        print(f"{len(im_fenster)} Trial Reels in den letzten 24 h (Cap {MAX_POSTS_PER_24H}) "
              f"- ueberspringe Lauf. Naechster Slot frei ab "
              f"{frei_ab.isoformat(timespec='minutes')}.")
        return

    # Doppel-Trigger-Guard: zaehlt auch Fehlversuche mit. Ohne das legt ein
    # stuendlicher Trigger nach jedem Fehlschlag sofort wieder los.
    letzte_aktion = max(_zeitstempel(trial_state, "posted_at", "attempted_at"), default=None)
    if letzte_aktion:
        age_min = (now - letzte_aktion).total_seconds() / 60
        if age_min < MIN_MINUTES_BETWEEN_POSTS:
            print(f"Letzter Trial-Post/-Versuch liegt erst {age_min:.0f} min zurueck "
                  f"(< {MIN_MINUTES_BETWEEN_POSTS} min) - ueberspringe Lauf.")
            return

    posted_this_run = 0
    for i in range(batch_size):
        reel_nr = next_available(state, hosted, captions)
        if reel_nr is None:
            print("Pool erschoepft, kein weiterer Reel vorhanden. Stoppe.")
            break

        try:
            post_one(reel_nr, hosted, captions, ig_user_id, ig_token, do_facebook, fb_page_id,
                     fb_token, trial_state)
        except TrialLimitReached:
            # Erwartete Drosselung, kein Bug: Versuch protokollieren, State
            # sichern, sauber beenden. next_reel bleibt stehen, der Reel geht
            # im naechsten freien Slot raus.
            record_attempt(trial_state, reel_nr, "trial_limit")
            save_json("state.json", state)
            save_json("trial_state.json", trial_state)
            print(f"[{reel_nr}] Metas Trial-Reel-Limit erreicht - Lauf sauber beendet. "
                  f"Naechster Versuch fruehestens in {MIN_MINUTES_BETWEEN_POSTS} min.")
            return

        state["posted"].append(reel_nr)
        posted_this_run += 1

        if i < batch_size - 1:
            time.sleep(PAUSE_BETWEEN_POSTS_S)

    save_json("state.json", state)
    save_json("trial_state.json", trial_state)
    print(f"Lauf beendet: {posted_this_run} Reel(s) gepostet. {len(state.get('posted', []))} insgesamt durch.")


if __name__ == "__main__":
    main()
