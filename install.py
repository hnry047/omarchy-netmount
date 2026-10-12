#!/usr/bin/python3
"""Install the user plugin without modifying packaged files."""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path


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
        backup = config.with_name(
            "shell.json.netmount-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        )
        shutil.copy2(config, backup)
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
