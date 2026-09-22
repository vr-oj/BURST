from dataclasses import dataclass


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
            return "Camera Default"
        return f"{self.width}×{self.height} ({self.pixel_format})"

    def as_tuple(self) -> tuple[int, int, str]:
        return self.width, self.height, self.pixel_format
