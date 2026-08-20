"""Bundled recording-completion sound choices."""

DEFAULT_COMPLETION_SOUND = "gentle_chime"

COMPLETION_SOUNDS = (
    {
        "id": "gentle_chime",
        "label": "Gentle Chime",
        "filename": "gentle_chime.wav",
        "volume": 0.55,
    },
    {
        "id": "soft_bell",
        "label": "Soft Bell",
        "filename": "soft_bell.wav",
        "volume": 0.5,
    },
    {
        "id": "warm_chime",
        "label": "Warm Chime",
        "filename": "warm_chime.wav",
        "volume": 0.55,
    },
    {
        "id": "classic",
        "label": "Classic",
        "filename": "recording_complete.wav",
        "volume": 0.7,
    },
)


def get_completion_sound(sound_id):
    """Return a valid sound definition, falling back to the new default."""

    for sound in COMPLETION_SOUNDS:
        if sound["id"] == sound_id:
            return sound
    return next(
        sound
        for sound in COMPLETION_SOUNDS
        if sound["id"] == DEFAULT_COMPLETION_SOUND
    )
