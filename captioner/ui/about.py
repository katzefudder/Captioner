"""The "About Captioner" window: logo, version, link to the website."""
import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .. import WEBSITE, WEBSITE_LINK, version
from ..i18n import _
from .resources import logo_pixmap


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Über Captioner'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(128).scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        title = QLabel('<h2 style="margin:0">Captioner</h2>' + _('Version {version}').format(version=version()))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        text = QLabel(_('Fotos sichten, bewerten und beschriften, bevor sie in Lightroom importiert werden.'))
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)

        # target with campaign parameters, only the short address is visible
        self.link = QLabel(f'<a href="{html.escape(WEBSITE_LINK)}">{WEBSITE.split("://", 1)[1]}</a>')
        self.link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.link.setOpenExternalLinks(True)
        self.link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(self.link)

        credit = QLabel('<small>© Florian Dehn 2026 · GPL-3.0-or-later</small>')
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.setFixedWidth(380)
