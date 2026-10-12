"""GTK widgets built offscreen with synthetic data.

Safe: no windows are mapped, and nothing touches Hyprland, the keyring, or a
NAS. Skipped when GTK cannot initialize (no display).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_gtk_ui import AVAILABLE, Gtk  # noqa: E402


@unittest.skipUnless(AVAILABLE, "GTK display required")
class WidgetTests(unittest.TestCase):
    def widgets(self, parent):
        yield parent
        if isinstance(parent, Gtk.Container):
            for child in parent.get_children():
                yield from self.widgets(child)

    def test_card_can_be_reordered_by_handle_or_menu(self):
        from nas_ui import connection_card

        moves = []
        profile = {
            "id": "docs",
            "label": "Documents",
            "source": "//fileserver/shared",
            "local": "/mnt/nas-documents",
        }
        card, _action, menu = connection_card(
            Gtk,
            profile,
            "unmounted",
            True,
            False,
            *(lambda: None,) * 3,
            position=(0, 3),
            move=moves.append,
            dropped=lambda ident: None,
        )
        self.addCleanup(card.destroy)
        handles = [
            w
            for w in self.widgets(card)
            if isinstance(w, Gtk.EventBox) and w.get_tooltip_text() == "Drag to reorder"
        ]
        self.assertEqual(len(handles), 1)
        buttons = {
            w.get_label(): w
            for w in self.widgets(menu.get_popover())
            if isinstance(w, Gtk.Button)
        }
        self.assertFalse(buttons["Move up"].get_sensitive())
        self.assertTrue(buttons["Move down"].get_sensitive())
        buttons["Move down"].clicked()
        self.assertEqual(moves, [1])

    def test_card_border_reflects_mount_state(self):
        from nas_ui import connection_card

        profile = {
            "label": "Documents",
            "source": "//fileserver/shared",
            "local": "/mnt/nas-documents",
        }
        for state in ("mounted", "unmounted", "occupied"):
            with self.subTest(state=state):
                card, _action, _menu = connection_card(
                    Gtk, profile, state, True, False, *(lambda: None,) * 3
                )
                self.addCleanup(card.destroy)
                style = card.get_style_context()
                self.assertTrue(style.has_class("nas-card"))
                self.assertTrue(style.has_class(state))
                # The ⋮ button is borderless; only the card border shows state.
                self.assertTrue(_menu.get_style_context().has_class("nas-flat"))

    def test_only_mounted_card_offers_open(self):
        from nas_ui import connection_card

        opened = []
        profile = {
            "label": "Documents",
            "source": "//fileserver/shared",
            "local": "/mnt/nas-documents",
        }

        def open_buttons(state):
            card, _action, _menu = connection_card(
                Gtk,
                profile,
                state,
                True,
                False,
                lambda: None,
                lambda: None,
                lambda: None,
                open_folder=lambda: opened.append(state),
            )
            self.addCleanup(card.destroy)
            return [
                w
                for w in self.widgets(card)
                if isinstance(w, Gtk.Button) and w.get_label() == "Open"
            ]

        self.assertEqual(open_buttons("unmounted"), [])
        self.assertEqual(open_buttons("occupied"), [])
        (button,) = open_buttons("mounted")
        button.clicked()
        self.assertEqual(opened, ["mounted"])

    def test_connection_card_runs_the_selected_action(self):
        from nas_ui import connection_card

        called = []
        profile = {
            "label": "Documents",
            "source": "//fileserver/shared",
            "local": "/mnt/nas-documents",
        }
        card, action, menu = connection_card(
            Gtk,
            profile,
            "unmounted",
            True,
            False,
            lambda: called.append("mount"),
            lambda: None,
            lambda: None,
        )
        self.addCleanup(card.destroy)
        self.assertFalse(
            menu.get_popover().get_visible(), "Dropdown must stay closed until clicked"
        )
        self.assertEqual(action.get_label(), "Mount")
        action.clicked()
        self.assertEqual(called, ["mount"])
        labels = [
            widget.get_text()
            for widget in self.widgets(card)
            if isinstance(widget, Gtk.Label)
        ]
        self.assertIn("○  Disconnected", labels)
        self.assertNotIn("/mnt/nas-documents", labels)
        # The row is an EventBox so it can show hover; its content is one line.
        self.assertIsInstance(card, Gtk.EventBox)
        self.assertEqual(card.get_child().get_orientation(), Gtk.Orientation.HORIZONTAL)
        details = [
            w.get_text()
            for w in self.widgets(menu.get_popover())
            if isinstance(w, Gtk.Label)
        ]
        self.assertIn("/mnt/nas-documents", details)
        self.assertIn("//fileserver/shared", details)
        self.assertTrue(
            any(
                isinstance(w, Gtk.Expander) and w.get_label() == "Details"
                for w in self.widgets(menu.get_popover())
            )
        )

    def test_mounted_row_menu_disconnects_the_selected_share(self):
        from nas_ui import connection_card

        called = []
        profile = dict(
            label="Documents", source="//fileserver/shared", local="/mnt/demo"
        )
        row, action, menu = connection_card(
            Gtk,
            profile,
            "mounted",
            True,
            False,
            lambda: called.append("disconnect"),
            lambda: None,
            lambda: None,
        )
        self.addCleanup(row.destroy)
        self.assertEqual(action.get_label(), "Disconnect")
        action.clicked()
        self.assertEqual(called, ["disconnect"])
        buttons = {
            w.get_label(): w
            for w in self.widgets(menu.get_popover())
            if isinstance(w, Gtk.Button)
        }
        self.assertFalse(buttons["Edit"].get_sensitive())
        self.assertFalse(buttons["Forget"].get_sensitive())

    def test_occupied_card_disables_mount_and_edit(self):
        from nas_ui import connection_card

        profile = {
            "label": "Documents",
            "source": "//fileserver/shared",
            "local": "/mnt/nas-documents",
        }
        card, action, menu = connection_card(
            Gtk,
            profile,
            "occupied",
            True,
            False,
            lambda: self.fail("must not mount"),
            lambda: None,
            lambda: None,
        )
        self.addCleanup(card.destroy)
        self.assertFalse(action.get_sensitive())
        buttons = [
            w for w in self.widgets(menu.get_popover()) if isinstance(w, Gtk.Button)
        ]
        self.assertTrue(all(not button.get_sensitive() for button in buttons))
        details = next(
            w for w in self.widgets(menu.get_popover()) if isinstance(w, Gtk.Expander)
        )
        self.assertTrue(details.get_sensitive())


if __name__ == "__main__":
    unittest.main()
