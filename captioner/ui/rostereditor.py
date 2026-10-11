"""
Roster bearbeiten: lokale Roster-Dateien im Code-Replacement-Format.

* Tabs sind farbig hinterlegt (das haeufigste Problem: Leerzeichen statt Tab), Abschnitts-
  koepfe und Codes hervorgehoben, ignorierte und widerspruechliche Zeilen rot.
* Gespeichert wird in Kodierung und Zeilenenden der Datei (roster.write_file).
* URL-Quellen werden nur angezeigt (letzte geladene Fassung); zurueckschreiben
  laesst sich dorthin nicht.
"""
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QKeySequence, QPainter, QShortcut, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextFormat)
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QTextEdit, QVBoxLayout, QWidget)

from .. import roster as roster_module

ENCODING_NAMES = {'utf-8': 'UTF-8', 'utf-8-sig': 'UTF-8 mit BOM', 'utf-16': 'UTF-16', 'cp1252': 'Windows-1252'}


class LineNumbers(QWidget):
    """Zeilennummern links neben dem Text; Problemzeilen rot."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class NumberedTextEdit(QPlainTextEdit):
    """QPlainTextEdit mit Zeilennummern (Qt-Beispiel "Code Editor")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.problem_lines = set()
        self.numbers = LineNumbers(self)
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_width()
        self._highlight_current_line()

    def _highlight_current_line(self):
        """Zeile mit dem Cursor ueber die ganze Breite hinterlegen: Systemfarbe, sehr blass
        (passt zu hell/dunkel, rote Problemzeilen bleiben erkennbar)."""
        color = QColor(self.palette().highlight().color())
        color.setAlpha(60)
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(color)
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def line_number_width(self):
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_width(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_area(self, rect, dy):
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        area = self.contentsRect()
        self.numbers.setGeometry(QRect(area.left(), area.top(), self.line_number_width(), area.height()))

    def set_problem_lines(self, lines):
        self.problem_lines = set(lines)
        self.numbers.update()

    def paint_line_numbers(self, event):
        painter = QPainter(self.numbers)
        palette = self.palette()
        painter.fillRect(event.rect(), palette.alternateBase())
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible() and bottom >= event.rect().top():
                number = block.blockNumber() + 1
                if number in self.problem_lines:
                    painter.setPen(QColor('#d64541'))
                elif block.blockNumber() == current:
                    painter.setPen(palette.text().color())
                else:
                    painter.setPen(palette.placeholderText().color())
                painter.drawText(0, top, self.numbers.width() - 6, height,
                                 Qt.AlignmentFlag.AlignRight, str(number))
            block = block.next()
            top = bottom


class RosterHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.problem_lines = set()
        self.section = QTextCharFormat()
        self.section.setFontWeight(QFont.Weight.Bold)
        self.section.setForeground(QColor('#2f7de1'))
        self.code = QTextCharFormat()
        self.code.setFontWeight(QFont.Weight.Bold)
        self.problem = QTextCharFormat()
        self.problem.setBackground(QColor(214, 69, 65, 60))
        self.problem.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        self.problem.setUnderlineColor(QColor('#d64541'))
        self.tab = QTextCharFormat()
        self.tab.setBackground(QColor(47, 125, 225, 70))

    def highlightBlock(self, text):
        number = self.currentBlock().blockNumber() + 1
        if number in self.problem_lines:
            self.setFormat(0, len(text), self.problem)
            return
        if '\t' in text:
            self.setFormat(0, text.index('\t'), self.code)
            for position, char in enumerate(text):
                if char == '\t':
                    self.setFormat(position, 1, self.tab)
        elif roster_module.SECTION_PATTERN.match(text.strip()):
            self.setFormat(0, len(text), self.section)


class RosterEditorDialog(QDialog):
    saved = Signal(str)   # Pfad der gespeicherten Datei

    def __init__(self, sources, cached_text=None, parent=None):
        """sources: Settings.roster_sources; cached_text(url) liefert die geladene Fassung einer URL."""
        super().__init__(parent)
        self.setWindowTitle('Roster bearbeiten')
        self.resize(900, 760)
        self.cached_text = cached_text or (lambda url: None)
        self.file = None          # roster.RosterFile der geoeffneten lokalen Datei
        self.source = None
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.sources = QComboBox()
        for source in sources:
            local = not roster_module.is_url(source)
            name = Path(source).name if local else roster_module.raw_url(source).rsplit('/', 1)[-1]
            self.sources.addItem(name if local else f'{name}  (URL, nur lesbar)', source)
            self.sources.setItemData(self.sources.count() - 1, source, Qt.ItemDataRole.ToolTipRole)
        self.sources.currentIndexChanged.connect(self._source_chosen)
        self.find = QLineEdit()
        self.find.setPlaceholderText('Suchen (Code, Name, Team) – Enter: weiter')
        self.find.setMinimumWidth(240)
        self.find.returnPressed.connect(self.find_next)
        top.addWidget(QLabel('Datei'))
        top.addWidget(self.sources, 2)
        top.addWidget(self.find, 1)
        layout.addLayout(top)

        self.text = NumberedTextEdit()
        self.text.cursorPositionChanged.connect(self.text.numbers.update)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.text.setFont(font)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setTabStopDistance(self.text.fontMetrics().horizontalAdvance(' ') * 10)
        self.highlighter = RosterHighlighter(self.text.document())
        self.text.textChanged.connect(self._schedule_check)

        self.problems = QListWidget()
        self.problems.setMaximumHeight(140)
        self.problems.itemActivated.connect(self._jump)
        self.problems.itemClicked.connect(self._jump)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.text)
        splitter.addWidget(self.problems)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([600, 120])
        layout.addWidget(splitter, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        hint = QLabel('<small>Eine Zeile pro Code: <b>Code</b>, <b>Tab</b>, Ersetzung (z. B. '
                      '<code>bn23⇥-23- Marius Erk (EC Bad Nauheim)</code>). Abschnitte mit '
                      '<code>- Team -</code>. Tabs sind blau hinterlegt.</small>')
        hint.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QPushButton('Schließen')
        self.close_button.clicked.connect(self.close)
        self.save_button = QPushButton('Speichern')
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=lambda: (self.find.setFocus(), self.find.selectAll()))

        self._check_timer = QTimer(self, singleShot=True, interval=300)
        self._check_timer.timeout.connect(self._check)
        local = next((i for i in range(self.sources.count())
                      if not roster_module.is_url(self.sources.itemData(i))), 0)
        if self.sources.count():
            self.sources.setCurrentIndex(local)
            self._source_chosen(local)
        else:
            self.text.setReadOnly(True)
            self.status.setText('Keine Roster-Quelle eingerichtet. Mit „Roster-Datei hinzufügen …“ eine '
                                'Datei auswählen.')
            self.save_button.setEnabled(False)

    # --- Laden ----------------------------------------------------------------

    def _source_chosen(self, index):
        source = self.sources.itemData(index)
        if source == self.source or source is None:
            return
        if not self._confirm_discard():
            self.sources.blockSignals(True)
            self.sources.setCurrentIndex(self.sources.findData(self.source))
            self.sources.blockSignals(False)
            return
        self.source = source
        self.file = None
        if roster_module.is_url(source):
            text = self.cached_text(source)
            self.text.setPlainText(text or '')
            self.text.setReadOnly(True)
            self.save_button.setEnabled(False)
            self._info = ('URL-Quelle, nur lesbar: angezeigt wird die zuletzt geladene Fassung. '
                          'Ändern lässt sie sich nur dort, wo sie liegt.' if text is not None
                          else 'URL-Quelle, noch nicht geladen.')
        else:
            try:
                self.file = roster_module.read_file(source)
            except OSError as e:
                self.text.setPlainText('')
                self.text.setReadOnly(True)
                self.save_button.setEnabled(False)
                self._info = f'Nicht lesbar: {e.strerror or e}'
            else:
                self.text.setPlainText(self.file.text)
                self.text.setReadOnly(False)
                self.save_button.setEnabled(True)
                self._info = (f'{ENCODING_NAMES.get(self.file.encoding, self.file.encoding)}, '
                              f'Zeilenenden {"Windows (CRLF)" if self.file.newline == chr(13) + chr(10) else "Unix (LF)"}')
                if self.file.lossy:
                    self._info += (' – Achtung: die Datei enthält Bytes, die in Windows-1252 nicht vorkommen; '
                                   'sie werden beim Speichern zu „�“')
        self.text.document().setModified(False)
        self._check()

    # --- Pruefen --------------------------------------------------------------

    def _schedule_check(self):
        self._check_timer.start()

    def _check(self):
        text = self.text.toPlainText()
        problems = roster_module.check(text)
        entries = roster_module.parse(text)
        teams = {entry.team for entry in entries if entry.team}
        self.highlighter.problem_lines = {p.line for p in problems if p.serious}
        self.text.set_problem_lines(self.highlighter.problem_lines)
        self.highlighter.rehighlight()
        self.problems.clear()
        for problem in problems:
            entry = QListWidgetItem(f'Zeile {problem.line}: {problem.message}')
            entry.setData(Qt.ItemDataRole.UserRole, problem.line)
            if problem.serious:
                entry.setForeground(QColor('#d64541'))
            self.problems.addItem(entry)
        self.problems.setVisible(bool(problems))
        serious = sum(1 for p in problems if p.serious)
        summary = f'<b>{len(entries)} Codes, {len(teams)} Teams</b>'
        if problems:
            summary += f' · <span style="color:#d64541">{serious} Problem(e)</span>' if serious else ''
            summary += f' · {len(problems) - serious} Hinweis(e)' if len(problems) > serious else ''
        modified = ' · <i>ungespeichert</i>' if self.text.document().isModified() else ''
        self.status.setText(f'{summary}{modified}<br><small>{getattr(self, "_info", "")}</small>')

    def _jump(self, entry):
        block = self.text.document().findBlockByNumber(entry.data(Qt.ItemDataRole.UserRole) - 1)
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.text.setTextCursor(cursor)
        self.text.setFocus()

    def find_next(self):
        term = self.find.text()
        if not term:
            return
        if not self.text.find(term):
            # am Ende: von vorn
            cursor = self.text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.text.setTextCursor(cursor)
            if not self.text.find(term):
                self.find.setStyleSheet('color: #d64541;')
                return
        self.find.setStyleSheet('')

    # --- Speichern ------------------------------------------------------------

    def save(self):
        if self.file is None or self.text.isReadOnly():
            return False
        path = self.file.path
        try:
            changed_outside = path.stat().st_mtime != self.file.mtime
        except OSError:
            changed_outside = False
        if changed_outside:
            answer = QMessageBox.question(
                self, 'Datei wurde geändert', f'{path.name} wurde außerhalb von Captioner geändert, seit sie '
                'hier geöffnet wurde. Trotzdem überschreiben?')
            if answer != QMessageBox.StandardButton.Yes:
                return False
        text = self.text.toPlainText()
        if not roster_module.parse(text):
            QMessageBox.warning(self, 'Nicht gespeichert', 'Die Datei enthält keinen einzigen Code (Code, Tab, '
                                'Ersetzung). So würde sie beim Laden als fehlerhaft gelten.')
            return False
        encoding = None
        try:
            text.encode(self.file.encoding)
        except UnicodeEncodeError as e:
            answer = QMessageBox.question(
                self, 'Kodierung', f'„{e.object[e.start:e.end]}“ gibt es in '
                f'{ENCODING_NAMES.get(self.file.encoding, self.file.encoding)} nicht. Als UTF-8 speichern?')
            if answer != QMessageBox.StandardButton.Yes:
                return False
            encoding = 'utf-8'
        try:
            roster_module.write_file(self.file, text, encoding)
        except OSError as e:
            QMessageBox.warning(self, 'Nicht gespeichert', f'{path}: {e.strerror or e}')
            return False
        self.text.document().setModified(False)
        self._source_chosen_info_refresh()
        self.saved.emit(str(path))
        return True

    def _source_chosen_info_refresh(self):
        self._info = (f'{ENCODING_NAMES.get(self.file.encoding, self.file.encoding)}, gespeichert '
                      f'{Path(self.file.path).name}')
        self._check()

    # --- Schliessen -----------------------------------------------------------

    def _confirm_discard(self):
        if not self.text.document().isModified() or self.text.isReadOnly():
            return True
        answer = QMessageBox.question(
            self, 'Ungespeicherte Änderungen', 'Änderungen am Roster speichern?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    # Esc, "Schliessen" und das Fenster-X laufen alle ueber reject()
    def reject(self):
        if self._confirm_discard():
            super().reject()
