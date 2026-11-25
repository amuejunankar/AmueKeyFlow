"""Frameless dialog sheets, confirmation prompts, search and toasts."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.buttons import IconButton, make_button
from app.ui.components.chips import ChordChips, Pill
from app.ui.icons import icon_pixmap
from app.ui.theme import palette


class _DragArea(QWidget):
    """Header strip that lets the user move a frameless dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._offset = None

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
            self._offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._offset = None
        super().mouseReleaseEvent(event)


class FramelessSheet(QDialog):
    """Rounded, shadowed dialog with a draggable header and footer actions."""

    def __init__(
        self,
        parent: QWidget | None = None,
        title: str = "",
        subtitle: str = "",
        width: int = 560,
        height: int | None = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setWindowTitle(title)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 26, 26, 26)
        self.sheet = QFrame()
        self.sheet.setObjectName("DialogSheet")
        self.sheet.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self.sheet)

        shadow = QGraphicsDropShadowEffect(self.sheet)
        shadow.setBlurRadius(60)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(0, 0, 0, 190))
        self.sheet.setGraphicsEffect(shadow)

        inner = QVBoxLayout(self.sheet)
        inner.setContentsMargins(26, 22, 26, 22)
        inner.setSpacing(18)

        header = _DragArea()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        title_box.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("muted", True)
        self.subtitle_label.setVisible(bool(subtitle))
        title_box.addWidget(self.subtitle_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        self.close_button = IconButton("close", tooltip="Close")
        self.close_button.clicked.connect(self.reject)
        header_layout.addWidget(self.close_button, 0, Qt.AlignTop)
        inner.addWidget(header)
        self.header = header

        self.body = QVBoxLayout()
        self.body.setSpacing(16)
        inner.addLayout(self.body, 1)

        self.footer = QHBoxLayout()
        self.footer.setSpacing(10)
        inner.addLayout(self.footer)

        self.setFixedWidth(width + 52)
        if height:
            self.setFixedHeight(height + 52)

    def add_footer_button(self, text: str, variant: str = "default", icon_name: str | None = None) -> QPushButton:
        button = make_button(text, variant, icon_name)
        self.footer.addWidget(button)
        return button

    def center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            geo = parent.window().frameGeometry()
            self.adjustSize()
            self.move(
                geo.center().x() - self.width() // 2,
                max(0, geo.center().y() - self.height() // 2),
            )


class ConfirmDialog(FramelessSheet):
    def __init__(
        self,
        parent: QWidget | None = None,
        title: str = "Are you sure?",
        message: str = "",
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        danger: bool = False,
    ):
        super().__init__(parent, title, "", width=440)
        self.body.setSpacing(10)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setProperty("muted", True)
        self.body.addWidget(label)
        self.footer.addStretch(1)
        cancel = self.add_footer_button(cancel_text)
        cancel.clicked.connect(self.reject)
        confirm = self.add_footer_button(confirm_text, "danger" if danger else "primary")
        confirm.clicked.connect(self.accept)
        confirm.setDefault(True)

    @staticmethod
    def ask(
        parent: QWidget | None,
        title: str,
        message: str,
        confirm_text: str = "Confirm",
        danger: bool = False,
    ) -> bool:
        dialog = ConfirmDialog(parent, title, message, confirm_text, danger=danger)
        dialog.center_on_parent()
        return dialog.exec() == QDialog.Accepted


class SearchDialog(FramelessSheet):
    """Search every mapping in the active profile and jump to it."""

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(parent, "Search mappings", "Find a mapping by key, name or output", width=580, height=440)
        self.controller = controller
        self.selected_id: str | None = None

        self.input = QLineEdit()
        self.input.setPlaceholderText("Try “caps lock”, “ctrl + c” or a mapping name…")
        self.body.addWidget(self.input)

        self.results = QListWidget()
        self.results.setSpacing(2)
        self.results.itemActivated.connect(self._choose)
        self.body.addWidget(self.results, 1)

        self.empty = QLabel("No mappings match your search.")
        self.empty.setProperty("muted", True)
        self.empty.setVisible(False)
        self.body.addWidget(self.empty)

        self.input.textChanged.connect(self._refresh)
        self.input.returnPressed.connect(lambda: self._choose(self.results.currentItem()))
        self._refresh("")

    def _refresh(self, text: str) -> None:
        self.results.clear()
        query = text.strip().lower()
        overrides = {o.id: o.executable for o in self.controller.db.list_app_overrides()}
        for mapping in self.controller.all_mappings():
            haystack = " ".join(
                [
                    mapping.name,
                    mapping.input_display,
                    mapping.output_display,
                    mapping.description,
                    mapping.mapping_type,
                ]
            ).lower()
            if query and query not in haystack:
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, mapping.id)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 5, 8, 5)
            layout.setSpacing(10)
            scope = overrides.get(mapping.override_id or "")
            if scope:
                scope_label = QLabel(scope)
                scope_label.setProperty("muted", True)
                scope_label.setToolTip("App override — only applies while this app is in front")
                layout.addWidget(scope_label)
            name = QLabel(mapping.name or mapping.input_display)
            name.setMinimumWidth(120)
            layout.addWidget(name)
            layout.addWidget(ChordChips(mapping.input_config, compact=True))
            arrow = QLabel("→")
            arrow.setProperty("muted", True)
            layout.addWidget(arrow)
            output = QLabel(mapping.output_display)
            output.setProperty("muted", True)
            layout.addWidget(output, 1)
            layout.addWidget(Pill("ON" if mapping.is_enabled else "OFF", "success" if mapping.is_enabled else "muted", dot=False, compact=True))
            item.setSizeHint(widget.sizeHint())
            self.results.addItem(item)
            self.results.setItemWidget(item, widget)
        self.empty.setVisible(self.results.count() == 0)

    def _choose(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self.selected_id = item.data(Qt.UserRole)
        self.accept()


class Toast(QFrame):
    """Transient status message shown at the bottom of the main window."""

    _active: "Toast | None" = None

    def __init__(self, parent: QWidget, text: str, tone: str = "success", icon_name: str | None = None):
        super().__init__(parent)
        p = palette()
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(46)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 16, 8)
        layout.setSpacing(10)
        tints = {"success": p["success"], "error": p["danger"], "info": p["info"], "warning": p["warning"]}
        tint = tints.get(tone, p["info"])
        glyph = QLabel()
        glyph.setPixmap(icon_pixmap(icon_name or ("alert" if tone in {"error", "warning"} else "check"), tint, 16, 1.9))
        layout.addWidget(glyph)
        label = QLabel(text)
        label.setWordWrap(False)
        layout.addWidget(label)
        self.adjustSize()
        self.setFixedWidth(min(max(280, label.sizeHint().width() + 76), 520))

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    @classmethod
    def show_message(cls, parent: QWidget, text: str, tone: str = "success", ms: int = 2800) -> "Toast":
        if cls._active is not None:
            try:
                cls._active.deleteLater()
            except RuntimeError:
                pass
        toast = cls(parent, text, tone)
        cls._active = toast
        toast.reposition()
        toast.show()
        toast.raise_()
        toast._fade.setStartValue(0.0)
        toast._fade.setEndValue(1.0)
        toast._fade.start()
        QTimer.singleShot(ms, toast._dismiss)
        return toast

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(parent.width() - self.width() - 28, parent.height() - self.height() - 26)

    def _dismiss(self) -> None:
        if Toast._active is not self:
            return
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()
        Toast._active = None
