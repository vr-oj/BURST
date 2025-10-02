"""Reusable widgets for UI panels."""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QWidget, QLabel, QVBoxLayout, QSizePolicy


class MetricCard(QFrame):
    """Reusable metric card with compact label/value layout."""

    def __init__(
        self,
        title: str,
        parent: Optional[QWidget] = None,
        *,
        label_class: str = "heroLabel",
        value_class: str = "heroValue",
        uppercase_label: bool = True,
        placeholder: str = "—",
    ) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "heroCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        label = QLabel(title.upper() if uppercase_label else title)
        label.setProperty("cssClass", label_class)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(label)

        self.value_label = QLabel(placeholder)
        self.value_label.setProperty("cssClass", value_class)
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.value_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.value_label)

        self._placeholder = placeholder

    def set_value(self, html_value: Optional[str]) -> None:
        """Update the card's value label, falling back to placeholder."""

        if not html_value:
            self.value_label.setText(self._placeholder)
        else:
            self.value_label.setText(html_value)
