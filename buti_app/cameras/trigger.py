"""Explicit external frame triggers; never silently fall back to software timing."""
import re

AUTO_TRIGGER = "auto"


def choose_trigger_source(current, choices):
    """Reuse a physical input, or select the only one; never guess between wires."""
    physical = [str(value) for value in choices if re.fullmatch(r"Line\d+", str(value))]
    if str(current) in physical:
        return str(current)
    if len(physical) == 1:
        return physical[0]
    raise RuntimeError(
        "The camera's trigger input needs one-time setup. Select the wired input in "
        "Camera properties or the manufacturer's utility, then restart the preview. "
        "BURST cannot automatically choose between multiple inputs or use a software trigger."
    )


def verify_external_trigger(read, expected):
    actual = {name: str(read(name)) for name in expected}
    if actual != expected:
        raise RuntimeError(f"Trigger settings changed while arming: {actual}")


def configure_external_trigger(read, write, source, activation="RisingEdge", choices=None, fixed_input=None):
    if not source or source.lower() == "software":
        raise RuntimeError("Choose the physical camera input wired to the Arduino trigger output.")

    def set_value(name, value):
        # Single-choice nodes may be read-only even while acquisition is stopped.
        try:
            if str(read(name)) == value:
                return
        except Exception:
            pass
        write(name, value)

    try:
        set_value("TriggerMode", "Off")
        if fixed_input is not None:
            if source not in (AUTO_TRIGGER, fixed_input):
                raise RuntimeError(f"This camera uses the fixed {fixed_input} input, not {source}.")
        elif source == AUTO_TRIGGER:
            set_value("TriggerSelector", "FrameStart")
            source = choose_trigger_source(read("TriggerSource"), choices() if choices else ())
        desired = {"TriggerSelector": "FrameStart"}
        if fixed_input is None:
            desired["TriggerSource"] = source
        desired.update(TriggerActivation=activation, TriggerMode="On")
        for name, value in desired.items():
            set_value(name, value)
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
            "Check the camera's supported input/adapter settings. Approximate recording "
            "is available separately under Acquisition > Advanced. "
            "BURST has not started the Arduino."
        ) from exc
