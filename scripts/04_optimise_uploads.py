#!/usr/bin/env python3
#
# Reduce the size of images, while maintaining comparable visual quality
# by converting to WebP. This will update references.
#
# Requires "cwebp" and ImageMagick installed for converting images.
#
# The original images are replaced with optimised WebP versions, and will update references in JSON files.
# Images that fail to convert or were already converted are skipped.
#
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JSON_DIR = REPO_ROOT / "json"
UPLOADS_DIR = REPO_ROOT / "uploads"

WEBP_QUALITY = 90
UPLOAD_REFERENCE_PATTERN = re.compile(r"/uploads/[A-Za-z0-9._-]+")
CWEBP_FORMATS = {".jpg", ".jpeg", ".png"}
MAGICK_FORMATS = {".gif"}


def convert_images():
    """Convert uploaded images and return reference replacements and sources."""
    replacements = {}
    sources = []

    for source in sorted(UPLOADS_DIR.iterdir()):
        extension = source.suffix.lower()
        if not source.is_file() or extension not in CWEBP_FORMATS | MAGICK_FORMATS:
            continue

        destination = source.with_suffix(".webp")
        if destination.exists():
            replacements[f"/uploads/{source.name}"] = f"/uploads/{destination.name}"
            sources.append(source)
            continue

        with tempfile.NamedTemporaryFile(dir=UPLOADS_DIR, suffix=".webp", delete=False) as file:
            temporary = Path(file.name)

        if extension in CWEBP_FORMATS:
            command = ["cwebp", "-quiet", "-q", str(WEBP_QUALITY), str(source), "-o", str(temporary)]
        elif shutil.which("magick"):
            image = f"{source}[0]" if extension == ".ico" else str(source)
            command = ["magick", image, "-quality", str(WEBP_QUALITY), str(temporary)]
        else:
            temporary.unlink()
            print(f"Skipping {source.name}: ImageMagick is required", file=sys.stderr)
            continue

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            os.chmod(temporary, source.stat().st_mode & 0o777)
            os.replace(temporary, destination)
        except (OSError, subprocess.CalledProcessError) as error:
            temporary.unlink(missing_ok=True)
            print(f"Skipping {source.name}: {error}", file=sys.stderr)
            continue

        replacements[f"/uploads/{source.name}"] = f"/uploads/{destination.name}"
        sources.append(source)
        print(f"Converted {source.name} -> {destination.name}")

    return replacements, sources


def rewrite_json(path, replacements):
    """Rewrite references a line at a time instead of loading the whole file."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        with path.open(encoding="utf-8", newline="") as source:
            for line in source:
                file.write(UPLOAD_REFERENCE_PATTERN.sub(lambda match: replacements.get(match.group(), match.group()), line))

    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.replace(temporary, path)


def main():
    if not shutil.which("cwebp"):
        sys.exit("cwebp is required; install the webp package first.")

    replacements, sources = convert_images()
    if not replacements:
        print("No images to convert.")
        return

    json_paths = sorted(JSON_DIR.glob("*.json"))
    manifest = UPLOADS_DIR / "uploads.json"
    if manifest.exists():
        json_paths.append(manifest)

    print(f"Updating references in {len(json_paths)} JSON files...")
    for path in json_paths:
        rewrite_json(path, replacements)

    for source in sources:
        source.unlink()

    print(f"Converted {len(replacements):,} images and removed the originals.")


if __name__ == "__main__":
    main()
