import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import json
import subprocess
from unittest.mock import patch

from nas_geometry import initial_placement, launch_bar, popup_bounds


class GeometryTests(unittest.TestCase):
    def test_all_bar_edges_fit_scaled_offset_monitor(self):
        for position in ("top", "bottom", "left", "right"):
            with self.subTest(position=position):
                monitor = dict(
                    width=2880,
                    height=1800,
                    scale=1.6,
                    x=-1800,
                    y=120,
                    reserved=[0, 28, 0, 0],
                )
                x, y, w, h = popup_bounds(monitor, (440, 520), position, 32)
                self.assertGreaterEqual(x, -1790)
                self.assertGreaterEqual(y, 158)
                self.assertLessEqual(x + w, -10)
                self.assertLessEqual(y + h, 1235)
                if position == "left":
                    self.assertEqual(x, -1758)
                if position == "bottom":
                    self.assertEqual(y + h, 1203)
                if position == "right":
                    self.assertEqual(x + w, -42)

    def test_oversized_form_is_limited_to_usable_area(self):
        monitor = dict(width=640, height=480, x=0, y=0, reserved=[0, 0, 0, 0])
        for edge in ("top", "bottom", "left", "right"):
            x, y, w, h = popup_bounds(monitor, (900, 900), edge)
            self.assertGreaterEqual(x, 10)
            self.assertGreaterEqual(y, 10)
            self.assertLessEqual(x + w, 630)
            self.assertLessEqual(y + h, 470)

    def test_rotated_monitor_uses_logical_dimensions(self):
        monitor = dict(width=1920, height=1080, scale=1, transform=1, x=0, y=0)
        self.assertEqual(popup_bounds(monitor, (440, 520)), (630, 38, 440, 520))


class LaunchBarTests(unittest.TestCase):
    def test_legacy_launch_uses_current_left_bar(self):
        with patch(
            "nas_geometry.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, '{"bar":{"position":"left"}}'
            ),
        ):
            self.assertEqual(launch_bar(["nas_app.py"]), ("left", 28))

    def test_explicit_widget_geometry_is_preserved(self):
        with patch("nas_geometry.subprocess.run") as run:
            self.assertEqual(
                launch_bar(
                    ["nas_app.py", "--bar-position", "right", "--bar-size", "32"]
                ),
                ("right", 32),
            )
            run.assert_not_called()

    def test_reserved_left_edge_does_not_become_top_edge(self):
        monitor = dict(width=1800, height=1125, x=0, y=0, reserved=[28, 0, 0, 0])
        self.assertEqual(popup_bounds(monitor, (440, 360), "left"), (38, 755, 440, 360))

    def test_shell_unavailable_has_safe_default(self):
        with patch("nas_geometry.subprocess.run", side_effect=OSError):
            self.assertEqual(launch_bar(["nas_app.py"]), ("top", 28))


class InitialPlacementTests(unittest.TestCase):
    def test_rule_carries_style_without_user_hyprland_config(self):
        monitor = dict(
            id=0,
            focused=True,
            width=1920,
            height=1080,
            x=0,
            y=0,
            activeWorkspace={"id": 1},
        )

        def ipc(*args):
            return json.dumps([monitor]) if args[0] == "monitors" else ""

        with patch("nas_geometry.ipc", side_effect=ipc) as fake:
            initial_placement("top", 28)
        rule = fake.call_args_list[-1].args[1]
        self.assertIn('name="netmount-initial-placement"', rule)
        self.assertIn("float=true", rule)
        self.assertIn("rounding=0", rule)
        self.assertIn("border_size=1", rule)
        self.assertIn('animation="popin 95%"', rule)


class FakeWindow:
    def __init__(self, visible=True, title="Netmount", size=(440, 360)):
        self.visible, self.title, self.size = visible, title, size
        self.handlers, self.decorated = {}, True

    def get_visible(self):
        return self.visible

    def get_title(self):
        return self.title

    def get_size(self):
        return self.size

    def set_decorated(self, value):
        self.decorated = value

    def connect(self, signal, handler):
        self.handlers[signal] = handler


class PlaceWindowTests(unittest.TestCase):
    monitor = dict(id=0, width=1920, height=1080, x=0, y=0, reserved=[0, 28, 0, 0])

    def fake_ipc(self, client):
        calls = []

        def ipc(*args):
            calls.append(args)
            if args[0] == "clients":
                return json.dumps([client] if client else [])
            if args[0] == "monitors":
                return json.dumps([self.monitor])
            return ""

        return ipc, calls

    def client(self, **changes):
        from nas_geometry import os as geometry_os

        base = dict(
            pid=geometry_os.getpid(),
            title="Netmount",
            address="0xabc",
            monitor=0,
            size=[600, 5000],  # taller than the screen: must shrink
            at=[0, 0],
        )
        return dict(base, **changes)

    def test_moves_and_resizes_only_this_process_window_by_address(self):
        from nas_geometry import place_window

        ipc, calls = self.fake_ipc(self.client())
        with patch("nas_geometry.ipc", side_effect=ipc):
            self.assertFalse(place_window(FakeWindow(), "top", 28))
        dispatched = [args[1] for args in calls if args[0] == "dispatch"]
        self.assertEqual(len(dispatched), 2)
        self.assertTrue(all('address:0xabc"' in d for d in dispatched))
        self.assertIn("window.resize", dispatched[0])
        self.assertIn("window.move", dispatched[1])

    def test_already_placed_window_is_left_alone(self):
        from nas_geometry import place_window, popup_bounds

        x, y, w, h = popup_bounds(self.monitor, (440, 360), "top", 28)
        ipc, calls = self.fake_ipc(self.client(size=[w, h], at=[x, y]))
        with patch("nas_geometry.ipc", side_effect=ipc):
            place_window(FakeWindow(), "top", 28)
        self.assertFalse([args for args in calls if args[0] == "dispatch"])

    def test_unmapped_window_retries_and_hidden_window_stops(self):
        from nas_geometry import place_window

        ipc, _ = self.fake_ipc(None)
        with patch("nas_geometry.ipc", side_effect=ipc):
            self.assertTrue(place_window(FakeWindow(), "top", 28))
            self.assertFalse(place_window(FakeWindow(visible=False), "top", 28))

    def test_unexpected_address_or_ipc_failure_never_dispatches(self):
        from nas_geometry import place_window

        ipc, calls = self.fake_ipc(self.client(address='0x1"}); evil'))
        with patch("nas_geometry.ipc", side_effect=ipc):
            self.assertFalse(place_window(FakeWindow(), "top", 28))
        self.assertFalse([args for args in calls if args[0] == "dispatch"])
        with patch("nas_geometry.ipc", side_effect=OSError):
            self.assertFalse(place_window(FakeWindow(), "top", 28))

    def test_ipc_returns_hyprctl_output(self):
        from nas_geometry import ipc

        done = subprocess.CompletedProcess([], 0, "[]", "")
        with patch("nas_geometry.subprocess.run", return_value=done) as run:
            self.assertEqual(ipc("clients", "-j"), "[]")
        self.assertEqual(run.call_args.args[0], ["hyprctl", "clients", "-j"])

    def test_initial_placement_ignores_compositor_errors(self):
        with patch("nas_geometry.ipc", side_effect=OSError):
            initial_placement("top", 28)  # must not raise


class PrepareWindowTests(unittest.TestCase):
    def test_map_and_resize_schedule_bounded_placement_retries(self):
        from nas_geometry import prepare_window

        scheduled = []
        glib = type(
            "GLib",
            (),
            {"timeout_add": staticmethod(lambda _ms, fn: scheduled.append(fn))},
        )
        window = FakeWindow()
        with patch("nas_geometry.initial_placement") as initial:
            prepare_window(window, glib, "left", 32)
        initial.assert_called_once_with("left", 32)
        self.assertFalse(window.decorated)
        window.handlers["map"]()
        with patch("nas_geometry.place_window", return_value=True) as place:
            retries = 0
            while scheduled[-1]():
                retries += 1
        self.assertEqual(place.call_count, 12)  # gives up after 12 attempts
        window.handlers["size-allocate"]()
        window.handlers["size-allocate"]()  # same size: no extra placement
        self.assertEqual(len(scheduled), 2)


class LaunchBarEdgeTests(unittest.TestCase):
    def test_malformed_arguments_fall_back_to_safe_values(self):
        with patch("nas_geometry.subprocess.run") as run:
            self.assertEqual(launch_bar(["x", "--bar-position"]), ("top", 28))
            self.assertEqual(
                launch_bar(["x", "--bar-position", "diagonal"]), ("top", 28)
            )
            self.assertEqual(
                launch_bar(["x", "--bar-position", "left", "--bar-size", "big"]),
                ("left", 28),
            )
            self.assertEqual(
                launch_bar(["x", "--bar-position", "left", "--bar-size", "999"]),
                ("left", 200),
            )
            run.assert_not_called()
