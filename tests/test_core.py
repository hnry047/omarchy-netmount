import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("nas_core"), "NAS core implementation missing"
        )
        import nas_core

        self.core = nas_core

    def profile(self):
        return dict(
            self.core.normalize(
                r"\\FileServer", r"shared_docs\folder", "/mnt/nas backups"
            ),
            id="demo",
            label="Demo",
        )

    def test_windows_notation(self):
        self.assertEqual(self.profile()["source"], "//FileServer/shared_docs/folder")

    def test_ip_and_unc_path(self):
        p = self.core.normalize("192.0.2.10", r"\\192.0.2.10\shared_docs", "/mnt/nas")
        self.assertEqual(p["source"], "//192.0.2.10/shared_docs")

    def test_reject_unsafe_server_and_remote(self):
        for server, remote in [
            ("nas,guest", "backup"),
            ("nas\n", "backup"),
            ("nas", "../backup"),
            ("nas", "share,guest"),
            ("nas", "share\n"),
        ]:
            with (
                self.subTest(server=server, remote=remote),
                self.assertRaises(ValueError),
            ):
                self.core.normalize(server, remote, "/mnt/nas")

    def test_reject_unsafe_mount_targets(self):
        for path in [
            "/",
            "/etc",
            "/mnt",
            os.path.expanduser("~"),
            "/mnt/../etc",
            "relative",
        ]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.core.normalize("nas", "backup", path)

    def test_source_mismatch_occupied(self):
        p = self.profile()
        mounts = [
            {
                "target": p["local"],
                "source": "//other/share",
                "fstype": "cifs",
                "root": "/",
            }
        ]
        self.assertEqual(self.core.mount_state(p, mounts), "occupied")

    def test_matching_subdirectory_mount(self):
        p = self.profile()
        mounts = [
            {
                "target": p["local"],
                "source": "//FileServer/shared_docs",
                "fstype": "cifs",
                "root": "/folder",
            }
        ]
        self.assertEqual(self.core.mount_state(p, mounts), "mounted")

    def test_different_subdirectory_occupied(self):
        p = self.profile()
        mounts = [
            {
                "target": p["local"],
                "source": "//FileServer/shared_docs",
                "fstype": "cifs",
                "root": "/other",
            }
        ]
        self.assertEqual(self.core.mount_state(p, mounts), "occupied")

    def test_remote_subfolder_case_is_not_ignored(self):
        p = self.profile()
        mounts = [
            {
                "target": p["local"],
                "source": "//fileserver/shared_docs",
                "fstype": "cifs",
                "root": "/Folder",
            }
        ]
        self.assertEqual(self.core.mount_state(p, mounts), "occupied")

    def test_share_root_does_not_match_a_mounted_subfolder(self):
        p = self.core.normalize("nas", "share", "/mnt/nas")
        mounts = [
            {
                "target": "/mnt/nas",
                "source": "//nas/share",
                "fstype": "cifs",
                "root": "/other",
            }
        ]
        self.assertEqual(self.core.mount_state(p, mounts), "occupied")

    def test_mount_refuses_symlink_to_system_folder(self):
        with patch.object(os.path, "realpath", return_value="/etc"):
            with self.assertRaises(ValueError):
                self.core.mount(
                    self.profile(),
                    {"username": "demo", "password": "<PASSWORD>"},
                    runner=lambda *a, **k: self.fail("must not execute"),
                    mounts_fn=lambda: [],
                )

    def test_normalization_never_touches_the_mount_folder(self):
        with patch.object(
            os.path,
            "realpath",
            side_effect=AssertionError("offline NAS must not be touched"),
        ):
            self.assertEqual(self.profile()["local"], "/mnt/nas backups")

    def test_profile_save_allowlist_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            p = dict(self.profile(), password="<PASSWORD>", username="<USERNAME>")
            self.core.save_profiles(path, [p])
            content = json.loads(path.read_text())
            self.assertNotIn("password", content[0])
            self.assertNotIn("username", content[0])
            self.assertNotIn("source", content[0])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.core.load_profiles(path)[0]["source"], p["source"])

    def test_mount_file_cleanup_on_cancel_and_no_login_in_argv(self):
        calls = []
        ephemeral = []

        def runner(args, **kwargs):
            calls.append(args)
            if "cifs" in args:
                option = args[-1]
                name = option.split("credentials=", 1)[1].split(",", 1)[0]
                ephemeral.append(name)
                self.assertTrue(Path(name).exists())
                self.assertEqual(Path(name).stat().st_mode & 0o777, 0o600)
                return subprocess.CompletedProcess(args, 126, "", "<PRIVATE_ERROR>")
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            tempfile.TemporaryDirectory() as runtime,
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}),
        ):
            with self.assertRaises(self.core.OperationError):
                self.core.mount(
                    self.profile(),
                    {"username": "<USERNAME>", "password": "<PASSWORD>", "domain": ""},
                    runner=runner,
                    mounts_fn=lambda: [],
                )
        self.assertTrue(ephemeral)
        self.assertFalse(Path(ephemeral[0]).exists())
        self.assertNotIn("<PASSWORD>", repr(calls))
        self.assertNotIn("<USERNAME>", repr(calls))

    def mount_options(self, profile, stderr=None):
        """Run mount with a fake runner and return the cifs -o string."""
        seen = []

        def runner(args, **kwargs):
            if "cifs" in args:
                seen.append(args[-1])
                if stderr:
                    return subprocess.CompletedProcess(args, 32, "", stderr)
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            tempfile.TemporaryDirectory() as runtime,
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}),
            patch("nas_core.os.path.isdir", return_value=True),
        ):
            try:
                self.core.mount(
                    profile,
                    {"username": "demo", "password": "<PASSWORD>", "domain": ""},
                    runner=runner,
                    mounts_fn=lambda: [],
                )
            except self.core.OperationError as exc:
                if not stderr:
                    self.assertIn("could not be confirmed", str(exc))
                else:
                    raise
        return seen[0].split(",")

    def test_mount_defaults_to_encrypted_smb3_without_exec(self):
        options = self.mount_options(self.profile())
        for flag in ("vers=3", "seal", "noexec", "nosuid", "nodev"):
            self.assertIn(flag, options)

    def test_mount_hardening_can_be_relaxed_per_connection(self):
        options = self.mount_options(
            dict(self.profile(), encrypt=False, allow_exec=True)
        )
        self.assertNotIn("seal", options)
        self.assertNotIn("vers=3", options)
        self.assertNotIn("noexec", options)
        self.assertIn("nosuid", options)
        self.assertIn("file_mode=0700", options)

    def test_mounted_share_is_private_to_the_user(self):
        # Other local users must not read the share through this user's login.
        options = self.mount_options(self.profile())
        self.assertIn("file_mode=0600", options)
        self.assertIn("dir_mode=0700", options)
        # The client must enforce those modes, so permission checks stay on.
        self.assertNotIn("noperm", options)

    def test_unsupported_encryption_explains_the_setting(self):
        with self.assertRaises(self.core.OperationError) as caught:
            self.mount_options(
                self.profile(), stderr="mount error(95): Operation not supported"
            )
        self.assertIn("Encrypt traffic", str(caught.exception))

    def test_security_flags_persist_and_default_on_for_old_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            self.core.save_profiles(
                path, [dict(self.profile(), encrypt=False, allow_exec=True)]
            )
            loaded = self.core.load_profiles(path)[0]
            self.assertFalse(loaded["encrypt"])
            self.assertTrue(loaded["allow_exec"])
            records = json.loads(path.read_text())
            for key in ("encrypt", "allow_exec"):
                del records[0][key]
            path.write_text(json.dumps(records))
            loaded = self.core.load_profiles(path)[0]
            self.assertTrue(loaded["encrypt"])
            self.assertFalse(loaded["allow_exec"])

    def test_input_errors_name_the_field_to_fix(self):
        cases = (
            (lambda: self.core.normalize("bad host!", "share", "/mnt/x"), "server"),
            (lambda: self.core.normalize("nas", "a,b", "/mnt/x"), "remote"),
            (lambda: self.core.normalize("nas", "share", "/etc/x"), "local"),
            (
                lambda: self.core.validate_login(
                    {"username": " ", "password": "", "domain": ""}
                ),
                "username",
            ),
        )
        for call, field in cases:
            with (
                self.subTest(field=field),
                self.assertRaises(self.core.FieldError) as caught,
            ):
                call()
            self.assertEqual(caught.exception.field, field)

    def test_mount_failures_name_the_field_to_fix(self):
        cases = (
            ("mount error(13): Permission denied", "password"),
            ("could not resolve address for nas", "server"),
            ("mount error(2): No such file or directory", "remote"),
            ("mount error(95): Operation not supported", "encrypt"),
            ("mount error(5): something else", None),
        )
        for stderr, field in cases:
            with (
                self.subTest(field=field),
                self.assertRaises(self.core.OperationError) as caught,
            ):
                self.mount_options(self.profile(), stderr=stderr)
            self.assertEqual(caught.exception.field, field)

    def test_read_mounts_parses_local_mount_metadata(self):
        mounts = self.core.read_mounts()
        root = next(m for m in mounts if m["target"] == "/")
        self.assertEqual(set(root), {"target", "root", "fstype", "source"})

    def test_mount_paths_with_spaces_are_unescaped(self):
        self.assertEqual(
            self.core._unescape(r"/mnt/nas\040backups"), "/mnt/nas backups"
        )

    def test_mount_refuses_occupied_target(self):
        p = self.profile()
        calls = []
        with self.assertRaises(self.core.OperationError) as caught:
            self.core.mount(
                p,
                {"username": "demo", "password": "<PASSWORD>"},
                runner=lambda *a, **k: calls.append(a),
                mounts_fn=lambda: [
                    {
                        "target": p["local"],
                        "source": "//foreign/share",
                        "fstype": "cifs",
                        "root": "/",
                    }
                ],
            )
        self.assertEqual(calls, [])
        self.assertEqual(caught.exception.field, "local")

    def test_mount_of_an_already_mounted_share_succeeds_quietly(self):
        p = self.profile()
        self.core.mount(
            p,
            {"username": "demo", "password": "<PASSWORD>", "domain": ""},
            runner=lambda *a, **k: self.fail("must not ask for authorization"),
            mounts_fn=lambda: [
                {
                    "target": p["local"],
                    "source": p["source"],
                    "fstype": "cifs",
                    "root": "/",
                }
            ],
        )

    def test_login_newline_rejected(self):
        with self.assertRaises(ValueError):
            self.core.mount(
                self.profile(),
                {"username": "demo", "password": "line\ninjection"},
                runner=lambda *a, **k: self.fail("must not execute"),
                mounts_fn=lambda: [],
            )

    def test_busy_unmount_sanitized_and_not_forced(self):
        p = self.profile()
        calls = []

        def runner(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(
                args, 32, "", "target is busy <PRIVATE_ERROR>"
            )

        with self.assertRaisesRegex(self.core.OperationError, "busy") as caught:
            self.core.unmount(
                p,
                runner=runner,
                mounts_fn=lambda: [
                    {
                        "target": p["local"],
                        "source": p["source"],
                        "fstype": "cifs",
                        "root": "/",
                    }
                ],
            )
        self.assertNotIn("PRIVATE_ERROR", str(caught.exception))
        self.assertNotIn("-f", calls[0])
        self.assertNotIn("-l", calls[0])

    def test_foreign_mount_never_unmounted(self):
        p = self.profile()
        with self.assertRaises(self.core.OperationError):
            self.core.unmount(
                p,
                runner=lambda *a, **k: self.fail("must not execute"),
                mounts_fn=lambda: [
                    {
                        "target": p["local"],
                        "source": "//foreign/share",
                        "fstype": "cifs",
                        "root": "/",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
