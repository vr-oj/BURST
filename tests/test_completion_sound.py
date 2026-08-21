import unittest
import wave
from pathlib import Path
import sys


APP_PATH = str(Path(__file__).parents[1] / "buti_app")
sys.path.insert(0, APP_PATH)
try:
    from utils.completion_sounds import (
        COMPLETION_SOUNDS,
        DEFAULT_COMPLETION_SOUND,
        get_completion_sound,
    )
finally:
    sys.path.remove(APP_PATH)


class CompletionSoundAssetTests(unittest.TestCase):
    def test_bundled_completion_sounds_are_short_pcm_wavs(self):
        root = Path(__file__).parents[1]
        sound_ids = {sound["id"] for sound in COMPLETION_SOUNDS}
        self.assertEqual(len(sound_ids), len(COMPLETION_SOUNDS))
        self.assertIn(DEFAULT_COMPLETION_SOUND, sound_ids)

        for definition in COMPLETION_SOUNDS:
            sound_path = (
                root / "buti_app" / "ui" / "sounds" / definition["filename"]
            )
            with self.subTest(sound=definition["id"]):
                with wave.open(str(sound_path), "rb") as sound:
                    self.assertEqual(sound.getnchannels(), 1)
                    self.assertEqual(sound.getsampwidth(), 2)
                    duration = sound.getnframes() / sound.getframerate()
                self.assertGreater(duration, 0.1)
                self.assertLess(duration, 1.0)

        spec_text = (root / "BURST.spec").read_text(encoding="utf-8")
        self.assertIn('"sounds"', spec_text)
        self.assertIn('"PyQt5.QtMultimedia"', spec_text)

    def test_unknown_sound_setting_falls_back_to_gentle_default(self):
        selected = get_completion_sound("no-longer-available")

        self.assertEqual(selected["id"], DEFAULT_COMPLETION_SOUND)


if __name__ == "__main__":
    unittest.main()
