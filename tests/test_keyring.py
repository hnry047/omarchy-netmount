"""nas_keyring against a fake Secret module; the real keyring is never touched."""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FakeSecret:
    """Records calls in place of gi.repository.Secret (libsecret)."""

    COLLECTION_DEFAULT = "default"

    class SchemaFlags:
        NONE = 0

    class SchemaAttributeType:
        STRING = "string"

    class Schema:
        @staticmethod
        def new(name, flags, attributes):
            return ("schema", name, flags, tuple(attributes))

    def __init__(self):
        self.store, self.calls, self.store_ok = {}, [], True

    def password_lookup_sync(self, schema, attributes, _cancellable):
        self.calls.append(("lookup", schema[1], attributes))
        return self.store.get(attributes["profile"])

    def password_store_sync(self, schema, attributes, collection, label, value, _c):
        self.calls.append(("store", schema[1], attributes, collection, label))
        if self.store_ok:
            self.store[attributes["profile"]] = value
        return self.store_ok

    def password_clear_sync(self, schema, attributes, _cancellable):
        self.calls.append(("clear", schema[1], attributes))
        return self.store.pop(attributes["profile"], None) is not None


class KeyringTests(unittest.TestCase):
    def setUp(self):
        self.secret = FakeSecret()
        # Plain namespaces are enough for `import gi` / `from gi.repository ...`.
        repository = types.SimpleNamespace(Secret=self.secret)
        gi = types.SimpleNamespace(
            require_version=lambda *_: None, repository=repository
        )
        modules = {"gi": gi, "gi.repository": repository}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules.pop("nas_keyring", None)
        self.addCleanup(sys.modules.pop, "nas_keyring", None)
        self.keyring = importlib.import_module("nas_keyring")

    def test_login_round_trips_under_the_plugin_schema_and_profile_id(self):
        login = {"username": "<USERNAME>", "password": "<PASSWORD>", "domain": ""}
        self.keyring.store_login("demo", login)
        self.assertEqual(self.keyring.get_login("demo"), login)
        for call in self.secret.calls:
            self.assertEqual(call[1], "org.omarchy.Netmount")
            self.assertEqual(call[2], {"profile": "demo"})
        # The label and attributes never contain the login itself.
        self.assertNotIn("<PASSWORD>", repr(self.secret.calls))

    def test_missing_login_is_none_and_forget_is_quiet(self):
        self.assertIsNone(self.keyring.get_login("unknown"))
        self.keyring.forget_login("unknown")
        self.keyring.store_login("demo", {"username": "u", "password": "p"})
        self.keyring.forget_login("demo")
        self.assertIsNone(self.keyring.get_login("demo"))

    def test_store_failure_raises(self):
        self.secret.store_ok = False
        with self.assertRaises(RuntimeError):
            self.keyring.store_login("demo", {"username": "u", "password": "p"})


if __name__ == "__main__":
    unittest.main()
