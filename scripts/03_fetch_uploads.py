#!/usr/bin/env python3
#
# With the original Discourse instance running, fetch images remotely.
# Discourse backups do include a copy of "uploads", but these are missing
# custom icons, avatars, emojis, etc.
#
# This script will:
# - Name these files by their MD5 checksum to deduplicate files.
# - Skip downloads that were already downloaded.
# - Rewrite JSON to point to the local upload path.
#
import hashlib
import http.client
import json
import mimetypes
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REMOTE_URL = "https://ubuntu-mate.community"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

JSON_DIR = Path(__file__).resolve().parent.parent / "json"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"

# Tracks path -> local /uploads/<md5>.ext (or None if it failed), so a crashed
# or interrupted run can be re-started without re-fetching everything.
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "uploads" / "uploads.json"
MANIFEST_SAVE_INTERVAL = 100

# Matches asset paths, optionally prefixed with REMOTE_URL:
# - /uploads/...       user-uploaded files (images, attachments)
# - /user_avatar/...   dynamically-resized avatar thumbnails
# - /images/emoji/...  built-in "baked" emoji images
# The negative lookbehind stops this matching "/uploads/..." embedded mid-path
# inside unrelated third-party URLs, e.g. "https://example.com/wp-content/uploads/...".
# Also excludes brackets/braces and common prose/BBCode punctuation that can
# trail a URL in raw text (e.g. "...jpg[/img]" or "...png,"), none of which
# ever appear inside a genuine Discourse asset path.
ASSET_URL_PATTERN = re.compile(
    r"(?<!\w)(?:" + re.escape(REMOTE_URL) + r")?(/(?:uploads|user_avatar|images/emoji)/[^\"'\s<>()\[\]{},;:!?]+)"
)


def find_asset_paths(value, found):
    """Recursively collect every unique asset path referenced in a JSON value."""
    if isinstance(value, str):
        found.update(match.group(1) for match in ASSET_URL_PATTERN.finditer(value))
    elif isinstance(value, list):
        for item in value:
            find_asset_paths(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            find_asset_paths(item, found)


def fetch_asset(path, manifest):
    """
    Download an asset and name it by its MD5 checksum, to deduplicate identical files.

    Assets that fail to download (including 404s) are recorded as None, so the
    reference gets stripped from the JSON rather than left pointing at the live server.
    """
    if path in manifest:
        return

    request = urllib.request.Request(REMOTE_URL + urllib.parse.quote(path, safe="/:?=&%"), headers={"User-Agent": USER_AGENT})

    content = None
    content_type = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request) as response:
                content = response.read()
                content_type = response.headers.get_content_type()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(" ... 404 not found, removed.\n")
                manifest[path] = None
                return
            if attempt == MAX_RETRIES:
                print(f" ... failed to fetch: {e}\n")
                manifest[path] = None
                return
            time.sleep(RETRY_DELAY_SECONDS * attempt)
        except urllib.error.URLError as e:
            if attempt == MAX_RETRIES:
                print(f" ... failed to fetch: {e}\n")
                manifest[path] = None
                return
            time.sleep(RETRY_DELAY_SECONDS * attempt)
        except http.client.HTTPException as e:
            if attempt == MAX_RETRIES:
                print(f" ... failed to fetch: {e}\n")
                manifest[path] = None
                return
            time.sleep(RETRY_DELAY_SECONDS * attempt)

    # Some paths (e.g. Discourse's short-url attachment links) have no extension.
    ext = Path(path.split("?", 1)[0]).suffix or mimetypes.guess_extension(content_type or "") or ""
    filename = f"{hashlib.md5(content).hexdigest()}{ext}"
    dest = UPLOADS_DIR / filename
    if not dest.exists():
        dest.write_bytes(content)

    manifest[path] = f"/uploads/{filename}"


def print_progress(i, total, url):
    """Print a self-clearing \"File i of total: url\" progress line."""
    line = f"File {i} of {total}: {url}"
    width = shutil.get_terminal_size((80, 20)).columns
    line = line[:width] if len(line) > width else line.ljust(width)
    print(f"\r{line}", end="", flush=True)


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def rewrite(value, manifest):
    """Recursively rewrite every asset reference in a JSON value to its local path,
    removing any that failed to download."""
    if isinstance(value, str):
        return ASSET_URL_PATTERN.sub(lambda m: manifest.get(m.group(1), m.group(1)) or "", value)
    if isinstance(value, list):
        return [rewrite(item, manifest) for item in value]
    if isinstance(value, dict):
        return {key: rewrite(item, manifest) for key, item in value.items()}
    return value


def main():
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    print(f"Resuming with {len(manifest):,} assets already recorded in {MANIFEST_PATH}")

    print("Reading references...")
    json_paths = sorted(JSON_DIR.glob("*.json"))
    documents = {}
    asset_paths = set()

    for path in json_paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        documents[path] = data
        find_asset_paths(data, asset_paths)

    asset_paths = sorted(asset_paths)
    total = len(asset_paths)
    print(f"Found {total:,} referenced assets across {len(json_paths)} JSON files.")

    for i, path in enumerate(asset_paths, start=1):
        print_progress(i, total, REMOTE_URL + path)
        fetch_asset(path, manifest)
        if i % MANIFEST_SAVE_INTERVAL == 0:
            save_manifest(manifest)
    print()
    save_manifest(manifest)

    for path, data in documents.items():
        data = rewrite(data, manifest)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    print("Done!")


if __name__ == "__main__":
    main()
