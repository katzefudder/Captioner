"""Datei atomar ersetzen, auch wenn Windows sie gerade sperrt (ohne Qt)."""
import os
import sys
import time

# Explorer (Vorschau), Virenscanner, Indexdienst oder Lightroom halten eine Datei unter
# Windows oft kurz offen; os.replace scheitert dann mit PermissionError. Ein paarmal
# nachfassen, dann aufgeben. Auf macOS/Linux tritt das nicht auf.
ATTEMPTS = 10 if sys.platform == 'win32' else 1
DELAY = 0.2


def replace_file(source, target):
    """os.replace mit Wiederholung bei PermissionError; danach der letzte Fehler."""
    for attempt in range(ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(DELAY)
