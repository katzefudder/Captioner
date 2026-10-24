"""Replace a file atomically, even while Windows is locking it (no Qt)."""
import os
import sys
import time

# Explorer (preview), virus scanners, the indexing service or Lightroom often keep a file
# open briefly on Windows; os.replace then fails with PermissionError. Retry a few times,
# then give up. This does not happen on macOS/Linux.
ATTEMPTS = 10 if sys.platform == 'win32' else 1
DELAY = 0.2


def replace_file(source, target):
    """os.replace, retried on PermissionError; after that the last error."""
    for attempt in range(ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(DELAY)
