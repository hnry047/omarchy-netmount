"""nas_app.status(): what the bar polls; synthetic profiles, no keyring."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import nas_app  # noqa: E402


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "profiles.json"
        patcher = patch.object(nas_app, "PROFILE_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, *locals_):
        records = [
            {
                "id": f"p{i}",
                "label": f"Share {i}",
                "server": "fileserver",
                "remote": f"share{i}",
                "local": local,
            }
            for i, local in enumerate(locals_)
        ]
        self.path.write_text(json.dumps(records))

    def test_counts_saved_mounted_and_occupied(self):
        self.save("/mnt/a", "/mnt/b", "/mnt/c")
        mounts = [
            {"target": "/mnt/a", "source": "//fileserver/share0", "fstype": "cifs"},
            {"target": "/mnt/b", "source": "//other/x", "fstype": "cifs"},
        ]
        with patch.object(nas_app, "read_mounts", return_value=mounts):
            result = nas_app.status()
        self.assertEqual(
            result, {"mounted": 1, "saved": 3, "occupied": 1, "error": False}
        )

    def test_no_profile_file_means_nothing_saved(self):
        with patch.object(nas_app, "read_mounts", return_value=[]):
            self.assertEqual(nas_app.status()["saved"], 0)

    def test_broken_profile_file_reports_an_error_without_details(self):
        self.path.write_text("{not json")
        self.assertEqual(
            nas_app.status(),
            {"mounted": 0, "saved": 0, "occupied": 0, "error": True},
        )


if __name__ == "__main__":
    unittest.main()
