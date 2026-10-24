"""
New version on GitHub? Without Qt: URL, parsing, comparison. The UI does the networking.

Releases are named v<major>.<minor>.<run number> (see .github/workflows/release.yml).
A private repository answers 404 without login: then there is simply no notice.
"""
import re
import time

LATEST_URL = 'https://api.github.com/repos/katzefudder/Captioner/releases/latest'
RELEASES_PAGE = 'https://github.com/katzefudder/Captioner/releases'
INTERVAL_SECONDS = 24 * 60 * 60


def parse_version(text):
    """'v0.1.20' -> (0, 1, 20); no version number -> None."""
    match = re.match(r'^v?(\d+(?:\.\d+)*)$', (text or '').strip())
    return tuple(int(part) for part in match.group(1).split('.')) if match else None


def is_newer(latest, current):
    latest, current = parse_version(latest), parse_version(current)
    return bool(latest and current and latest > current)


def parse_release(data):
    """GitHub response -> (version without 'v', release page) or None."""
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name') or ''
    if parse_version(tag) is None:
        return None
    return tag.lstrip('v'), data.get('html_url') or RELEASES_PAGE


def due(last_check, now=None):
    now = time.time() if now is None else now
    return not last_check or now - last_check >= INTERVAL_SECONDS
