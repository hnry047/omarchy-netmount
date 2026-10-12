"""The one-manager lock, with temporary paths and a fake toggle request."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import nas_single  # noqa: E402


class ClaimManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = Path(self.tmp.name) / "state" / "manager.lock"
        self.sock = self.lock.with_suffix(".sock")
        self.sleeps = []

    def claim(self, toggle):
        return nas_single.claim_manager(
            self.lock, self.sock, b"warm", toggle=toggle, sleep=self.sleeps.append
        )

    def own(self):
        outcome, fd = self.claim(lambda *_: False)
        self.assertEqual(outcome, "owner")
        assert fd is not None
        self.addCleanup(os.close, fd)
        return fd

    def test_first_claim_owns_a_private_lock(self):
        self.own()
        self.assertEqual(self.lock.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.lock.stat().st_mode & 0o777, 0o600)

    def test_second_claim_hands_off_to_the_running_manager(self):
        self.own()
        answers = iter([False, False, True])
        self.assertEqual(self.claim(lambda *_: next(answers)), ("handed_off", None))
        self.assertEqual(len(self.sleeps), 2)

    def test_second_claim_reports_busy_when_the_manager_never_answers(self):
        self.own()
        self.assertEqual(self.claim(lambda *_: False), ("busy", None))
        self.assertEqual(len(self.sleeps), 20)

    def test_symlinked_lock_file_is_refused(self):
        self.lock.parent.mkdir(mode=0o700)
        target = Path(self.tmp.name) / "elsewhere"
        target.touch()
        self.lock.symlink_to(target)
        with self.assertRaises(OSError):
            self.claim(lambda *_: False)


if __name__ == "__main__":
    unittest.main()
