import unittest
import wave
from pathlib import Path


class CompletionSoundAssetTests(unittest.TestCase):
    def test_bundled_completion_sound_is_a_short_pcm_wav(self):
        root = Path(__file__).parents[1]
        sound_path = root / "buti_app" / "ui" / "sounds" / "recording_complete.wav"
        with wave.open(str(sound_path), "rb") as sound:
            self.assertEqual(sound.getnchannels(), 1)
            self.assertEqual(sound.getsampwidth(), 2)
            duration = sound.getnframes() / sound.getframerate()
        self.assertGreater(duration, 0.1)
        self.assertLess(duration, 1.0)

        spec_text = (root / "BURST.spec").read_text(encoding="utf-8")
        self.assertIn('"sounds"', spec_text)
        self.assertIn('"PyQt5.QtMultimedia"', spec_text)


if __name__ == "__main__":
    unittest.main()
