"""
ExifTool als dauerhafter Prozess (-stay_open), nicht ein Prozess pro Datei.

Sonst kostet allein der Perl-Start pro Bild mehr als das Auslesen der Vorschau
(ADR 0001, Punkt 2). Eine Instanz ist nicht threadsicher; ExifToolPool gibt
jedem Thread seine eigene.
"""
import json
import logging
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# ExifTool beendet sich im -stay_open-Modus nicht, wenn stdin zugeht. Stirbt die
# App hart, bleiben die Prozesse liegen. Jeder Prozess traegt deshalb die PID der
# App als Kennung; reap_orphans() raeumt beim naechsten Start auf.
PARENT_MARKER = 'captioner_parent'


class ExifToolError(RuntimeError):
    pass


def find_exiftool(configured=''):
    candidates = []
    if configured:
        candidates.append(configured)
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        candidates.append(str(Path(bundle_dir) / 'exiftool' / 'exiftool'))
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which('exiftool')
    if found:
        return found
    for fallback in ('/opt/homebrew/bin/exiftool', '/usr/local/bin/exiftool'):
        if os.access(fallback, os.X_OK):
            return fallback
    raise ExifToolError('ExifTool nicht gefunden. Pfad in den Einstellungen setzen.')


class ExifTool:
    def __init__(self, executable):
        self.executable = executable
        self._process = None
        self._counter = 0
        self._lock = threading.Lock()

    def start(self):
        self._process = subprocess.Popen(
            [self.executable, '-stay_open', 'True', '-@', '-', '-common_args', '-charset', 'filename=UTF8',
             '-userParam', f'{PARENT_MARKER}={os.getpid()}'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self

    def close(self):
        if self._process and self._process.poll() is None:
            try:
                self._process.stdin.write(b'-stay_open\nFalse\n')
                self._process.stdin.flush()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
        self._process = None

    def execute(self, *args):
        """Fuehrt ein Kommando aus, gibt (stdout_bytes, stderr_text) zurueck."""
        for arg in args:
            if '\n' in str(arg):
                raise ValueError('ExifTool-Argumente duerfen keine Zeilenumbrueche enthalten')
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self.start()
            self._counter += 1
            marker = f'{{ready{self._counter}}}'.encode()
            payload = '\n'.join(str(a) for a in args) + f'\n-echo4\n{{ready{self._counter}}}\n-execute{self._counter}\n'
            self._process.stdin.write(payload.encode('utf-8'))
            self._process.stdin.flush()
            return self._read_until(marker)

    def _read_until(self, marker):
        out, err = bytearray(), bytearray()
        done = {'out': False, 'err': False}
        selector = selectors.DefaultSelector()
        selector.register(self._process.stdout, selectors.EVENT_READ, 'out')
        selector.register(self._process.stderr, selectors.EVENT_READ, 'err')
        try:
            while not (done['out'] and done['err']):
                for key, _ in selector.select(timeout=60):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        raise ExifToolError('ExifTool wurde unerwartet beendet')
                    buffer = out if key.data == 'out' else err
                    buffer.extend(chunk)
                    if buffer.rstrip().endswith(marker):
                        done[key.data] = True
                if not selector.get_map():
                    break
        finally:
            selector.close()
        out_bytes = bytes(out).rstrip()
        out_bytes = out_bytes[:-len(marker)]
        err_text = bytes(err).rstrip()[:-len(marker)].decode('utf-8', 'replace').strip()
        # stdout endet mit "\n{readyN}"; das Zeilenende vor dem Marker gehoert nicht zu den Daten
        if out_bytes.endswith(b'\n'):
            out_bytes = out_bytes[:-1]
        return out_bytes, err_text

    def json(self, *args):
        out, err = self.execute('-json', *args)
        if not out.strip():
            return []
        try:
            return json.loads(out.decode('utf-8'))
        except ValueError as e:
            raise ExifToolError(f'Antwort von ExifTool nicht lesbar: {e}; {err}')

    def binary(self, tag, path):
        out, _ = self.execute('-b', f'-{tag}', str(path))
        return out or None


class ExifToolPool:
    """
    Eine ExifTool-Instanz pro Betriebssystem-Thread.

    Bewusst nicht threading.local: In Threads des QThreadPool legt PySide pro
    Aufruf einen neuen Python-Thread-Zustand an, threading.local waere jedes Mal
    leer und jede Vorschau startete einen eigenen Perl-Prozess.
    """

    def __init__(self, executable):
        self.executable = executable
        self._tools = {}
        self._lock = threading.Lock()

    def get(self) -> ExifTool:
        ident = threading.get_ident()
        with self._lock:
            tool = self._tools.get(ident)
            if tool is None:
                tool = ExifTool(self.executable).start()
                self._tools[ident] = tool
        return tool

    def size(self):
        with self._lock:
            return len(self._tools)

    def close(self):
        with self._lock:
            tools = list(self._tools.values())
            self._tools.clear()
        for tool in tools:
            tool.close()


def reap_orphans():
    """Beendet ExifTool-Prozesse frueherer App-Laeufe, deren App nicht mehr lebt."""
    if os.name != 'posix':
        return 0
    try:
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    reaped = 0
    for line in listing.splitlines():
        match = re.search(PARENT_MARKER + r'=(\d+)', line)
        if not match:
            continue
        pid, parent = int(line.split()[0]), int(match.group(1))
        if parent == os.getpid() or _alive(parent):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            reaped += 1
        except OSError:
            pass
    if reaped:
        logger.info('%s verwaiste ExifTool-Prozesse beendet', reaped)
    return reaped


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
