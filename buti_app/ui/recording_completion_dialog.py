"""Combined post-recording summary, rename, and action dialog."""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from utils.recording_summary import format_bytes, format_duration


class RecordingCompletionDialog(QDialog):
    """Collect all post-recording choices in one modal window."""

    open_folder_requested = pyqtSignal()

    def __init__(
        self,
        current_name: str,
        run_folder_name: str,
        *,
        summary=None,
        braid_application: str | None = None,
        braid_icon_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._completion_action = "finish"
        self.setWindowTitle("Recording Complete")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        recovered = summary is not None and summary.status == "recovered"
        heading = QLabel(
            "Interrupted recording recovered"
            if recovered
            else "Recording saved successfully"
        )
        heading.setProperty("cssClass", "panelTitle")
        layout.addWidget(heading)

        details = QLabel(
            (
                f"Readable CSV and TIFF data were preserved in {run_folder_name}."
                if recovered
                else f"The synchronized CSV and TIFF were saved in {run_folder_name}."
            )
        )
        details.setWordWrap(True)
        layout.addWidget(details)

        if summary is not None:
            layout.addWidget(self._build_integrity_card(summary))

        name_label = QLabel("Recording name for both files:")
        layout.addWidget(name_label)

        self.name_edit = QLineEdit(current_name)
        self.name_edit.selectAll()
        layout.addWidget(self.name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save, parent=self)
        open_folder_button = buttons.addButton(
            "Open Run Folder",
            QDialogButtonBox.ActionRole,
        )
        open_folder_button.setToolTip(
            "Open the folder containing this recording without closing this window"
        )
        open_folder_button.clicked.connect(self.open_folder_requested.emit)

        if braid_application:
            self.braid_button = buttons.addButton(
                "Open in BRAID",
                QDialogButtonBox.ActionRole,
            )
            if braid_icon_path:
                self.braid_button.setIcon(QIcon(braid_icon_path))
            self.braid_button.setToolTip(
                "Apply the recording name and open this TIFF for analysis in BRAID"
            )
            self.braid_button.clicked.connect(self._request_braid)
        else:
            self.braid_button = None

        save_button = buttons.button(QDialogButtonBox.Save)
        save_button.setText("Finish")
        save_button.setToolTip(
            "Apply the recording name and close this window"
        )
        save_button.setDefault(True)
        buttons.accepted.connect(self._finish)
        layout.addWidget(buttons)

    def _build_integrity_card(self, summary):
        card = QFrame(self)
        card.setProperty("cssClass", "subCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(7)

        status_icon = "✓" if summary.checks_passed else "⚠"
        status = QLabel(f"{status_icon}  {summary.status_title}")
        status.setProperty(
            "cssClass",
            "integrityPassed" if summary.checks_passed else "integrityWarning",
        )
        status.setToolTip(
            "BURST verifies that both files closed successfully, compares force "
            "sample and video-frame counts, checks device-frame continuity, and "
            "confirms no paired samples remain pending."
        )
        card_layout.addWidget(status)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(18)
        metrics.setVerticalSpacing(5)
        metric_rows = (
            (
                "Video frames",
                f"{summary.frames_written:,}",
                "Images successfully written into the multi-page TIFF file.",
            ),
            (
                "Force samples",
                f"{summary.samples_written:,}",
                "Synchronized device rows successfully written into the CSV file.",
            ),
            (
                "Duration",
                format_duration(summary.duration_s),
                "Elapsed device time between the first and last recorded samples.",
            ),
            (
                "File sizes",
                (
                    f"CSV {format_bytes(summary.csv_size_bytes)}  ·  "
                    f"TIFF {format_bytes(summary.tiff_size_bytes)}"
                ),
                "Final sizes after both recording files were closed.",
            ),
        )
        for row, (label_text, value_text, tooltip) in enumerate(metric_rows):
            label = QLabel(label_text)
            value = QLabel(value_text)
            label.setProperty("cssClass", "detailLabel")
            value.setProperty("cssClass", "detailValue")
            label.setToolTip(tooltip)
            value.setToolTip(tooltip)
            metrics.addWidget(label, row, 0)
            metrics.addWidget(value, row, 1)
        metrics.setColumnStretch(1, 1)
        card_layout.addLayout(metrics)

        if summary.issues:
            issue_text = QLabel("\n".join(f"• {issue}" for issue in summary.issues))
            issue_text.setWordWrap(True)
            issue_text.setProperty("cssClass", "integrityWarningDetail")
            issue_text.setToolTip(
                "These checks need review before the recording is used for analysis."
            )
            card_layout.addWidget(issue_text)
        return card

    def _finish(self):
        self._completion_action = "finish"
        self.accept()

    def _request_braid(self):
        self._completion_action = "braid"
        self.accept()

    def recording_name(self) -> str:
        return self.name_edit.text()

    def completion_action(self) -> str:
        return self._completion_action
