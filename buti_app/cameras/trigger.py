"""Explicit external frame triggers; never silently fall back to software timing."""


def verify_external_trigger(read, expected):
    actual = {name: str(read(name)) for name in expected}
    if actual != expected:
        raise RuntimeError(f"Trigger settings changed while arming: {actual}")


def configure_external_trigger(read, write, source, activation="RisingEdge"):
    if not source or source.lower() == "software":
        raise RuntimeError("Choose the physical camera input wired to the Arduino trigger output.")
    desired = {"TriggerSelector": "FrameStart", "TriggerSource": source,
               "TriggerActivation": activation, "TriggerMode": "On"}
    try:
        write("TriggerMode", "Off")
        for name, value in desired.items():
            write(name, value)
        actual = {name: str(read(name)) for name in desired}
        if actual != desired:
            raise RuntimeError(f"Trigger readback differs from requested settings: {actual}")
        return actual
    except Exception as exc:
        try:
            write("TriggerMode", "Off")
        except Exception:
            pass
        raise RuntimeError(
            f"Cannot arm external triggering on {source}: {exc}. "
            "Check the camera's supported input/adapter settings, or select Software pairing. "
            "BURST has not started the Arduino."
        ) from exc
