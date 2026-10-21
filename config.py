"""
Configuration constants for the Decart Livestream Studio desktop app.

Everything that a user might reasonably want to tweak lives here so the rest of
the code stays declarative and easy to read.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# App metadata
# --------------------------------------------------------------------------- #
APP_NAME = "Decart Livestream Studio"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Realtime AI video transformation powered by Decart Lucy"

# --------------------------------------------------------------------------- #
# Decart endpoints (defaults come from the official SDK; overridable at runtime)
# --------------------------------------------------------------------------- #
DEFAULT_BASE_URL = "https://api.decart.ai"
DEFAULT_REALTIME_BASE_URL = "wss://api3.decart.ai"

# --------------------------------------------------------------------------- #
# Realtime models exposed in the UI.
#   key   -> value passed to models.realtime(...)
#   value -> human readable label shown in the dropdown
# --------------------------------------------------------------------------- #
REALTIME_MODELS = {
    "lucy-2.1": "Lucy 2.1  -  character transform (1088x624)",
    "lucy-2.5": "Lucy 2.5  -  flagship realtime (1280x720, fast mode)",
    "lucy-latest": "Lucy latest  -  newest realtime model",
    "lucy-restyle-2": "Lucy Restyle 2  -  style transfer (1280x704)",
}
DEFAULT_MODEL = "lucy-2.1"

# --------------------------------------------------------------------------- #
# Output resolutions supported by the Decart realtime API.
#
# IMPORTANT: The Decart realtime API currently caps output at 1080p. There is
# no 4K option in the realtime API, so 1080p is the maximum quality obtainable.
# The app defaults to 1080p and exposes 720p as a lighter-bandwidth option.
# --------------------------------------------------------------------------- #
RESOLUTIONS = ["720p", "1080p"]
DEFAULT_RESOLUTION = "1080p"  # maximum quality available from the API

# --------------------------------------------------------------------------- #
# View modes -> stream orientation
# --------------------------------------------------------------------------- #
VIEW_DESKTOP = "desktop"  # landscape 16:9  (model.width  x model.height)
VIEW_MOBILE = "mobile"    # portrait  9:16  (model.height x model.width)
DEFAULT_VIEW = VIEW_DESKTOP

# --------------------------------------------------------------------------- #
# Input video sources
# --------------------------------------------------------------------------- #
SOURCE_WEBCAM = "webcam"    # live camera
SOURCE_PICTURE = "picture"  # stream the chosen reference picture as a static feed
DEFAULT_SOURCE = SOURCE_WEBCAM

# --------------------------------------------------------------------------- #
# Reference image best practices (from the Decart Lucy 2.1 documentation).
#
# A clear, well-lit, front-facing portrait with neutral expression and
# head-and-shoulders framing produces the most consistent character
# transformation. JPEG / PNG / WebP are supported; >=512x512 px recommended.
# --------------------------------------------------------------------------- #
REFERENCE_MIN_SIZE = 512  # minimum recommended edge length, in pixels
REFERENCE_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}
REFERENCE_HINT = ("Optional \u2014 leave empty for text-only editing. "
                  "Best results: clear, well-lit, front-facing portrait, "
                  "head-and-shoulders framing, \u2265512\u00d7512 px (JPEG/PNG/WebP).")

# --------------------------------------------------------------------------- #
# Prompt templates from the Lucy 2.1 prompting guide.
#
# Lucy 2.1 supports four edit operations, each with its own prompt structure.
# Selecting a template inserts it into the streaming-description box so users
# start from a well-structured prompt (which beats relying on auto-enhance).
# --------------------------------------------------------------------------- #
PROMPT_TEMPLATES = {
    "Character transform \u2014 \u201cSubstitute the character\u2026\u201d": (
        "Substitute the character in the video with <describe the person in your "
        "reference image: skin tone, hair, eyes, clothing, distinctive features>."
    ),
    "Add an object \u2014 \u201cAdd <object> to <where>\u201d": (
        "Add <description of the object in the reference image> to <where to add it, "
        "e.g. the person\u2019s head>."
    ),
    "Replace an object \u2014 \u201cChange <object> with <new>\u201d": (
        "Change <object to change> with <description of the object in the "
        "reference image>."
    ),
    "Change an attribute \u2014 \u201cChange <object>\u2019s <attribute>\u201d": (
        "Change <object to change attribute of> to <description of the new attribute>."
    ),
}
DEFAULT_PROMPT = (
    "Replace the live video person's appearance with the identity in the reference "
    "image. The live video is the motion source: follow its head and body movement, "
    "pose, facial expression, and speaking mouth motion in real time. Use the "
    "reference image for identity and appearance only, not as the motion source. "
    "Preserve natural proportions and framing."
)

# --------------------------------------------------------------------------- #
# UI palette (dark, modern)
# --------------------------------------------------------------------------- #
COLOR_BG = "#0e1016"
COLOR_PANEL = "#161a24"
COLOR_PANEL_ALT = "#1d2230"
COLOR_BORDER = "#2a3142"
COLOR_TEXT = "#e7ebf3"
COLOR_TEXT_DIM = "#9aa4b8"
COLOR_ACCENT = "#7c5cff"        # Decart-ish violet
COLOR_ACCENT_HOVER = "#8f74ff"
COLOR_CONNECT = "#2ecc71"
COLOR_CONNECT_HOVER = "#27b866"
COLOR_DISCONNECT = "#ff5c5c"
COLOR_DISCONNECT_HOVER = "#e14b4b"
COLOR_WARN = "#ffb84d"

# Connection-state -> (label, color)
STATE_STYLES = {
    "disconnected": ("Disconnected", COLOR_TEXT_DIM),
    "connecting": ("Connecting…", COLOR_WARN),
    "connected": ("Connected", COLOR_CONNECT),
    "generating": ("Generating", COLOR_CONNECT),
    "reconnecting": ("Reconnecting…", COLOR_WARN),
    "error": ("Error", COLOR_DISCONNECT),
}

# --------------------------------------------------------------------------- #
# Local settings persistence (API key is only stored if the user opts in)
# --------------------------------------------------------------------------- #
SETTINGS_FILENAME = ".decart_livestream.json"

# Target UI refresh interval in milliseconds (~60 fps preview)
PREVIEW_INTERVAL_MS = 15
