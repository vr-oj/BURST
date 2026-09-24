"""Bounded, isolated MM discovery; no Arduino or other microscope devices."""
from pathlib import Path
import os
import time
from .models import physical_identity
from .micro_manager_profiles import normalize_profile, profile_key


def inspect_installation(sdk, installation):
    root = Path(installation)
    if not root.is_dir():
        raise ValueError("Micro-Manager installation folder is missing.")
    core = sdk.CMMCore()
    # Listing files avoids loading every native adapter in a single process.
    libraries = sorted({p.name.removeprefix("mmgr_dal_").split(".")[0]
                        for p in root.glob("mmgr_dal_*") if p.suffix.lower() in {".dll", ".so", ".dylib"}})
    return {"installation": str(root.resolve()), "api": core.getAPIVersionInfo(),
            "libraries": [n for n in libraries if not n.lower().startswith(("demo", "sequence", "utilities"))]}


def discover_library(sdk, installation, library):
    from .micro_manager_backend import MicroManagerSession, MicroManagerControls
    handle = os.add_dll_directory(installation) if os.name == "nt" else None
    core = sdk.CMMCore()
    profiles, issues = [], []
    try:
        core.setTimeoutMs(2000)
        core.setDeviceAdapterSearchPaths([installation])
        devices = list(core.getAvailableDevices(library))
        types = list(core.getAvailableDeviceTypes(library))
        for device, kind in zip(devices, types):
            if kind != sdk.CameraDevice:
                continue
            if library.casefold() == "tiscam":
                issues.append("TIScam requires its camera selection dialog; import a saved Micro-Manager configuration.")
                continue
            label = "Camera"
            core.loadDevice(label, library, device)
            try:
                settings, serials = {}, [None]
                ambiguous = False
                for name in core.getDevicePropertyNames(label):
                    if not core.isPropertyPreInit(label, name):
                        continue
                    current = str(core.getProperty(label, name))
                    choices = list(core.getAllowedPropertyValues(label, name))
                    if library == "SpinnakerC" and name == "Serial Number" and choices:
                        serials = choices
                    elif len(choices) == 1:
                        settings[name] = choices[0]
                    elif len(choices) > 1 or not current:
                        ambiguous = True
                    else:
                        settings[name] = current
                supported = core.supportsDeviceDetection(label)
                if library == "SpinnakerC" and serials == [None]:
                    issues.append(f"{library} / {device}: no camera serial numbers reported. Check the USB connection, vendor driver and other camera applications.")
                    continue
                if not ambiguous and library != "SpinnakerC" and supported:
                    for name, value in settings.items():
                        core.setProperty(label, name, value)
                if ambiguous or (library != "SpinnakerC" and (not supported or core.detectDevice(label) != sdk.CanCommunicate)):
                    issues.append(f"{library} / {device}: use a saved configuration for this adapter's initialization settings.")
                    continue
            finally:
                core.unloadDevice(label)
            for serial in serials:
                pre_init = dict(settings)
                if serial is not None:
                    pre_init["Serial Number"] = serial
                profile = normalize_profile({"installation": installation, "camera": label,
                    "connection": {"library": library, "device": device, "pre_init": pre_init},
                    "display_name": f"{device}" + (f" (S/N: {serial})" if serial else "")})
                try:
                    with MicroManagerSession(sdk, profile) as session:
                        controls = MicroManagerControls(session).read_controls()
                        profile["configured_mode"] = {"width": session.core.getImageWidth(), "height": session.core.getImageHeight()}
                        if library == "SpinnakerC" and serial:
                            profile.update(serial=serial, vendor="FLIR", physical_id=physical_identity("FLIR", serial))
                        profiles.append({"profile": profile, "controls": controls})
                except Exception as exc:
                    issues.append(f"{library} / {device}: {exc}")
        return {"cameras": profiles, "issues": issues}
    finally:
        core.unloadAllDevices()
        if handle:
            handle.close()


def find_cameras(installations, client_factory, cancelled=lambda: False, progress=lambda message: None,
                 clock=time.monotonic, max_seconds=60):
    deadline = clock() + max_seconds
    found, issues, seen = [], [], set()
    valid_installations = []
    for installation in dict.fromkeys(installations):
        if cancelled() or clock() >= deadline:
            break
        try:
            with client_factory(cancelled=cancelled) as client:
                info = client.request("inspect_installation", installation, timeout=min(10, max(0.1, deadline - clock())))
            libraries = sorted(info["libraries"], key=lambda name: (name != "SpinnakerC", name))
            for library in libraries:
                if cancelled() or clock() >= deadline:
                    break
                progress(f"Checking {library}…")
                try:
                    with client_factory(cancelled=cancelled) as client:
                        result = client.request("discover_library", info["installation"], library,
                                                timeout=min(10, max(0.1, deadline - clock())))
                    if info["installation"] not in valid_installations:
                        valid_installations.append(info["installation"])
                    issues.extend(result["issues"])
                    for camera in result["cameras"]:
                        profile = camera["profile"]
                        key = profile.get("physical_id") or profile_key(profile)
                        if key not in seen:
                            seen.add(key)
                            found.append(camera)
                except Exception as exc:
                    issues.append(f"{library}: {exc}")
        except Exception as exc:
            issues.append(f"{installation}: {exc}")
    if cancelled():
        issues.append("Search cancelled; cameras found so far are retained.")
    elif clock() >= deadline:
        issues.append("Search reached 60 seconds; results are partial. Import a saved configuration for additional cameras.")
    return {"cameras": found, "issues": issues, "installations": valid_installations}
