from dataclasses import dataclass


def physical_identity(vendor: str, serial: str | None) -> str | None:
    """Conservative vendor + serial key shared by native SDKs and GenTL."""
    if not vendor or not serial or serial.lower() in {"unknown", "none", "0"}:
        return None
    vendor = vendor.casefold().strip()
    if "flir" in vendor or "point grey" in vendor:
        vendor = "flir"
    elif "imaging source" in vendor:
        vendor = "tis"
    return f"{vendor}:{serial.casefold().strip()}"


@dataclass(frozen=True)
class CameraDeviceInfo:
    backend: str
    id: str
    display_name: str
    serial: str | None = None
    native_info: object = None
    vendor: str = ""
    # Only populate when a backend can supply a stable physical-device key.
    physical_id: str | None = None


@dataclass(frozen=True)
class CameraMode:
    width: int
    height: int
    pixel_format: str

    @property
    def display_name(self) -> str:
        if not self.width or not self.height:
            if self.pixel_format == "Configuration":
                return "Configuration (resolution read on start)"
            return "Camera Default"
        return f"{self.width}×{self.height} ({self.pixel_format})"

    def as_tuple(self) -> tuple[int, int, str]:
        return self.width, self.height, self.pixel_format
