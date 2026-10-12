import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.config = self.dir / "shell.json"
        self.config.write_text('{"synthetic": true}')
        self.config.chmod(0o600)
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)

    def test_backup_is_never_readable_by_others(self):
        modes = []
        real_copystat = shutil.copystat

        def spy(src, dst, **kwargs):
            modes.append(stat.S_IMODE(os.stat(dst).st_mode))
            return real_copystat(src, dst, **kwargs)

        with patch("shutil.copystat", spy):
            backup = install.backup_shell_config(self.config)
        modes.append(stat.S_IMODE(backup.stat().st_mode))
        self.assertEqual(backup.read_text(), '{"synthetic": true}')
        for mode in modes:
            self.assertEqual(mode & 0o077, 0, oct(mode))

    def test_backup_keeps_the_source_timestamps(self):
        os.utime(self.config, (1_000_000_000, 1_000_000_000))
        backup = install.backup_shell_config(self.config)
        self.assertEqual(backup.stat().st_mtime, 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
