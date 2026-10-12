#!/usr/bin/python3
"""Install the user plugin without modifying packaged files."""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def backup_shell_config(config):
    """Copy the shell configuration next to itself and return the copy's path."""
    backup = config.with_name(
        "shell.json.netmount-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    with open(config, "rb") as src:
        # The backup stays owner-only whatever the source's mode: it is created
        # 0600 (shutil.copy2 would start at umask permissions and then copy the
        # source's), and only the timestamps are copied from the source.
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as dst:
                shutil.copyfileobj(src, dst)
            st = os.fstat(src.fileno())
            os.utime(backup, ns=(st.st_atime_ns, st.st_mtime_ns))
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
    return backup


def main():
    # The repository root is the plugin folder (manifest.json lives there).
    source = Path(__file__).resolve().parent
    subprocess.run(["omarchy", "plugin", "validate", str(source)], check=True)
    target = Path.home() / ".config" / "omarchy" / "plugins" / "hnry047.netmount"
    if target.exists() or target.is_symlink():
        if not target.is_symlink() or target.resolve() != source:
            raise SystemExit(
                "netmount already exists at a different location; it was not changed."
            )
    config = Path.home() / ".config" / "omarchy" / "shell.json"
    if config.exists():
        backup = backup_shell_config(config)
        print("Shell configuration backed up to " + str(backup))
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_symlink():
        target.symlink_to(source, target_is_directory=True)
    # The shell may not have discovered a freshly linked plugin yet.
    subprocess.run(["omarchy-shell", "-q", "shell", "rescanPlugins"], check=False)
    subprocess.run(
        ["omarchy", "plugin", "enable", "hnry047.netmount", "--section", "right"],
        check=True,
    )
    print("Installed netmount in the right bar section.")


if __name__ == "__main__":
    main()
