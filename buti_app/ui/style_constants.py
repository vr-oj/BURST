"""Shared UI style constants for control panels."""

PANEL_STYLESHEET = '''
QFrame[cssClass="panelCard"] {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
}

QLabel[cssClass="panelTitle"] {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.03em;
    color: rgba(255, 255, 255, 0.85);
}

QLabel[cssClass="statusBadge"] {
    font-size: 12px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.75);
}

QFrame[cssClass="heroCard"] {
    background-color: rgba(255, 255, 255, 0.04);
    border-radius: 8px;
}

QFrame[cssClass="subCard"] {
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
}

QLabel[cssClass="heroLabel"] {
    font-size: 10px;
    letter-spacing: 0.08em;
    color: rgba(255, 255, 255, 0.7);
}

QLabel[cssClass="heroValue"] {
    font-size: 22px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.92);
    font-family: "Roboto Mono", "Consolas", "Courier New", monospace;
}

QLabel[cssClass="detailLabel"] {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.6);
}

QLabel[cssClass="detailValue"] {
    font-size: 12px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.9);
    font-family: "Roboto Mono", "Consolas", "Courier New", monospace;
}

QLabel[cssClass="microLabel"] {
    font-size: 10px;
    letter-spacing: 0.05em;
    color: rgba(255, 255, 255, 0.55);
}

QLabel[cssClass="sectionLabel"] {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: rgba(255, 255, 255, 0.82);
}

QLabel[cssClass="axisState"] {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.52);
}

QFrame[cssClass="panelDivider"] {
    background-color: rgba(255, 255, 255, 0.1);
    min-height: 1px;
    max-height: 1px;
}

QPushButton[cssClass="primary"] {
    background-color: #3DBD7D;
    color: #0B1014;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
}

QPushButton[cssClass="primary"]:hover:!disabled {
    background-color: #45D18A;
}

QPushButton[cssClass="primary"]:disabled {
    background-color: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.35);
}

QPushButton[cssClass="record"] {
    background-color: #D94F57;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 700;
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 8px;
    padding: 9px 16px;
}

QPushButton[cssClass="record"]:hover:!disabled {
    background-color: #EB6068;
}

QPushButton[cssClass="record"][recordState="recording"] {
    background-color: #A92F38;
    border-color: #F07A80;
}

QPushButton[cssClass="record"]:disabled {
    background-color: rgba(217, 79, 87, 0.18);
    color: rgba(255, 255, 255, 0.38);
    border-color: rgba(255, 255, 255, 0.10);
}

QPushButton[cssClass="ghost"] {
    background-color: transparent;
    color: rgba(255, 255, 255, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 6px;
    padding: 6px 12px;
}

QPushButton[cssClass="ghost"]:hover:!disabled {
    background-color: rgba(255, 255, 255, 0.08);
}

QPushButton[cssClass="ghost"]:disabled {
    color: rgba(255, 255, 255, 0.35);
    border-color: rgba(255, 255, 255, 0.12);
}

QComboBox[cssClass="monoInput"],
QDoubleSpinBox[cssClass="monoInput"],
QSpinBox[cssClass="monoInput"],
QLineEdit[cssClass="monoInput"] {
    font-family: "Roboto Mono", "Consolas", "Courier New", monospace;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.92);
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 4px;
    padding: 2px 6px;
}

QComboBox[cssClass="monoInput"]::drop-down {
    width: 22px;
    border-left: 1px solid rgba(255, 255, 255, 0.14);
}

QCheckBox[cssClass="muted"] {
    color: rgba(255, 255, 255, 0.78);
    font-size: 11px;
}

QCheckBox[cssClass="muted"]::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid rgba(255, 255, 255, 0.25);
    background-color: rgba(255, 255, 255, 0.06);
}

QCheckBox[cssClass="muted"]::indicator:checked {
    background-color: #3DBD7D;
    border-color: #3DBD7D;
}

QSlider[cssClass="controlSlider"]::groove:horizontal {
    height: 6px;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.18);
}

QSlider[cssClass="controlSlider"]::handle:horizontal {
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
    background: #3DBD7D;
}

QSlider[cssClass="controlSlider"]::handle:horizontal:disabled {
    background: rgba(255, 255, 255, 0.25);
}

QListWidget[cssClass="batchList"] {
    color: rgba(255, 255, 255, 0.86);
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 5px;
    padding: 3px;
    font-family: "Roboto Mono", "Consolas", "Courier New", monospace;
    font-size: 11px;
}
'''
