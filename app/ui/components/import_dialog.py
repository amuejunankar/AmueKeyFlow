"""Dialogs used by configuration import/export."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.components.dialogs import FramelessSheet


class MessageSheet(FramelessSheet):
    def __init__(self, parent: QWidget | None, title: str, message: str, confirm_text: str = "Close"):
        super().__init__(parent, title, "", width=460)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setProperty("muted", True)
        self.body.addWidget(label)
        self.footer.addStretch(1)
        button = self.add_footer_button(confirm_text, "primary")
        button.clicked.connect(self.accept)
        button.setDefault(True)

    @staticmethod
    def show_message(parent, title: str, message: str) -> None:
        dialog = MessageSheet(parent, title, message)
        dialog.center_on_parent()
        dialog.exec()


class ImportDialog(FramelessSheet):
    """Explain what the file contains and let the user pick a merge strategy."""

    def __init__(
        self,
        parent: QWidget | None,
        profile_count: int,
        mapping_count: int,
        file_name: str,
        override_count: int = 0,
    ):
        super().__init__(parent, "Import configuration", file_name, width=560)
        self.mode: str | None = None
        contents = f"{profile_count} profile(s) and {mapping_count} mapping(s)"
        if override_count:
            contents += f", plus {override_count} app override(s)"
        intro = QLabel(f"The file contains {contents}. Choose how it should be applied.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)

        merge = QLabel(
            "<b>Merge</b> — adds profiles and mappings that do not exist yet. Existing mappings are kept and "
            "duplicate trigger combinations inside a profile are skipped."
        )
        merge.setWordWrap(True)
        merge.setProperty("muted", True)
        self.body.addWidget(merge)

        replace = QLabel(
            "<b>Replace everything</b> — deletes the current profiles, mappings and app overrides and "
            "restores the file exactly. A backup is created automatically first."
        )
        replace.setWordWrap(True)
        replace.setProperty("muted", True)
        self.body.addWidget(replace)

        self.footer.addWidget(QLabel(""))
        self.footer.addStretch(1)
        cancel = self.add_footer_button("Cancel")
        cancel.clicked.connect(self.reject)
        merge_button = self.add_footer_button("Merge", "default", "upload")
        merge_button.clicked.connect(lambda: self._choose("merge"))
        replace_button = self.add_footer_button("Replace everything", "danger")
        replace_button.clicked.connect(lambda: self._choose("replace"))
        merge_button.setDefault(True)

    def _choose(self, mode: str) -> None:
        self.mode = mode
        self.accept()
