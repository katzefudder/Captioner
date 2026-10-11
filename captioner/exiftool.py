"""
ExifTool als dauerhafter Prozess (-stay_open), nicht ein Prozess pro Datei.

Sonst kostet allein der Perl-Start pro Bild mehr als das Auslesen der Vorschau
(ADR 0001, Punkt 2). Eine Instanz ist nicht threadsicher; ExifToolPool gibt
jedem Thread seine eigene.
"""
import json
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

from .i18n import _

logger = logging.getLogger(__name__)

# ExifTool beendet sich im -stay_open-Modus nicht, wenn stdin zugeht. Stirbt die
# App hart, bleiben die Prozesse liegen. Jeder Prozess traegt deshalb die PID der
# App als Kennung; reap_orphans() raeumt beim naechsten Start auf. Unter Windows
# haengen die Prozesse stattdessen an einem Job Object, das mit der App stirbt.
PARENT_MARKER = 'captioner_parent'

WINDOWS = sys.platform == 'win32'


class ExifToolError(RuntimeError):
    pass


def find_exiftool(configured=''):
    candidates = []
    if configured:
        candidates.append(configured)
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        # Windows: exiftool.exe startet das Perl aus exiftool_files/ daneben
        candidates.append(str(Path(bundle_dir) / 'exiftool' / ('exiftool.exe' if WINDOWS else 'exiftool')))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which('exiftool')
    if found:
        return found
    if not WINDOWS:
        for fallback in ('/opt/homebrew/bin/exiftool', '/usr/local/bin/exiftool'):
            if os.access(fallback, os.X_OK):
                return fallback
    raise ExifToolError(_('ExifTool nicht gefunden. Pfad in den Einstellungen setzen.'))


class ExifTool:
    def __init__(self, executable):
        self.executable = executable
        self._process = None
        self._counter = 0
        self._lock = threading.Lock()
        self._chunks = None

    def start(self):
        self._process = subprocess.Popen(
            [self.executable, '-stay_open', 'True', '-@', '-', '-common_args', '-charset', 'filename=UTF8',
             '-userParam', f'{PARENT_MARKER}={os.getpid()}'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            # Windows: sonst oeffnet jeder Prozess ein Konsolenfenster
            creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0)
        if WINDOWS:
            _windows_job().assign(self._process)
        # Je Pipe ein Lese-Thread. selectors kann unter Windows keine Pipes beobachten.
        self._chunks = queue.Queue()
        for name, pipe in (('out', self._process.stdout), ('err', self._process.stderr)):
            threading.Thread(target=_pump, args=(pipe, name, self._chunks), daemon=True,
                             name=f'exiftool-{name}').start()
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
        buffers = {'out': bytearray(), 'err': bytearray()}
        done = {'out': False, 'err': False}
        while not (done['out'] and done['err']):
            try:
                name, chunk = self._chunks.get(timeout=60)
            except queue.Empty:
                continue
            if not chunk:
                raise ExifToolError(_('ExifTool wurde unerwartet beendet'))
            buffers[name].extend(chunk)
            if buffers[name].rstrip().endswith(marker):
                done[name] = True
        out, err = buffers['out'], buffers['err']
        out_bytes = bytes(out).rstrip()
        out_bytes = out_bytes[:-len(marker)]
        err_text = bytes(err).rstrip()[:-len(marker)].decode('utf-8', 'replace').strip()
        # stdout endet mit "\n{readyN}" (Windows: "\r\n"); das Zeilenende vor dem Marker gehoert
        # nicht zu den Daten
        if WINDOWS and out_bytes.endswith(b'\r\n'):
            out_bytes = out_bytes[:-2]
        elif out_bytes.endswith(b'\n'):
            out_bytes = out_bytes[:-1]
        return out_bytes, err_text

    def json(self, *args):
        out, err = self.execute('-json', *args)
        if not out.strip():
            return []
        try:
            return json.loads(out.decode('utf-8'))
        except ValueError as e:
            raise ExifToolError(_('Antwort von ExifTool nicht lesbar: {error}; {stderr}').format(error=e, stderr=err))

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


def _pump(pipe, name, chunks):
    """Liest eine Pipe bis zum Ende; b'' heisst: Prozess weg."""
    fd = pipe.fileno()
    while True:
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            chunk = b''
        chunks.put((name, chunk))
        if not chunk:
            return


class _WindowsJob:
    """
    Job Object mit KILL_ON_JOB_CLOSE: Endet die App (auch hart), schliesst Windows den
    Handle und beendet alle zugeordneten ExifTool-Prozesse samt ihrem Perl.
    """
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

        class BasicLimits(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self.kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                                          wintypes.DWORD]
        self.kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.handle = self.kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'CreateJobObjectW')
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel32.SetInformationJobObject(self.handle, self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                     ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError(ctypes.get_last_error(), 'SetInformationJobObject')

    def assign(self, process):
        import ctypes
        if not self.kernel32.AssignProcessToJobObject(self.handle, int(process._handle)):
            logger.warning('ExifTool nicht im Job Object (Fehler %s), bleibt bei Absturz evtl. liegen',
                           ctypes.get_last_error())


_job = None
_job_lock = threading.Lock()


def _windows_job():
    global _job
    with _job_lock:
        if _job is None:
            _job = _WindowsJob()
        return _job


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
