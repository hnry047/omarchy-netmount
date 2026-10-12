#!/usr/bin/python3
"""NAS connection manager. `status` never accesses login storage."""

import json
import os
import signal
import sys
from pathlib import Path

from nas_core import (
    load_profiles,
    mount_state,
    read_mounts,
)

PROFILE_PATH = Path.home() / ".config" / "omarchy-netmount" / "profiles.json"
MANAGER_LOCK_PATH = (
    Path.home() / ".local" / "state" / "omarchy-netmount" / "manager.lock"
)


def status():
    try:
        profiles = load_profiles(PROFILE_PATH)
        mounts = read_mounts()
        states = [mount_state(p, mounts) for p in profiles]
        return {
            "mounted": states.count("mounted"),
            "saved": len(profiles),
            "occupied": states.count("occupied"),
            "error": False,
        }
    except Exception:
        return {"mounted": 0, "saved": 0, "occupied": 0, "error": True}


def load_gtk():
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk  # type: ignore  # generated at runtime

    return Gtk, Gdk, GLib


def main():
    from nas_geometry import launch_bar
    from nas_single import claim_manager
    from nas_toggle import ToggleServer, request_toggle

    resident = "--preload" in sys.argv
    position, bar_size = launch_bar(sys.argv)
    request = b"warm" if resident else f"toggle {position} {bar_size}".encode("ascii")
    socket_path = MANAGER_LOCK_PATH.with_suffix(".sock")
    if request_toggle(socket_path, request):
        return
    Gtk, Gdk, GLib = load_gtk()
    GLib.set_prgname("omarchy-netmount")
    from gi.repository import GLibUnix  # type: ignore  # generated at runtime

    import nas_keyring
    from nas_manager import Manager
    from nas_ui import install_style

    # A single manager owns session-only profiles and serializes all user operations.
    outcome, fd = claim_manager(MANAGER_LOCK_PATH, socket_path, request)
    if fd is None:
        if outcome == "handed_off" or resident:
            return
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Netmount is already open",
        )
        dialog.format_secondary_text(
            "Use the open Netmount window to manage your connections."
        )
        dialog.run()
        dialog.destroy()
        return

    from nas_window import ManagerWindow

    refresh_style = install_style(Gtk, Gdk)

    gate = None
    gate_watch = None
    signal_watch = None
    try:
        window = ManagerWindow(
            manager_factory=lambda: Manager(PROFILE_PATH, nas_keyring),
            resident=resident,
            position=position,
            bar_size=bar_size,
            refresh_style=refresh_style,
        )
        gate = ToggleServer(socket_path)
        gate_watch = GLib.io_add_watch(
            gate.socket.fileno(),
            GLib.PRIORITY_DEFAULT,
            GLib.IO_IN,
            lambda *_: gate.receive(window.close, window.toggle),
        )
        if not resident:
            window.show_all()
        else:
            # Warm font/layout caches without mapping the top-level window.
            window.get_child().show_all()
            window.get_preferred_size()
            window.realize()
        signal_watch = GLibUnix.signal_add(
            GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or True
        )
        Gtk.main()
    except Exception:
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Netmount could not open",
        )
        dialog.format_secondary_text(
            "Check the saved connection file and installed GTK/Secret Service dependencies."
        )
        dialog.run()
        dialog.destroy()
    finally:
        if signal_watch is not None:
            GLib.source_remove(signal_watch)
        if gate_watch is not None:
            GLib.source_remove(gate_watch)
        if gate is not None:
            gate.close()
        os.close(fd)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "status":
        print(json.dumps(status()))
    else:
        main()
