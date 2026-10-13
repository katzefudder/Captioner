"""
Dialog "Herkunft": Content Credentials eines Bildes (ADR 0002).

Links die Kette der Manifeste (neuestes oben), rechts fuer den gewaehlten Schritt:
Vorschaubild beim Signieren, das Bild jetzt und ein grobes Differenzbild, darunter die
Beschriftung beim Signieren gegen die aktuelle (nur wenn das Manifest sie enthaelt).
"""
import io

from PySide6.QtCore import QBuffer, QIODevice, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import credentials
from ..details import format_timestamp
from ..i18n import _
from .gallery import CREDENTIAL_COLORS

VERIFY_URL = 'https://contentcredentials.org/verify'
PREVIEW_SIZE = 220


def qimage_to_pil(image):
    from PIL import Image
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return Image.open(io.BytesIO(bytes(buffer.data())))


def pil_to_qimage(image):
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return QImage.fromData(stream.getvalue(), 'PNG')


def step_title(step, number):
    parts = [step.generator or _('unbekanntes Programm')]
    if step.signer:
        parts.append(step.signer)
    if step.signed_at:
        parts.append(format_timestamp(step.signed_at))
    actions = ', '.join(credentials.action_text(a) for a in step.actions)
    return f'{number}. ' + ' · '.join(parts) + (f'\n    {actions}' if actions else '')


class PreviewBox(QWidget):
    """Ueberschrift und Bild, fester Rahmen."""

    def __init__(self, title):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(title)
        heading.setStyleSheet('font-weight: bold;')
        self.image = QLabel()
        self.image.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet('background: #222; color: #888;')
        layout.addWidget(heading)
        layout.addWidget(self.image)

    def set_image(self, image, empty_text=''):
        if image is None or image.isNull():
            self.image.setPixmap(QPixmap())
            self.image.setText(empty_text)
            return
        self.image.setPixmap(QPixmap.fromImage(image).scaled(
            PREVIEW_SIZE, PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))


class CredentialsPage(QWidget):
    """Eine Datei mit Manifest."""

    def __init__(self, found, meta, current_image):
        super().__init__()
        self.credentials = found
        self.meta = meta
        self.current_image = current_image

        state = QLabel(credentials.state_text(found))
        state.setStyleSheet('font-weight: bold; color: %s;' % CREDENTIAL_COLORS.get(found.level, 'palette(text)'))
        where = _('Manifest in der Datei') if found.manifest is None \
            else _('Manifest im Sidecar {name}').format(name=found.manifest.name)
        header = QLabel(f'{found.path.name} · {where}')
        header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.steps = QListWidget()
        for number, step in enumerate(found.history, 1):
            self.steps.addItem(QListWidgetItem(step_title(step, number)))
        self.steps.currentRowChanged.connect(self._show_step)

        self.signed_box = PreviewBox(_('Beim Signieren'))
        self.current_box = PreviewBox(_('Jetzt'))
        self.difference_box = PreviewBox(_('Unterschied'))
        self.score = QLabel()
        self.score.setWordWrap(True)
        previews = QGridLayout()
        previews.addWidget(self.signed_box, 0, 0)
        previews.addWidget(self.current_box, 0, 1)
        previews.addWidget(self.difference_box, 0, 2)
        previews.addWidget(self.score, 1, 0, 1, 3)

        self.source = QLabel()
        self.authors = QLabel()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([_('Feld'), _('Beim Signieren'), _('Jetzt')])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.no_metadata = QLabel(_('Das Manifest enthält keine Beschriftung zum Vergleichen.'))

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(previews)
        right_layout.addWidget(self.source)
        right_layout.addWidget(self.authors)
        right_layout.addWidget(self.table, 1)
        right_layout.addWidget(self.no_metadata)

        splitter = QSplitter()
        splitter.addWidget(self.steps)
        splitter.addWidget(right)
        splitter.setSizes([300, 700])

        layout = QVBoxLayout(self)
        layout.addWidget(state)
        layout.addWidget(header)
        if found.failures:
            codes = QLabel(_('Prüfergebnis: {codes}').format(codes=', '.join(found.failures)))
            codes.setWordWrap(True)
            codes.setStyleSheet('color: palette(placeholder-text);')
            layout.addWidget(codes)
        layout.addWidget(splitter, 1)
        if found.history:
            self.steps.setCurrentRow(0)

    def _show_step(self, row):
        if not 0 <= row < len(self.credentials.history):
            return
        step = self.credentials.history[row]
        self.source.setText(_('Herkunft: {source}').format(source=credentials.source_text(step.source_type))
                            if step.source_type else '')
        self.authors.setText(_('Urheber: {authors}').format(authors=', '.join(step.authors)) if step.authors else '')
        self._show_previews(step)
        self._show_metadata(step)

    def _show_previews(self, step):
        self.current_box.set_image(self.current_image, _('keine Vorschau'))
        data = credentials.thumbnail(self.credentials, step)
        signed = QImage.fromData(data) if data else None
        self.signed_box.set_image(signed, _('kein Vorschaubild im Manifest'))
        if signed is None or signed.isNull() or self.current_image is None or self.current_image.isNull():
            self.difference_box.set_image(None, '–')
            self.score.setText('')
            return
        from PIL import Image
        diff, score = credentials.difference(Image.open(io.BytesIO(data)), qimage_to_pil(self.current_image))
        self.difference_box.set_image(pil_to_qimage(diff))
        self.score.setText(_('Mittlere Abweichung der Vorschaubilder: {percent} %. Grober Vergleich in '
                             'Vorschaugröße: hell ist, was sich geändert hat; Kompression zählt mit, '
                             'ein Beweis ist das nicht.').format(percent=f'{score * 100:.1f}'.replace('.', ',')))

    def _show_metadata(self, step):
        rows = credentials.metadata_changes(step, self.meta)
        self.table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        for row, (label, then, now, changed) in enumerate(rows):
            for column, text in enumerate((label, then, now)):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                if changed:
                    cell.setFont(bold)
                    cell.setForeground(QColor(CREDENTIAL_COLORS[credentials.LEVEL_INVALID]))
                self.table.setItem(row, column, cell)
        self.table.resizeColumnsToContents()
        self.table.setVisible(bool(rows))
        self.no_metadata.setVisible(not rows)


class ProvenanceDialog(QDialog):
    def __init__(self, item, current_image=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Herkunft – {name}').format(name=item.name))
        self.resize(1100, 720)
        layout = QVBoxLayout(self)
        found = item.credentials or []
        if not found:
            layout.addWidget(QLabel(_('Dieses Bild hat keine Content Credentials.')))
            self.pages = []
        elif len(found) == 1:
            self.pages = [CredentialsPage(found[0], item.meta, current_image)]
            layout.addWidget(self.pages[0], 1)
        else:
            tabs = QTabWidget()
            self.pages = [CredentialsPage(c, item.meta, current_image) for c in found]
            for page, c in zip(self.pages, found):
                tabs.addTab(page, c.path.name)
            layout.addWidget(tabs, 1)

        verify = QPushButton(_('Bei contentcredentials.org prüfen …'))
        verify.setToolTip(_('Öffnet die Prüfseite im Browser; hochgeladen wird die Datei dort von Hand.'))
        verify.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(VERIFY_URL)))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(verify)
        row.addStretch(1)
        row.addWidget(buttons)
        layout.addLayout(row)
