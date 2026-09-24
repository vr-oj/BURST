"""Optional property mappings; users never enter Python or C++ code."""
from copy import deepcopy
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QDialogButtonBox, QTabWidget, QWidget, QTableWidget, QPushButton, QMessageBox)
from cameras.micro_manager_profiles import ROLES, UNITS, normalize_profile


class MicroManagerMappingDialog(QDialog):
    def __init__(self, profile, controls, parent=None):
        super().__init__(parent)
        self.profile = deepcopy(profile)
        self.native = {key[3:]: value for key, value in controls.items() if key.startswith("mm:")}
        self.setWindowTitle("Advanced camera mapping")
        self.resize(780, 540)
        layout = QVBoxLayout(self)
        note = QLabel("Use automatic mappings for familiar adapters. For unusual adapters, select the existing "
            "camera controls and their native units. These settings are remembered for this camera.")
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        page, form = QWidget(), QFormLayout()
        page.setLayout(form)
        tabs.addTab(page, "Image controls")
        self.rows = {}
        for role in ROLES:
            row = QHBoxLayout()
            prop = QComboBox()
            prop.addItem("Automatic", "")
            for name in sorted(self.native):
                prop.addItem(name, name)
            binding = profile.get("bindings", {}).get(role, {})
            if binding.get("property") and prop.findData(binding["property"]) < 0:
                prop.addItem(binding["property"] + " (missing)", binding["property"])
            prop.setCurrentIndex(max(0, prop.findData(binding.get("property", ""))))
            row.addWidget(prop, 1)
            unit, off, on = QComboBox(), QComboBox(), QComboBox()
            if role in UNITS:
                unit.addItems(UNITS[role])
                unit.setCurrentText(binding.get("unit", UNITS[role][0]))
                row.addWidget(unit)
            if role.startswith("auto_"):
                row.addWidget(QLabel("Manual:"))
                row.addWidget(off)
                row.addWidget(QLabel("Auto:"))
                row.addWidget(on)
            self.rows[role] = (prop, unit, off, on)
            prop.currentIndexChanged.connect(lambda _index, r=role: self._choices(r))
            self._choices(role)
            off.setCurrentText(binding.get("off", "Off"))
            on.setCurrentText(binding.get("on", "Continuous" if on.findText("Continuous") >= 0 else "On"))
            form.addRow("Frame rate" if role == "fps" else role.replace("_", " ").title(), row)
        self.tables = {}
        for mode, title in (("preview", "Preview timing"), ("external", "External trigger timing")):
            page = QWidget()
            box = QVBoxLayout(page)
            message = QLabel("Optional ordered assignments before starting acquisition. Leave BOTH timing tabs empty "
                "for automatic setup. External assignments must select the physical Arduino trigger input; "
                "readback cannot check the cable or exposure timing. Image settings are preserved separately.")
            message.setWordWrap(True)
            box.addWidget(message)
            table = QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(["Camera property", "Value"])
            table.horizontalHeader().setStretchLastSection(True)
            table.setColumnWidth(0, 320)
            self.tables[mode] = table
            box.addWidget(table)
            buttons = QHBoxLayout()
            for label, callback in (("Add", lambda m=mode: self._add(m)),
                                    ("Remove", lambda m=mode: self.tables[m].removeRow(self.tables[m].currentRow())),
                                    ("Move up", lambda m=mode: self._move(m, -1)),
                                    ("Move down", lambda m=mode: self._move(m, 1))):
                button = QPushButton(label)
                button.clicked.connect(lambda _checked=False, fn=callback: fn())
                buttons.addWidget(button)
            box.addLayout(buttons)
            tabs.addTab(page, title)
            for item in profile.get("timing", {}).get(mode, []):
                self._add(mode, item)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choices(self, role):
        prop, unit, off, on = self.rows[role]
        control = self.native.get(prop.currentData())
        for combo in (off, on):
            combo.clear()
            if control:
                combo.addItems(control.choices)

    def _add(self, mode, item=None):
        table = self.tables[mode]
        row = table.rowCount()
        table.insertRow(row)
        prop, value = QComboBox(), QComboBox()
        prop.addItems(sorted(self.native))
        value.setEditable(True)
        def selected():
            value.clear()
            control = self.native.get(prop.currentText())
            if control:
                value.addItems(control.choices)
                value.setCurrentText(str(control.value))
        prop.currentTextChanged.connect(selected)
        selected()
        if item:
            if prop.findText(item["property"]) < 0:
                prop.addItem(item["property"])
            prop.setCurrentText(item["property"])
            value.setCurrentText(item["value"])
        table.setCellWidget(row, 0, prop)
        table.setCellWidget(row, 1, value)

    def _assignments(self, mode):
        table = self.tables[mode]
        return [{"property": table.cellWidget(row, 0).currentText(),
                 "value": table.cellWidget(row, 1).currentText()} for row in range(table.rowCount())]

    def _move(self, mode, delta):
        table = self.tables[mode]
        row = table.currentRow()
        items = self._assignments(mode)
        if 0 <= row < len(items) and 0 <= row + delta < len(items):
            items[row], items[row + delta] = items[row + delta], items[row]
            table.setRowCount(0)
            for item in items:
                self._add(mode, item)
            table.selectRow(row + delta)

    def _save(self):
        try:
            bindings = {}
            for role, (prop, unit, off, on) in self.rows.items():
                name = prop.currentData()
                if not name:
                    continue
                if name not in self.native:
                    raise ValueError(f"'{name}' is missing from the connected adapter.")
                binding = {"property": name}
                if role in UNITS:
                    binding["unit"] = unit.currentText()
                if role.startswith("auto_"):
                    binding.update(off=off.currentText(), on=on.currentText())
                bindings[role] = binding
            timing = {mode: self._assignments(mode) for mode in self.tables}
            if not any(timing.values()):
                timing = {}
            for assignments in timing.values():
                for item in assignments:
                    control = self.native.get(item["property"])
                    if control is None or not control.writable or (control.choices and item["value"] not in control.choices):
                        raise ValueError(f"Timing assignment for '{item['property']}' is unavailable or invalid.")
            self.profile = normalize_profile(dict(self.profile, bindings=bindings, timing=timing))
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Check camera mapping", str(exc))
            return
        self.accept()
