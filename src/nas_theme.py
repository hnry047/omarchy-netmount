"""Read only Omarchy palette and font files; accept safe colors and sizes."""

import math
import re
import tomllib
from pathlib import Path


def _toml(path):
    try:
        with Path(path).open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, ValueError):
        return {}


def _sources(theme_dir, override):
    theme_dir = (
        Path(theme_dir)
        if theme_dir is not None
        else Path.home() / ".local/state/omarchy/current/theme"
    )
    override = (
        Path(override)
        if override is not None
        else Path.home() / ".config/omarchy/shell.toml"
    )
    return theme_dir, override


def read_palette(theme_dir=None, override=None):
    theme_dir, override = _sources(theme_dir, override)
    colors = _toml(theme_dir / "colors.toml")
    if not colors:
        return {}
    roles = {}

    def flatten(values, prefix=""):
        for key, value in values.items():
            name = prefix + key
            if isinstance(value, dict):
                flatten(value, name + ".")
            else:
                roles[name] = value

    flatten(_toml(theme_dir / "shell.toml"))
    flatten(_toml(override))

    def resolve(value, fallback, depth=0):
        if not isinstance(value, str) or depth > 8:
            return fallback
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return value
        if value in roles:
            return resolve(roles[value], fallback, depth + 1)
        if value in colors:
            return resolve(colors[value], fallback, depth + 1)
        return fallback

    palette = {
        key: resolve(colors.get(key), fallback)
        for key, fallback in (
            ("background", "#101315"),
            ("foreground", "#cacccc"),
            ("accent", "#cacccc"),
            ("muted", "#707880"),
            ("green", "#7fb590"),
            ("yellow", "#e1b66c"),
            ("red", "#a55555"),
        )
    }
    palette["background"] = resolve(
        roles.get("popups.background"), palette["background"]
    )
    palette["foreground"] = resolve(roles.get("popups.text"), palette["foreground"])
    return palette


def palette_css(palette):
    names = {
        "background": "bg",
        "foreground": "fg",
        "accent": "accent",
        "muted": "muted",
        "green": "success",
        "yellow": "warning",
        "red": "error",
    }
    return "\n".join(
        f"@define-color nas_{names[key]} {color};"
        for key, color in palette.items()
        if key in names and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
    ).encode()


# Mirrors Style.font in the Omarchy shell: each token is base-size * multiplier
# unless shell.toml pins it in px.
FONT_TOKENS = (
    ("caption", 0.833),
    ("body-small", 0.917),
    ("body", 1.0),
    ("subtitle", 1.083),
    ("title", 1.167),
    ("heading", 1.333),
)

# One token below Omarchy's panels: the fixed-size popup stays compact.
FONT_CLASSES = (
    (".nas-manager, .nas-editor", "body-small"),
    (".nas-title", "body"),
    (".nas-status", "caption"),
    (".nas-subtitle", "body"),
    (".nas-section", "caption"),
    (".nas-card-title", "subtitle"),
    (".nas-path", "body-small"),
    (".nas-badge", "caption"),
    (".nas-form-heading", "subtitle"),
    (".nas-message", "body-small"),
)


def _px(value, fallback):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    if not math.isfinite(value) or not 0 < value <= 200:
        return fallback
    return max(1, math.floor(value + 0.5))


def read_fonts(theme_dir=None, override=None):
    theme_dir, override = _sources(theme_dir, override)
    values = {}
    for source in (_toml(theme_dir / "shell.toml"), _toml(override)):
        font = source.get("font")
        if isinstance(font, dict):
            values.update(font)
    base = _px(values.get("base-size"), 12)
    return {
        name: _px(values.get(name), max(1, math.floor(base * scale + 0.5)))
        for name, scale in FONT_TOKENS
    }


def font_css(fonts):
    return "\n".join(
        f"{selector} {{ font-size: {int(fonts[token])}px; }}"
        for selector, token in FONT_CLASSES
    ).encode()
