"""Native macOS frontend implemented with AppKit through PyObjC."""

import threading
import time
from pathlib import Path

from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSAppearance,
    NSAppearanceNameDarkAqua,
    NSBackingStoreBuffered,
    NSButton,
    NSButtonTypeMomentaryPushIn,
    NSFont,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSModalResponseOK,
    NSOpenPanel,
    NSProgressIndicator,
    NSScrollView,
    NSSize,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSTextView,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSMakeRange, NSUserDefaults
from PyObjCTools import AppHelper
from objc import super as objc_super

from .core import decrypt_library, list_books


def _label(text: str, size: float = 13):
    label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 22))
    label.setStringValue_(text)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setFont_(NSFont.systemFontOfSize_(size))
    return label


def _field(placeholder: str):
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 200, 34))
    field.setPlaceholderString_(placeholder)
    field.setFont_(NSFont.systemFontOfSize_(14))
    return field


def _button(title: str, target, action: str):
    button = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 96, 32))
    button.setTitle_(title)
    button.setButtonType_(NSButtonTypeMomentaryPushIn)
    button.setTarget_(target)
    button.setAction_(action)
    return button


class CocoaWindow(NSObject):
    def init(self):
        self = objc_super(CocoaWindow, self).init()
        if self is None:
            return None

        self.defaults = NSUserDefaults.standardUserDefaults()
        self.rows = []
        self.worker = None
        self.stop_event = None
        self.started_at = None
        self.timer = None
        self.log_visible = False

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 840, 700),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("리디 라이브러리")
        self.window.setMinSize_(NSSize(660, 620))
        self.window.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        self.window.setDelegate_(self)
        self.root = self.window.contentView()

        self._build_controls()
        self.window.center()
        self._restore()
        return self

    def _build_controls(self):
        self.title_label = _label("리디 라이브러리", 22)
        self.root.addSubview_(self.title_label)

        self.device_label = _label("Device ID")
        self.user_label = _label("User Index")
        self.output_label = _label("저장 폴더")
        for view in (self.device_label, self.user_label, self.output_label):
            self.root.addSubview_(view)

        self.device_field = _field("36자리")
        self.user_field = _field("숫자만")
        self.output_field = _field("저장 폴더")
        for view in (self.device_field, self.user_field, self.output_field):
            self.root.addSubview_(view)
        self.user_field.setDelegate_(self)

        self.browse_button = _button("찾기", self, "chooseOutput:")
        self.refresh_button = _button("새로고침", self, "refreshBooks:")
        self.root.addSubview_(self.browse_button)
        self.root.addSubview_(self.refresh_button)

        self.count_label = _label("책 목록")
        self.root.addSubview_(self.count_label)
        self.table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 260))
        column = NSTableColumn.alloc().initWithIdentifier_("title")
        column.setTitle_("")
        self.table.addTableColumn_(column)
        self.table.setHeaderView_(None)
        self.table.setRowHeight_(30)
        self.table_column = column
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)

        self.book_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 260))
        self.book_scroll.setHasVerticalScroller_(True)
        self.book_scroll.setDocumentView_(self.table)
        self.root.addSubview_(self.book_scroll)

        self.progress = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 10))
        self.progress.setMinValue_(0)
        self.progress.setMaxValue_(100)
        self.progress.setIndeterminate_(False)
        self.root.addSubview_(self.progress)
        self.status_label = _label("준비됨")
        self.elapsed_label = _label("00:00")
        self.root.addSubview_(self.status_label)
        self.root.addSubview_(self.elapsed_label)

        self.log_toggle = _button("기록 보기", self, "toggleLog:")
        self.root.addSubview_(self.log_toggle)
        self.log_text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 90))
        self.log_text.setEditable_(False)
        self.log_text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11, 0))
        self.log_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 90))
        self.log_scroll.setHasVerticalScroller_(True)
        self.log_scroll.setDocumentView_(self.log_text)
        self.root.addSubview_(self.log_scroll)
        self.log_scroll.setHidden_(True)

        self.start_button = _button("복호화", self, "start:")
        self.stop_button = _button("중지", self, "stop:")
        self.stop_button.setEnabled_(False)
        self.root.addSubview_(self.start_button)
        self.root.addSubview_(self.stop_button)

        self.layoutControls()

    def layoutControls(self):
        width = self.root.bounds().size.width
        height = self.root.bounds().size.height
        margin = 24
        gap = 16
        half = (width - margin * 2 - gap) / 2

        self.title_label.setFrame_(NSMakeRect(margin, height - 52, width - margin * 2, 30))
        self.device_label.setFrame_(NSMakeRect(margin, height - 87, half, 20))
        self.user_label.setFrame_(NSMakeRect(margin + half + gap, height - 87, half, 20))
        self.device_field.setFrame_(NSMakeRect(margin, height - 127, half, 34))
        self.user_field.setFrame_(NSMakeRect(margin + half + gap, height - 127, half, 34))

        self.output_label.setFrame_(NSMakeRect(margin, height - 165, 90, 20))
        browse_width = 96
        self.browse_button.setFrame_(NSMakeRect(width - margin - browse_width, height - 176, browse_width, 32))
        self.output_field.setFrame_(NSMakeRect(margin + 98, height - 176, width - margin * 2 - 98 - browse_width - 10, 34))

        self.count_label.setFrame_(NSMakeRect(margin, height - 231, 240, 22))
        self.refresh_button.setFrame_(NSMakeRect(width - margin - 104, height - 236, 104, 32))

        table_top = height - 250
        table_bottom = 228 if self.log_visible else 128
        self.book_scroll.setFrame_(NSMakeRect(margin, table_bottom, width - margin * 2, max(80, table_top - table_bottom)))
        self.table.setFrame_(NSMakeRect(0, 0, width - margin * 2 - 16, max(80, table_top - table_bottom)))

        self.log_scroll.setFrame_(NSMakeRect(margin, 128, width - margin * 2, 88))
        self.log_text.setFrame_(NSMakeRect(0, 0, width - margin * 2 - 16, 88))
        self.table_column.setWidth_(width - margin * 2 - 16)
        self.progress.setFrame_(NSMakeRect(margin, 96, width - margin * 2, 10))
        self.status_label.setFrame_(NSMakeRect(margin, 63, width - 210, 22))
        self.elapsed_label.setFrame_(NSMakeRect(width - margin - 160, 63, 160, 22))
        self.log_toggle.setFrame_(NSMakeRect(margin, 18, 120, 32))
        self.start_button.setFrame_(NSMakeRect(width - margin - 204, 18, 96, 32))
        self.stop_button.setFrame_(NSMakeRect(width - margin - 96, 18, 96, 32))

    def windowDidResize_(self, notification):
        self.layoutControls()

    def windowShouldClose_(self, window):
        if self.worker is not None and self.worker.is_alive():
            self.status_label.setStringValue_("중지 후 작업이 끝나면 닫을 수 있습니다")
            return False
        return True

    def controlTextDidEndEditing_(self, notification):
        if notification.object() == self.user_field:
            self.refreshBooks_(None)

    def numberOfRowsInTableView_(self, table):
        return len(self.rows)

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        return self.rows[row][1]

    def _restore(self):
        self.device_field.setStringValue_(self.defaults.stringForKey_("device_id") or "")
        self.user_field.setStringValue_(self.defaults.stringForKey_("user_idx") or "")
        default_output = str(Path.home() / "Desktop" / "Ridibooks")
        self.output_field.setStringValue_(self.defaults.stringForKey_("output") or default_output)
        if self.user_field.stringValue().strip():
            self.refreshBooks_(None)

    def _save(self):
        self.defaults.setObject_forKey_(self.device_field.stringValue().strip(), "device_id")
        self.defaults.setObject_forKey_(self.user_field.stringValue().strip(), "user_idx")
        self.defaults.setObject_forKey_(self.output_field.stringValue().strip(), "output")

    def chooseOutput_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setPrompt_("선택")
        panel.setDirectoryURL_(None)
        if panel.runModal() == NSModalResponseOK:
            urls = panel.URLs()
            if urls:
                self.output_field.setStringValue_(urls[0].path())

    def refreshBooks_(self, sender):
        user_idx = self.user_field.stringValue().strip().lstrip("_")
        self.rows = []
        if not user_idx:
            self.count_label.setStringValue_("책 목록")
            self.status_label.setStringValue_("User Index 입력")
            self.table.reloadData()
            return
        try:
            self.rows = list_books(user_idx)
        except Exception as exc:
            self.status_label.setStringValue_(str(exc))
            self.count_label.setStringValue_("책 목록")
            self.table.reloadData()
            return
        self.count_label.setStringValue_(f"책 목록  {len(self.rows)}권")
        self.status_label.setStringValue_("준비됨")
        self.table.reloadData()

    def toggleLog_(self, sender):
        self.log_visible = not self.log_visible
        self.log_scroll.setHidden_(not self.log_visible)
        self.log_toggle.setTitle_("기록 숨기기" if self.log_visible else "기록 보기")
        self.layoutControls()

    def start_(self, sender):
        if self.worker is not None and self.worker.is_alive():
            return
        device_id = self.device_field.stringValue().strip()
        user_idx = self.user_field.stringValue().strip()
        output = self.output_field.stringValue().strip()
        if len(device_id) != 36 or not user_idx or not output:
            self.status_label.setStringValue_("Device ID, User Index, 저장 폴더를 확인하세요")
            return

        self._save()
        self.progress.setDoubleValue_(0)
        self.started_at = time.monotonic()
        self.status_label.setStringValue_("복호화 중")
        self.start_button.setEnabled_(False)
        self.stop_button.setEnabled_(True)
        self.device_field.setEnabled_(False)
        self.user_field.setEnabled_(False)
        self.output_field.setEnabled_(False)
        self.browse_button.setEnabled_(False)
        self.refresh_button.setEnabled_(False)
        self.stop_event = threading.Event()
        self.timer = AppHelper.callLater(1.0, self.tick)

        def on_progress(index, total, title, page, pages):
            AppHelper.callAfter(self._update_progress, index, total, title, page, pages)

        def work():
            try:
                result = decrypt_library(
                    device_id,
                    user_idx,
                    Path(output),
                    log=lambda message: AppHelper.callAfter(self._append_log, message),
                    on_progress=on_progress,
                    on_status=lambda message: AppHelper.callAfter(self._set_status, message),
                    create_formats=True,
                    stop=self.stop_event,
                )
                AppHelper.callAfter(self._finish_result, *result)
            except Exception as exc:
                AppHelper.callAfter(self._fail_result, str(exc))

        self.worker = threading.Thread(target=work, name="decrypt-library", daemon=True)
        self.worker.start()

    def stop_(self, sender):
        if self.stop_event is not None:
            self.stop_event.set()
            self.status_label.setStringValue_("진행 중인 페이지 처리가 끝나면 중지합니다")

    def tick(self):
        if self.started_at is None:
            return
        seconds = max(0, int(time.monotonic() - self.started_at))
        hours, rest = divmod(seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        value = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        self.elapsed_label.setStringValue_(value)
        self.timer = AppHelper.callLater(1.0, self.tick)

    def _update_progress(self, index, total, title, page, pages):
        fraction = ((index - 1) + page / max(pages, 1)) / max(total, 1)
        self.progress.setDoubleValue_(max(self.progress.doubleValue(), fraction * 100))
        self.status_label.setStringValue_(f"{index}/{total}  {title}  {page}/{pages}")

    def _set_status(self, message):
        self.status_label.setStringValue_(message)

    def _append_log(self, message):
        existing = self.log_text.string()
        updated = f"{existing}\n{message}" if existing else message
        self.log_text.setString_(updated)
        self.log_text.scrollRangeToVisible_(NSMakeRange(len(updated), 0))

    def _finish_result(self, done, failed):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        self.progress.setDoubleValue_(100)
        self.status_label.setStringValue_(f"완료  ·  성공 {done}권  ·  실패 {failed}권")
        self._append_log(self.status_label.stringValue())
        self._set_idle()

    def _fail_result(self, message):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        self.status_label.setStringValue_(message)
        self._append_log(message)
        self.log_visible = True
        self.log_scroll.setHidden_(False)
        self.log_toggle.setTitle_("기록 숨기기")
        self.layoutControls()
        self._set_idle()

    def _set_idle(self):
        self.started_at = None
        self.stop_event = None
        self.worker = None
        self.start_button.setEnabled_(True)
        self.stop_button.setEnabled_(False)
        self.device_field.setEnabled_(True)
        self.user_field.setEnabled_(True)
        self.output_field.setEnabled_(True)
        self.browse_button.setEnabled_(True)
        self.refresh_button.setEnabled_(True)


def _install_menu(app):
    menu = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    menu.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("종료", "terminate:", "q")
    app_menu.addItem_(quit_item)
    app_item.setSubmenu_(app_menu)
    app.setMainMenu_(menu)


def run():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    _install_menu(app)
    controller = CocoaWindow.alloc().init()
    controller.window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()
