import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FakeKeyring:
    def __init__(self, fail=False):
        self.entries = {}
        self.fail = fail

    def get_login(self, ident):
        if self.fail:
            raise RuntimeError("<PRIVATE_ERROR>")
        return self.entries.get(ident)

    def store_login(self, ident, login):
        if self.fail:
            raise RuntimeError("<PRIVATE_ERROR>")
        self.entries[ident] = login

    def forget_login(self, ident):
        if self.fail:
            raise RuntimeError("<PRIVATE_ERROR>")
        self.entries.pop(ident, None)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("nas_manager"),
            "NAS manager implementation missing",
        )
        import nas_manager

        self.module = nas_manager
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "profiles.json"
        self.keyring = FakeKeyring()
        self.mounts = []
        self.manager = nas_manager.Manager(
            self.path, self.keyring, mounts_fn=lambda: self.mounts
        )
        self.p = {
            "id": "demo",
            "label": "Demo",
            "server": "nas",
            "remote": "backup",
            "local": "/mnt/nas",
        }
        self.login = {"username": "<USERNAME>", "password": "<PASSWORD>", "domain": ""}

    def test_saved_login_never_enters_profile_file(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=True)
        stored = json.loads(self.path.read_text())
        self.assertNotIn("password", stored[0])
        self.assertNotIn("username", stored[0])
        self.assertEqual(self.manager.login("demo"), self.login)

    def test_security_choices_are_saved_with_the_connection(self):
        relaxed = dict(self.p, encrypt=False, allow_exec=True)
        self.manager.save(relaxed, self.login, remember=True, remember_login=False)
        saved = self.manager.find("demo")
        self.assertFalse(saved["encrypt"])
        self.assertTrue(saved["allow_exec"])
        record = json.loads(self.path.read_text())[0]
        self.assertFalse(record["encrypt"])
        self.assertTrue(record["allow_exec"])

    def test_keyring_failure_allows_unsaved_login(self):
        self.keyring.fail = True
        warning = self.manager.save(
            self.p, self.login, remember=True, remember_login=True
        )
        self.assertIn("keyring", warning.lower())
        self.assertNotIn("PRIVATE_ERROR", warning)
        self.assertEqual(self.manager.login("demo"), self.login)
        self.assertNotIn("PASSWORD", self.path.read_text())

    def test_session_only_connection_is_not_persisted(self):
        self.manager.save(self.p, self.login, remember=False, remember_login=False)
        self.assertEqual(json.loads(self.path.read_text()), [])
        self.assertEqual(len(self.manager.profiles), 1)
        self.assertEqual(self.manager.login("demo"), self.login)

    def test_login_cannot_be_remembered_without_connection(self):
        with self.assertRaises(ValueError):
            self.manager.save(self.p, self.login, remember=False, remember_login=True)

    def test_forget_mounted_connection_is_refused(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        self.mounts = [
            {
                "target": "/mnt/nas",
                "source": "//nas/backup",
                "root": "/",
                "fstype": "cifs",
            }
        ]
        with self.assertRaises(self.module.OperationError):
            self.manager.forget("demo")
        self.assertEqual(len(self.manager.profiles), 1)

    def test_edit_mounted_connection_is_refused(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        self.mounts = [
            {
                "target": "/mnt/nas",
                "source": "//nas/backup",
                "root": "/",
                "fstype": "cifs",
            }
        ]
        with self.assertRaises(self.module.OperationError):
            self.manager.save(
                dict(self.p, remote="other"),
                self.login,
                remember=True,
                remember_login=False,
            )

    def mounted(self):
        self.mounts = [
            {
                "target": "/mnt/nas",
                "source": "//nas/backup",
                "root": "/",
                "fstype": "cifs",
            }
        ]

    def test_adding_the_same_share_and_folder_updates_that_connection(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        self.mounted()
        self.manager.save(
            dict(self.p, id="other", label="Backups"),
            self.login,
            remember=True,
            remember_login=False,
        )
        self.assertEqual([p["id"] for p in self.manager.profiles], ["demo"])
        self.assertEqual(self.manager.find("demo")["label"], "Backups")

    def test_mounted_connection_can_be_renamed_without_unmounting(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        self.mounted()
        self.manager.save(
            dict(self.p, label="Renamed"),
            self.login,
            remember=True,
            remember_login=False,
        )
        self.assertEqual(self.manager.find("demo")["label"], "Renamed")

    def test_move_reorders_and_persists_saved_connections(self):
        for ident, local in (("a", "/mnt/a"), ("b", "/mnt/b"), ("c", "/mnt/c")):
            self.manager.save(
                dict(self.p, id=ident, label=ident.upper(), local=local),
                self.login,
                remember=ident != "b",
                remember_login=False,
            )
        self.manager.move("c", 0)
        self.assertEqual([p["id"] for p in self.manager.profiles], ["c", "a", "b"])
        saved = [r["id"] for r in json.loads(self.path.read_text())]
        self.assertEqual(saved, ["c", "a"])  # session-only "b" is never written
        self.manager.move("c", 99)
        self.assertEqual([p["id"] for p in self.manager.profiles], ["a", "b", "c"])
        with self.assertRaises(ValueError):
            self.manager.move("missing", 0)

    def test_forget_removes_profile_and_login(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=True)
        self.manager.forget("demo")
        self.assertEqual(self.manager.profiles, [])
        self.assertEqual(self.keyring.entries, {})
        self.assertEqual(json.loads(self.path.read_text()), [])

    def test_status_does_not_access_keyring(self):
        self.keyring.fail = True
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        self.assertEqual(
            self.manager.status(), {"mounted": 0, "saved": 1, "occupied": 0}
        )

    def test_duplicate_mount_folder_rejected(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        with self.assertRaises(self.module.FieldError) as caught:
            self.manager.save(
                dict(self.p, id="other", remote="photos"),
                self.login,
                remember=True,
                remember_login=False,
            )
        # Shown under the Mount folder field, naming the connection to use.
        self.assertEqual(caught.exception.field, "local")
        self.assertIn("Demo", str(caught.exception))

    def test_session_login_does_not_enable_remembered_login(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=False)
        self.assertEqual(self.manager.login("demo"), self.login)
        self.assertFalse(self.manager.find("demo")["remember_login"])
        reloaded = self.module.Manager(self.path, self.keyring, mounts_fn=lambda: [])
        self.assertIsNone(reloaded.login("demo"))

    def test_remembered_login_preference_survives_reopening(self):
        self.manager.save(self.p, self.login, remember=True, remember_login=True)
        reloaded = self.module.Manager(self.path, self.keyring, mounts_fn=lambda: [])
        self.assertTrue(reloaded.find("demo")["remember_login"])
        self.assertEqual(reloaded.login("demo"), self.login)

    def test_failed_keyring_save_does_not_enable_stale_login(self):
        self.keyring.entries["demo"] = {"username": "old", "password": "<OLD_PASSWORD>"}
        self.keyring.fail = True
        self.manager.save(self.p, self.login, remember=True, remember_login=True)
        self.assertFalse(self.manager.find("demo")["remember_login"])
        self.keyring.fail = False
        reloaded = self.module.Manager(self.path, self.keyring, mounts_fn=lambda: [])
        self.assertIsNone(reloaded.login("demo"))


if __name__ == "__main__":
    unittest.main()
