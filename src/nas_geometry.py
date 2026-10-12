"""Screen-safe placement using only compositor geometry, never connection data."""

import json
import os
import re
import subprocess


def popup_bounds(monitor, size, position="top", bar_size=28, margin=10):
    width, height = monitor["width"], monitor["height"]
    if monitor.get("transform", 0) % 2:
        width, height = height, width
    scale = monitor.get("scale", 1)
    width, height = int(width / scale), int(height / scale)
    # Hyprland reserved order: left, top, right, bottom (logical pixels).
    left, top, right, bottom = monitor.get("reserved", [0, 0, 0, 0])
    edges = {"top": top, "bottom": bottom, "left": left, "right": right}
    if position in edges:
        edges[position] = max(edges[position], bar_size)
    x0 = int(monitor["x"] + edges["left"] + margin)
    y0 = int(monitor["y"] + edges["top"] + margin)
    x1 = int(monitor["x"] + width - edges["right"] - margin)
    y1 = int(monitor["y"] + height - edges["bottom"] - margin)
    w, h = min(size[0], max(1, x1 - x0)), min(size[1], max(1, y1 - y0))
    x = x0 if position == "left" else x1 - w
    y = y1 - h if position in ("bottom", "left", "right") else y0
    return x, y, w, h


def launch_bar(argv):
    """Resolve legacy/direct launches from Omarchy's effective live config."""
    position, bar_size = "top", 28
    if "--bar-position" not in argv:
        try:
            result = subprocess.run(
                ["omarchy-shell", "shell", "listShellConfig"],
                capture_output=True,
                text=True,
                timeout=1,
                check=True,
            )
            position = json.loads(result.stdout).get("bar", {}).get("position", "top")
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            pass
    else:
        try:
            position = argv[argv.index("--bar-position") + 1]
        except IndexError:
            pass
    if position not in ("top", "bottom", "left", "right"):
        position = "top"
    try:
        if "--bar-size" in argv:
            bar_size = min(200, max(0, int(argv[argv.index("--bar-size") + 1])))
    except (ValueError, IndexError):
        pass
    return position, bar_size


def ipc(*args):
    return subprocess.run(
        ["hyprctl", *args], capture_output=True, text=True, timeout=1, check=True
    ).stdout


def place_window(window, position, bar_size):
    """Target only this process's mapped window; retry while Wayland maps it."""
    if not window.get_visible():
        return False
    try:
        clients = json.loads(ipc("clients", "-j"))
        client = next(
            (
                c
                for c in clients
                if c["pid"] == os.getpid() and c["title"] == window.get_title()
            ),
            None,
        )
        if client is None:
            return True
        address = client["address"]
        if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
            return False
        monitor = next(
            m for m in json.loads(ipc("monitors", "-j")) if m["id"] == client["monitor"]
        )
        x, y, w, h = popup_bounds(monitor, client["size"], position, bar_size)
        selector = 'window = "address:' + address + '"'
        if [w, h] != client["size"]:
            ipc(
                "dispatch",
                f"hl.dsp.window.resize({{{selector}, x={w}, y={h}, relative=false}})",
            )
        if [x, y] != client["at"]:
            ipc(
                "dispatch",
                f"hl.dsp.window.move({{{selector}, x={x}, y={y}, relative=false}})",
            )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration):
        return False
    return False


def initial_placement(position, bar_size):
    """Install a bounded initial rule before mapping, so pop-in stays in place."""
    try:
        monitors = json.loads(ipc("monitors", "-j"))
        monitor = next((m for m in monitors if m.get("focused")), monitors[0])
        x0, y0, width, height = popup_bounds(
            monitor, (100000, 100000), position, bar_size
        )
        x0, y0 = x0 - int(monitor["x"]), y0 - int(monitor["y"])
        x = str(x0) if position == "left" else f"max({x0}, {x0 + width}-window_w)"
        y = str(y0) if position == "top" else f"max({y0}, {y0 + height}-window_h)"
        workspace = int(monitor["activeWorkspace"]["id"])
        # This rule is the plugin's only window rule, so no user Hyprland config
        # is needed. Named rules merge on redeclaration. Only numeric geometry
        # and fixed expressions enter Lua, never form values or profile data.
        ipc(
            "eval",
            'hl.window_rule({name="netmount-initial-placement", '
            'match={class="^omarchy-netmount$"}, float=true, pin=true, '
            'rounding=0, border_size=1, animation="popin 95%", '
            f'workspace="{workspace} silent", '
            f'monitor="{int(monitor["id"])}", move={{"{x}","{y}"}}, '
            f"max_size={{{width},{height}}}" + "})",
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        pass


def prepare_window(window, GLib, position, bar_size):
    window.set_decorated(False)
    initial_placement(position, bar_size)

    def mapped(*_):
        attempts = 0

        def place():
            nonlocal attempts
            attempts += 1
            return place_window(window, position, bar_size) and attempts < 12

        GLib.timeout_add(60, place)

    window.connect("map", mapped)
    last_size = None

    def resized(*_):
        nonlocal last_size
        size = tuple(window.get_size())
        if size != last_size:
            last_size = size
            mapped()

    window.connect("size-allocate", resized)
