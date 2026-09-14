#!/usr/bin/env python3
"""
Upload neuer Medien ins CDN-Repo + Aufwaermen des jsDelivr-Caches.

Hintergrund (14.09.26): Der 10-Uhr-Karussell-Post fiel aus, weil Instagram
karussell5_K12_5.jpg nicht laden konnte (Graph 9004 / subcode 2207052).
Datei und Format waren einwandfrei — der jsDelivr-Cache war kalt, und Metas
Fetcher bricht ab, bevor jsDelivr die Datei von GitHub nachgeladen hat.

Regel: JEDE neue URL einmal komplett abrufen, BEVOR sie in carousel_pool.json
oder hosted_urls.json landet. Eine Stichprobe reicht nicht — genau so ist der
Ausfall entstanden.

Benutzung als Modul (aus Build-Skripten):
    from cdn_upload import publish
    urls = publish([(lokal, "karussell5_K17_1.jpg"), ...], "Karussell K17")

Benutzung als CLI:
    python3 automation/cdn_upload.py warm <url> [<url> ...]
    python3 automation/cdn_upload.py warm-pool   # alle URLs aus den Pool-JSONs
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

REPO = os.environ.get("CDN_REPO", "UnserVentures25/yv-reels-cdn")
CDN = f"https://cdn.jsdelivr.net/gh/{REPO}@main/"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARM_TRIES = 4
WARM_TIMEOUT_S = 60


def warm(urls, tries=WARM_TRIES):
    """Laedt jede URL einmal vollstaendig, damit jsDelivr sie im Cache hat."""
    failed = []
    for url in urls:
        for attempt in range(1, tries + 1):
            try:
                r = requests.get(url, timeout=WARM_TIMEOUT_S)
                size = len(r.content)
                if r.ok and size > 0:
                    print(f"  warm OK  {size:>9} B  {url}")
                    break
                reason = f"HTTP {r.status_code}, {size} B"
            except requests.RequestException as e:
                reason = type(e).__name__
            if attempt == tries:
                print(f"  warm FAIL ({reason}) {url}")
                failed.append(url)
            else:
                time.sleep(3 * attempt)
    if failed:
        raise RuntimeError(
            f"{len(failed)} URL(s) nicht aufwaermbar — NICHT in den Pool schreiben:\n"
            + "\n".join(failed))


def _gh(args, tries=4):
    for attempt in range(1, tries + 1):
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
        transient = any(s in r.stderr.lower() for s in
                        ("connection reset", "timeout", "eof", "502", "503", "504"))
        if not transient or attempt == tries:
            raise RuntimeError(r.stderr[:300])
        time.sleep(3 * attempt)


def remote_sha(path):
    r = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}", "--jq", ".sha"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _put(path, content_b64, message):
    body = {"message": message, "content": content_b64}
    sha = remote_sha(path)
    if sha:
        body["sha"] = sha
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f)
        tmp = f.name
    try:
        return _gh(["api", "-X", "PUT", f"repos/{REPO}/contents/{path}",
                    "--input", tmp, "--jq", ".commit.sha"])
    finally:
        os.unlink(tmp)


def upload(local_path, remote_name, message=None):
    """Laedt eine Datei ins Repo (idempotent, ueberschreibt per sha)."""
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    _put(remote_name, b64, message or f"Add {remote_name}")
    return CDN + remote_name


def put_json(remote_name, obj, message):
    b64 = base64.b64encode(
        json.dumps(obj, ensure_ascii=False, indent=2).encode()).decode()
    return _put(remote_name, b64, message)


def get_json(remote_name):
    return json.loads(base64.b64decode(
        _gh(["api", f"repos/{REPO}/contents/{remote_name}", "--jq", ".content"])))


def publish(files, message):
    """Upload + Cache-Warmup in einem Schritt.

    files: Liste von (lokaler_pfad, remote_name).
    Gibt {remote_name: url} zurueck — erst NACH erfolgreichem Warmup, sodass
    ein kalter Cache niemals in den Pool geschrieben werden kann.
    """
    urls = {}
    for local, remote in files:
        urls[remote] = upload(local, remote, f"{message}: {remote}")
        print(f"  upload OK  {remote}")
    print(f"Warmup {len(urls)} URL(s):")
    warm(list(urls.values()))
    return urls


def _pool_urls():
    urls = []
    for name in ("carousel_pool.json", "hosted_urls.json"):
        path = os.path.join(REPO_ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if name == "carousel_pool.json":
            for group in data.get("urls", {}).values():
                urls.extend(group)
        else:
            urls.extend(data.values())
    return urls


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("warm", "warm-pool"):
        raise SystemExit(__doc__)
    urls = _pool_urls() if sys.argv[1] == "warm-pool" else sys.argv[2:]
    if not urls:
        raise SystemExit("Keine URLs angegeben.")
    print(f"Warmup {len(urls)} URL(s):")
    warm(urls)
    print("Alle URLs im Cache.")


if __name__ == "__main__":
    main()
