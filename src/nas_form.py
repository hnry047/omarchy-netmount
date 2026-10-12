"""Connection form text, layout data and validation; no GUI or keyring access."""

from nas_core import clean_label, normalize, validate_login

FIELDS = (
    ("label", "Connection name"),
    ("server", "Server address"),
    ("remote", "Shared folder"),
    ("local", "Mount folder"),
    ("username", "Username"),
    ("password", "Password"),
    ("domain", "Domain"),
)

HINTS = {
    "label": "e.g. Shared documents",
    "server": "IP address or hostname, e.g. fileserver",
    "remote": "e.g. shared/documents",
    "local": "/mnt/nas-documents",
    "username": "Your NAS username",
    "password": "Your NAS password",
    "domain": "Optional account domain",
}

SECTIONS = (
    ("Connection", "The server and shared folder you want to access."),
    ("Local folder", "Where the share appears on this computer."),
    ("Login", "Your NAS account. System authorization is requested separately."),
)

LOGIN_KEYS = ("username", "password", "domain")


def field_group(key):
    if key in ("label", "server", "remote"):
        return "Connection"
    return "Local folder" if key == "local" else "Login"


def form_copy(adding, login_only):
    """Title, confirm button and heading for each way the form opens.

    A new connection is mounted right away; editing only saves, so a rename
    never asks for system authorization.
    """
    if login_only:
        return {
            "title": "Connect to NAS",
            "confirm": "Mount",
            "heading": "Sign in to mount this share.",
        }
    return {
        "title": "Add connection" if adding else "Edit connection",
        "confirm": "Save and mount" if adding else "Save changes",
        "heading": "Give your shared folder a place on this computer.",
    }


def parse_form(values, profile_id, encrypt, allow_exec):
    """Validate typed values into (profile, login); FieldError names the field."""
    clean = dict(
        normalize(values["server"], values["remote"], values["local"]),
        id=profile_id,
        label=clean_label(values["label"]),
        encrypt=encrypt,
        allow_exec=allow_exec,
    )
    entered = {key: values[key] for key in LOGIN_KEYS}
    validate_login(entered)
    return clean, entered
