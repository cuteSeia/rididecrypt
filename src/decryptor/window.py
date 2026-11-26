"""PySide window for the library decryptor."""

import threading
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from .core import decrypt_library, list_books

STYLE = """
* { font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
QMainWindow, QWidget#root { background-color: #181818; color: #eeeeee; }
QLabel { color: #dddddd; }
QLabel#title { font-size: 25px; font-weight: 700; color: #f5f5f5; }
QLabel#subtitle { font-size: 13px; color: #a5a5a5; }
QLabel#section { font-size: 12px; font-weight: 650; color: #c2c2c2; }
QLabel#status { font-size: 12px; color: #c6c6c6; }
QLabel#elapsed { font-size: 12px; font-weight: 600; color: #e2e2e2; }
QFrame#card {
    background-color: #232323;
    border: 1px solid #363636;
    border-radius: 14px;
}
QLineEdit {
    background-color: #1c1c1c;
    border: 1px solid #414141;
    border-radius: 8px;
    padding: 9px 11px;
    font-size: 14px;
    color: #f0f0f0;
    selection-color: #ffffff;
    selection-background-color: #505050;
}
QLineEdit:focus { border: 1px solid #858585; background-color: #202020; }
QLineEdit:disabled { color: #888888; background-color: #202020; }
QListWidget {
    background-color: #1c1c1c;
    color: #e8e8e8;
    border: 1px solid #363636;
    border-radius: 9px;
    padding: 5px;
    font-size: 14px;
    outline: none;
}
QListWidget::item { color: #e8e8e8; padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background: #414141; color: #ffffff; }
QPlainTextEdit {
    background-color: #1c1c1c;
    color: #d0d0d0;
    border: none;
    border-radius: 9px;
    padding: 9px 11px;
    font-family: Menlo, monospace;
    font-size: 11px;
}
QProgressBar {
    background: #393939;
    border: none;
    border-radius: 4px;
    max-height: 7px;
}
QProgressBar::chunk { background: #a0a0a0; border-radius: 4px; }
QPushButton {
    background: #303030;
    color: #e5e5e5;
    border: 1px solid #414141;
    border-radius: 8px;
    padding: 8px 13px;
    font-size: 13px;
}
QPushButton:hover { background: #404040; }
QPushButton:disabled { color: #888888; background: #292929; border-color: #353535; }
QPushButton#primary { background: #555555; border: 1px solid #626262; color: #ffffff; font-weight: 650; }
QPushButton#primary:hover { background: #666666; }
QPushButton#primary:disabled { background: #393939; border-color: #454545; color: #bcbcbc; }
QPushButton#logToggle { background: transparent; border: none; color: #a8a8a8; text-align: left; padding-left: 2px; }
QPushButton#logToggle:hover { color: #eeeeee; background: transparent; }
"""


class DecryptJob(QThread):
    logged = Signal(str)
    progressed = Signal(int, str)
    status = Signal(str)
    finished_ok = Signal(int, int)
    failed = Signal(str)

    def __init__(self, device_id: str, user_idx: str, output: Path):
        super().__init__()
        self.device_id = device_id
        self.user_idx = user_idx
        self.output = output
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            progress_lock = threading.Lock()
            progress_value = [0]

            def on_progress(index: int, total: int, title: str, page: int, pages: int) -> None:
                fraction = ((index - 1) + page / max(pages, 1)) / max(total, 1)
                with progress_lock:
                    progress_value[0] = max(progress_value[0], int(fraction * 1000))
                    self.progressed.emit(progress_value[0], f"{index}/{total}   {title}   {page}/{pages}")

            done, failed = decrypt_library(
                self.device_id,
                self.user_idx,
                self.output,
                log=self.logged.emit,
                on_progress=on_progress,
                on_status=self.status.emit,
                create_formats=True,
                stop=self._stop,
            )
            self.finished_ok.emit(done, failed)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("리디 라이브러리")
        self.resize(780, 690)
        self.setMinimumSize(640, 600)
        self.settings = QSettings("Ridi", "Decryptor")
        self.job = None
        self._started_at = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self.setStyleSheet(STYLE)
        self._build()
        self._restore()

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root.setAutoFillBackground(True)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(12)

        layout.addWidget(self._label("리디 라이브러리", "title"))
        layout.addWidget(self._label("복호화한 책을 EPUB과 PDF로 시리즈별 저장합니다.", "subtitle"))

        card = QFrame()
        card.setObjectName("card")
        form = QVBoxLayout(card)
        form.setContentsMargins(16, 15, 16, 15)
        form.setSpacing(10)
        credentials = QHBoxLayout()
        credentials.setSpacing(12)
        self.device_id = self._field(credentials, "Device ID", "36자리")
        self.user_idx = self._field(credentials, "User Index", "숫자만")
        form.addLayout(credentials)
        self.user_idx.editingFinished.connect(self.refresh_books)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.output = QLineEdit()
        self.output.setPlaceholderText("저장 폴더")
        browse = QPushButton("찾기")
        browse.setFixedWidth(72)
        browse.clicked.connect(self.choose_output)
        folder_row.addWidget(self.output, 1)
        folder_row.addWidget(browse)
        folder_line = QHBoxLayout()
        folder_line.setSpacing(12)
        folder_line.addWidget(self._label("저장 폴더", "section"))
        folder_line.addLayout(folder_row, 1)
        form.addLayout(folder_line)
        layout.addWidget(card)

        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(14, 12, 14, 14)
        list_layout.setSpacing(9)
        header = QHBoxLayout()
        self.count_label = self._label("책 목록", "section")
        header.addWidget(self.count_label)
        header.addStretch(1)
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(self.refresh_books)
        header.addWidget(refresh)
        list_layout.addLayout(header)

        self.books = QListWidget()
        self.books.setMinimumHeight(145)
        list_layout.addWidget(self.books, 1)
        layout.addWidget(list_card, 3)

        progress_card = QFrame()
        progress_card.setObjectName("card")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(15, 12, 15, 12)
        progress_layout.setSpacing(7)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        progress_layout.addWidget(self.progress)
        progress_info = QHBoxLayout()
        self.status = self._label("User Index를 입력하면 책 목록이 나옵니다.", "status")
        progress_info.addWidget(self.status, 1)
        self.elapsed_label = self._label("소요 시간  00:00", "elapsed")
        progress_info.addWidget(self.elapsed_label, 0, Qt.AlignRight)
        progress_layout.addLayout(progress_info)
        layout.addWidget(progress_card)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.start_btn = QPushButton("복호화")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        layout.addLayout(buttons)

        self.log_toggle = QPushButton("진행 기록 보기  ▾")
        self.log_toggle.setObjectName("logToggle")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        layout.addWidget(self.log_toggle)

        self.log_card = QFrame()
        self.log_card.setObjectName("card")
        log_layout = QVBoxLayout(self.log_card)
        log_layout.setContentsMargins(14, 11, 14, 13)
        log_layout.setSpacing(7)
        log_layout.addWidget(self._label("진행 기록", "section"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(86)
        self.log.setMaximumHeight(118)
        self.log.setPlaceholderText("진행 기록이 여기에 쌓입니다.")
        log_layout.addWidget(self.log)
        self.log_card.setVisible(False)
        layout.addWidget(self.log_card)

        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#181818"))
        palette.setColor(QPalette.WindowText, QColor("#eeeeee"))
        palette.setColor(QPalette.Base, QColor("#1c1c1c"))
        palette.setColor(QPalette.AlternateBase, QColor("#232323"))
        palette.setColor(QPalette.Text, QColor("#e8e8e8"))
        palette.setColor(QPalette.PlaceholderText, QColor("#858585"))
        palette.setColor(QPalette.Button, QColor("#303030"))
        palette.setColor(QPalette.ButtonText, QColor("#e5e5e5"))
        palette.setColor(QPalette.Highlight, QColor("#555555"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)
        root.setPalette(palette)

    def _label(self, text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        return label

    def _toggle_log(self, visible: bool) -> None:
        self.log_card.setVisible(visible)
        self.log_toggle.setText("진행 기록 숨기기  ▴" if visible else "진행 기록 보기  ▾")

    def _field(self, layout: QVBoxLayout, caption: str, placeholder: str) -> QLineEdit:
        layout.addWidget(self._label(caption, "section"))
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(True)
        layout.addWidget(field)
        return field

    def _restore(self) -> None:
        self.device_id.setText(self.settings.value("device_id", ""))
        self.user_idx.setText(self.settings.value("user_idx", ""))
        default_output = str(Path.home() / "Desktop" / "Ridibooks")
        self.output.setText(self.settings.value("output", default_output))
        if self.user_idx.text().strip():
            self.refresh_books()

    def _save(self) -> None:
        self.settings.setValue("device_id", self.device_id.text().strip())
        self.settings.setValue("user_idx", self.user_idx.text().strip())
        self.settings.setValue("output", self.output.text().strip())

    def choose_output(self) -> None:
        current = self.output.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "저장 폴더", current)
        if path:
            self.output.setText(path)

    def refresh_books(self) -> None:
        user_idx = self.user_idx.text().strip().lstrip("_")
        self.books.clear()
        if not user_idx:
            self.count_label.setText("책 목록")
            self.status.setText("User Index를 입력하면 책 목록이 나옵니다.")
            return
        try:
            rows = list_books(user_idx)
        except Exception as exc:
            self.count_label.setText("책 목록")
            self.status.setText(str(exc))
            return
        for book_id, title in rows:
            self.books.addItem(title)
            self.books.item(self.books.count() - 1).setData(Qt.UserRole, book_id)
        self.count_label.setText(f"책 목록  {len(rows)}권")
        self.status.setText("EPUB과 PDF를 시리즈별 폴더에 저장합니다.")

    def start(self) -> None:
        if self.job is not None:
            return
        device_id = self.device_id.text().strip()
        user_idx = self.user_idx.text().strip()
        output = self.output.text().strip()
        if len(device_id) != 36 or not user_idx or not output:
            QMessageBox.warning(self, "입력 확인", "Device ID, User Index, 저장 폴더를 확인해주세요.")
            return
        self._save()
        self.log.clear()
        self.progress.setValue(0)
        self._started_at = time.monotonic()
        self._update_elapsed()
        self._elapsed_timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("복호화 중")
        self.job = DecryptJob(device_id, user_idx, Path(output))
        self.job.logged.connect(self.log.appendPlainText)
        self.job.progressed.connect(self._on_progress)
        self.job.status.connect(self.status.setText)
        self.job.finished_ok.connect(self._on_done)
        self.job.failed.connect(self._on_error)
        self.job.finished.connect(self._on_worker_finished)
        self.job.start()

    def stop(self) -> None:
        if self.job is not None:
            self.job.request_stop()
            self.status.setText("진행 중인 페이지 처리가 끝나면 중지합니다")

    def _on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def _on_done(self, done: int, failed: int) -> None:
        self._elapsed_timer.stop()
        self._update_elapsed()
        self.progress.setValue(1000)
        self.status.setText(f"완료  ·  성공 {done}권  ·  실패 {failed}권")
        self.log.appendPlainText(self.status.text())

    def _on_error(self, message: str) -> None:
        self._elapsed_timer.stop()
        self._update_elapsed()
        self.status.setText(message)
        self.log.appendPlainText(message)
        self.log_toggle.setChecked(True)

    def _on_worker_finished(self) -> None:
        if self.job is not None:
            self.job.deleteLater()
            self.job = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event) -> None:
        if self.job is not None and self.job.isRunning():
            QMessageBox.information(self, "작업 중", "복호화가 진행 중입니다. 중지한 뒤 완료되면 창을 닫아주세요.")
            event.ignore()
            return
        event.accept()

    def _update_elapsed(self) -> None:
        if self._started_at is None:
            seconds = 0
        else:
            seconds = int(time.monotonic() - self._started_at)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        self.elapsed_label.setText(f"소요 시간  {duration}")


def font() -> QFont:
    chosen = QFont("Apple SD Gothic Neo", 13)
    chosen.setStyleStrategy(QFont.PreferAntialias)
    return chosen
