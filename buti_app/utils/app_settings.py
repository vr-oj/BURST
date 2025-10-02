# buti_app/utils/app_settings.py
import json
import os
import logging
from .config import APP_CONFIG_DIR

log = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(APP_CONFIG_DIR, "buti_settings.json")

# Ensure the APP_CONFIG_DIR exists when this module is loaded
os.makedirs(APP_CONFIG_DIR, exist_ok=True)


def save_app_setting(key, value):
    """Saves a specific setting to the application settings file."""
    settings = load_app_settings()
    settings[key] = value
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
        log.debug(f"Saved app setting: {{'{key}': '{value}'}} to {SETTINGS_FILE}")
    except IOError as e:
        log.error(f"Error saving settings to {SETTINGS_FILE}: {e}")


def load_app_setting(key, default=None):
    """Loads a specific setting from the application settings file."""
    settings = load_app_settings()
    value = settings.get(key, default)
    log.debug(
        f"Loaded app setting: {{'{key}': '{value}' (default: '{default}')}} from {SETTINGS_FILE}"
    )
    return value


def load_app_settings():
    """Loads all settings from the application settings file."""
    if not os.path.exists(SETTINGS_FILE):
        log.debug(
            f"Settings file not found: {SETTINGS_FILE}. Returning empty settings."
        )
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            log.debug(f"Successfully loaded settings from {SETTINGS_FILE}")
            return settings
    except (IOError, json.JSONDecodeError) as e:
        log.error(f"Error loading or parsing settings from {SETTINGS_FILE}: {e}")
        return {}


# --- Constants for setting keys ---
SETTING_LAST_CAMERA_INDEX = "last_camera_index"
SETTING_LAST_PROFILE_NAME = "last_profile_name"
SETTING_RESULTS_DIR = "results_dir"
SETTING_OPEN_FOLDER_PROMPT = "open_folder_prompt"
