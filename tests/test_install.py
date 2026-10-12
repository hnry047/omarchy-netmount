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

    def backups(self):
        return sorted(self.dir.glob("shell.json.netmount-backup-*"))

    def test_backup_is_never_readable_by_others(self):
        for source_mode in (0o600, 0o644):
            with self.subTest(source_mode=oct(source_mode)):
                self.config.chmod(source_mode)
                modes = []
                real_copy = shutil.copyfileobj

                def spy(src, dst, *args, modes=modes, real_copy=real_copy):
                    modes.append(stat.S_IMODE(os.fstat(dst.fileno()).st_mode))
                    return real_copy(src, dst, *args)

                with patch("shutil.copyfileobj", spy):
                    backup = install.backup_shell_config(self.config)
                modes.append(stat.S_IMODE(backup.stat().st_mode))
                self.assertEqual(backup.read_text(), '{"synthetic": true}')
                self.assertEqual(len(modes), 2)
                for mode in modes:
                    self.assertEqual(mode & 0o077, 0, oct(mode))
                backup.unlink()

    def test_unreadable_source_leaves_no_backup(self):
        with patch("builtins.open", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                install.backup_shell_config(self.config)
        self.assertEqual(self.backups(), [])

    def test_failed_copy_removes_the_partial_backup(self):
        with patch("shutil.copyfileobj", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                install.backup_shell_config(self.config)
        self.assertEqual(self.backups(), [])

    def test_backup_keeps_the_source_timestamps(self):
        os.utime(self.config, (1_000_000_000, 1_000_000_000))
        backup = install.backup_shell_config(self.config)
        self.assertEqual(backup.stat().st_mtime, 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
