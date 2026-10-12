"""Runtime-only Secret Service access for this application's profile IDs."""

import json

import gi

gi.require_version("Secret", "1")
# require_version must run first, so this import cannot move to the top.
from gi.repository import Secret  # type: ignore  # noqa: E402

SCHEMA = Secret.Schema.new(
    "org.omarchy.Netmount",
    Secret.SchemaFlags.NONE,
    {"profile": Secret.SchemaAttributeType.STRING},
)


def get_login(profile_id):
    value = Secret.password_lookup_sync(SCHEMA, {"profile": profile_id}, None)
    return json.loads(value) if value else None


def store_login(profile_id, login):
    success = Secret.password_store_sync(
        SCHEMA,
        {"profile": profile_id},
        Secret.COLLECTION_DEFAULT,
        "Netmount login",
        json.dumps(login),
        None,
    )
    if not success:
        raise RuntimeError("Keyring storage unavailable")


def forget_login(profile_id):
    # False means no matching entry existed; exceptions represent actual failures.
    Secret.password_clear_sync(SCHEMA, {"profile": profile_id}, None)
