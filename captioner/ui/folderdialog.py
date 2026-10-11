"""
Mehrere Ordner auf einmal waehlen.

Qt oeffnet den nativen macOS-Dialog fuer Ordner immer mit Einzelauswahl
(QCocoaFileDialogHelper erlaubt Mehrfachauswahl nur fuer Dateien). Deshalb auf
macOS NSOpenPanel direkt ueber die Objective-C-Laufzeit (ctypes, ohne PyObjC):
derselbe Finder-Dialog, aber mit Cmd-/Shift-Klick fuer mehrere Ordner.
Sonst (Windows, oder falls die Laufzeit nicht greifbar ist): Qt-eigener Dialog,
dessen Listen auf Mehrfachauswahl umgestellt werden.
"""
import ctypes
import ctypes.util
import logging
import sys

from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QListView, QTreeView

from ..i18n import _

logger = logging.getLogger(__name__)

NS_MODAL_RESPONSE_OK = 1


class _ObjC:
    """Gerade genug Objective-C fuer NSOpenPanel. Jede Nachricht mit exakter Signatur (arm64)."""

    def __init__(self):
        self.lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
        ctypes.cdll.LoadLibrary(ctypes.util.find_library('AppKit'))  # NSOpenPanel registrieren
        self.lib.objc_getClass.restype = ctypes.c_void_p
        self.lib.objc_getClass.argtypes = [ctypes.c_char_p]
        self.lib.sel_registerName.restype = ctypes.c_void_p
        self.lib.sel_registerName.argtypes = [ctypes.c_char_p]
        self._send_address = ctypes.cast(self.lib.objc_msgSend, ctypes.c_void_p).value

    def cls(self, name):
        return self.lib.objc_getClass(name.encode())

    def send(self, receiver, selector, *args, restype=ctypes.c_void_p, argtypes=()):
        prototype = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
        function = prototype(self._send_address)
        return function(receiver, self.lib.sel_registerName(selector.encode()), *args)

    def string(self, text):
        return self.send(self.cls('NSString'), 'stringWithUTF8String:', text.encode('utf-8'),
                         argtypes=[ctypes.c_char_p])

    def to_str(self, nsstring):
        raw = self.send(nsstring, 'UTF8String', restype=ctypes.c_char_p)
        return raw.decode('utf-8') if raw else ''


def _mac_panel(objc, title, start):
    panel = objc.send(objc.cls('NSOpenPanel'), 'openPanel')
    for selector, value in (('setCanChooseDirectories:', True), ('setCanChooseFiles:', False),
                            ('setAllowsMultipleSelection:', True), ('setCanCreateDirectories:', False)):
        objc.send(panel, selector, value, restype=None, argtypes=[ctypes.c_bool])
    objc.send(panel, 'setMessage:', objc.string(title), restype=None, argtypes=[ctypes.c_void_p])
    objc.send(panel, 'setPrompt:', objc.string(_('Öffnen')), restype=None, argtypes=[ctypes.c_void_p])
    if start:
        url = objc.send(objc.cls('NSURL'), 'fileURLWithPath:', objc.string(str(start)), argtypes=[ctypes.c_void_p])
        objc.send(panel, 'setDirectoryURL:', url, restype=None, argtypes=[ctypes.c_void_p])
    return panel


def _mac_selected(objc, panel):
    urls = objc.send(panel, 'URLs')
    count = objc.send(urls, 'count', restype=ctypes.c_ulong)
    paths = []
    for index in range(count):
        url = objc.send(urls, 'objectAtIndex:', index, argtypes=[ctypes.c_ulong])
        paths.append(objc.to_str(objc.send(url, 'path')))
    return [p for p in paths if p]


def _choose_mac(title, start):
    objc = _ObjC()
    panel = _mac_panel(objc, title, start)
    if objc.send(panel, 'runModal', restype=ctypes.c_long) != NS_MODAL_RESPONSE_OK:
        return []
    return _mac_selected(objc, panel)


def _choose_qt(parent, title, start):
    dialog = QFileDialog(parent, title, start or '')
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    for view in dialog.findChildren(QListView) + dialog.findChildren(QTreeView):
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    if not dialog.exec():
        return []
    return dialog.selectedFiles()


def choose_folders(parent, title, start=''):
    """Liste gewaehlter Ordner, leer bei Abbruch."""
    if sys.platform == 'darwin':
        try:
            return _choose_mac(title, start)
        except (OSError, AttributeError, TypeError) as e:
            logger.warning('NSOpenPanel nicht verfuegbar, Qt-Dialog: %s', e)
    return _choose_qt(parent, title, start)
