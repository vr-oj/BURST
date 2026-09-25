"""Opt-in camera test for a lab developer. Never opens or commands an Arduino."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "buti_app"))
from cameras.plugins import PluginManifest
from cameras.plugin_process import PluginClient
from threads.plugin_camera_thread import decode_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--device", help="Device ID from discovery; required if several cameras are found")
    parser.add_argument("--trigger-source", help="Opt in to arming this input, checking readback and restoring preview (e.g. auto)")
    args = parser.parse_args()
    manifest = PluginManifest.read(args.manifest)
    with PluginClient(manifest) as client:
        devices = client.request("discover")
        print("Discovered:", [(d["id"], d["name"]) for d in devices])
        selected = next((d for d in devices if d["id"] == args.device), None) if args.device else (devices[0] if len(devices) == 1 else None)
        if selected is None:
            parser.error("Select a discovered camera with --device")
        snapshot = client.request("open", selected["id"], None)
        print("Camera controls:", snapshot["controls"])

        def frames():
            deadline = time.monotonic() + 10
            count = 0
            while count < 5 and time.monotonic() < deadline:
                payload = client.request("next")
                if payload is not None:
                    _, frame = decode_frame(payload)
                    count += 1
            if count < 5:
                raise RuntimeError(f"Only received {count}/5 preview frames in ten seconds")
            print(f"Received {count} frames: {frame.pixels.shape}, {frame.pixels.dtype}, {frame.pixel_format}")

        frames()
        if args.trigger_source:
            snapshot = client.request("timing", args.trigger_source)
            print("External-trigger readback:", snapshot["trigger_configuration"])
            print("No Arduino commands or trigger pulses were sent by this validator.")
        client.request("timing", None)
        frames()
    print("Preview, restart and requested readback checks passed. This is NOT physical synchronization certification.")


if __name__ == "__main__":
    main()
