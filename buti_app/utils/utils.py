# BURST-QTAPP/buti_app/utils/utils.py
import time
import cv2
import serial.tools.list_ports
import re


def list_serial_ports():
    """Lists available serial ports."""
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


def timestamped_filename(prefix, ext):
    """Generates a timestamped filename."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{ts}.{ext}"


def list_cameras(max_idx=5):  # OpenCV camera listing
    """Lists available OpenCV/DirectShow cameras."""
    cams = []
    for i in range(max_idx):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                cams.append(i)
            cap.release()
    return cams


# --- ADDED FUNCTION ---
def to_prop_name(key: str) -> str:
    """
    Convert CamelCase or mixed_Case to UPPER_SNAKE_CASE
    to match common GenICam feature name conventions or internal mapping keys.
    Example: "ExposureTime" -> "EXPOSURE_TIME"
             "acquisitionFrameRate" -> "ACQUISITION_FRAME_RATE"
    """
    if not key:
        return ""
    # Add underscore before uppercase letters (except if it's the first char or already preceded by an underscore/uppercase)
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    # Add underscore before uppercase letters that follow another uppercase letter and then a lowercase (e.g. FPSRate -> FPS_Rate)
    s2 = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", s1)
    return s2.upper()

