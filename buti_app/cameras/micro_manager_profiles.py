"""Versioned, data-only Micro-Manager connections and control mappings."""
from copy import deepcopy
import json
from pathlib import Path

ROLES = ("exposure", "gain", "fps", "auto_exposure", "auto_gain", "pixel_format")
UNITS = {"exposure": ("ms", "us", "s"), "gain": ("camera units", "dB"), "fps": ("fps",)}


def normalize_profile(profile, *, check_paths=True):
    if not isinstance(profile, dict) or profile.get("version", 1) not in (1, 2):
        raise ValueError("Unsupported camera profile version.")
    result = deepcopy(profile)
    installation = Path(str(result.get("installation", "")))
    if check_paths and (not result.get("installation") or not installation.is_dir()):
        raise ValueError("Select the Micro-Manager installation folder containing its device adapters.")
    result.update(version=2, installation=str(installation.resolve()), camera=str(result.get("camera", "")))
    connection = result.get("connection")
    if connection is not None:
        if not isinstance(connection, dict) or not all(isinstance(connection.get(k), str) and connection[k]
                                                      for k in ("library", "device")):
            raise ValueError("A discovered connection needs an adapter and camera device name.")
        pre_init = connection.get("pre_init", {})
        if not isinstance(pre_init, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in pre_init.items()):
            raise ValueError("Initialization settings must be property/value strings.")
        result["camera"] = result["camera"] or "Camera"
        connection["pre_init"] = pre_init
        result.pop("config", None)
    else:
        config = Path(str(result.get("config", "")))
        if check_paths and (not config.is_file() or config.suffix.lower() != ".cfg"):
            raise ValueError("Select an existing Micro-Manager hardware configuration (.cfg).")
        result["config"] = str(config.resolve())
    bindings = result.get("bindings", {})
    if not isinstance(bindings, dict) or set(bindings) - set(ROLES):
        raise ValueError("Unknown camera control mapping.")
    for role, binding in bindings.items():
        if not isinstance(binding, dict) or not isinstance(binding.get("property"), str) or not binding["property"]:
            raise ValueError(f"Choose an existing property for {role}.")
        if role in UNITS and binding.get("unit") not in UNITS[role]:
            raise ValueError(f"Choose the native units for {role}.")
        if role.startswith("auto_") and (not all(isinstance(binding.get(k), str) for k in ("on", "off"))
                                         or binding["on"] == binding["off"]):
            raise ValueError(f"Choose distinct automatic/manual values for {role}.")
        if set(binding) - {"property", "unit", "on", "off"}:
            raise ValueError("Mappings accept property names, units and enum values only.")
    timing = result.get("timing", {})
    if not isinstance(timing, dict) or set(timing) - {"preview", "external"}:
        raise ValueError("Timing mappings contain preview and external assignments only.")
    if timing and not all(timing.get(mode) for mode in ("preview", "external")):
        raise ValueError("Provide both preview and external-trigger assignments.")
    for assignments in timing.values():
        if not isinstance(assignments, list) or len(assignments) > 32:
            raise ValueError("Use at most 32 ordered timing assignments.")
        for item in assignments:
            if not isinstance(item, dict) or set(item) != {"property", "value"} or not all(
                    isinstance(item[k], str) and item[k] for k in item):
                raise ValueError("Timing assignments must contain a property and value; scripts are not supported.")
    result["bindings"], result["timing"] = bindings, timing
    return result


def profile_key(profile):
    connection = profile.get("connection")
    return json.dumps([profile.get("installation", ""), connection or profile.get("config", ""),
                       profile.get("camera", "")], sort_keys=True)


def read_profile(path):
    path = Path(path)
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Camera profile is too large.")
    return normalize_profile(json.loads(path.read_text(encoding="utf-8")), check_paths=False)


def write_profile(path, profile):
    Path(path).write_text(json.dumps(normalize_profile(profile, check_paths=False), indent=2), encoding="utf-8")
