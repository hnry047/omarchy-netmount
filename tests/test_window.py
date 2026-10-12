"""ManagerWindow built offscreen with fakes.

Safe: the window is never shown, so Hyprland is not involved; profiles live in
a temporary folder, the keyring is fake, and mount/unmount only edit a fake
mount table. Background jobs run immediately instead of on a thread.
"""

import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_core import OperationError  # noqa: E402
from test_app import FakeKeyring  # noqa: E402
from test_gtk_ui import AVAILABLE, Gtk  # noqa: E402

LOGIN = {"username": "<USERNAME>", "password": "<PASSWORD>", "domain": ""}


def walk(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from walk(child)


def labels(widget):
    return [w.get_text() for w in walk(widget) if isinstance(w, Gtk.Label)]


class WindowFixture(unittest.TestCase):
    """Shared setup only; the test classes below add the tests."""

    def setUp(self):
        import nas_manager
        import nas_window

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mounts, self.calls = [], []
        self.mount_error = None
        self.keyring = FakeKeyring()
        path = Path(self.tmp.name) / "profiles.json"
        self.managers = []

        def factory():
            manager = nas_manager.Manager(
                path, self.keyring, mounts_fn=lambda: self.mounts
            )
            self.managers.append(manager)
            return manager

        self.window = nas_window.ManagerWindow(
            manager_factory=factory,
            prepare_window=lambda *_: None,
            initial_placement=lambda *_: self.calls.append("initial"),
            refresh_style=lambda: self.calls.append("style"),
            mount=self.fake_mount,
            unmount=self.fake_unmount,
            read_mounts=lambda: self.mounts,
            run_in_background=lambda job: job(),
            defer=lambda fn, *args: fn(*args),
        )
        self.addCleanup(self.window.destroy)
        # Registered last, so it runs first: nothing may reach the desktop.
        self.addCleanup(self.assert_nothing_mapped)

    def assert_nothing_mapped(self):
        mapped = [w.get_title() for w in Gtk.Window.list_toplevels() if w.get_mapped()]
        self.assertEqual(mapped, [], "a window was shown on the desktop")

    def fake_mount(self, profile, login):
        self.calls.append(("mount", profile["id"], login["username"]))
        if self.mount_error:
            raise self.mount_error
        self.mounts.append(
            {
                "target": profile["local"],
                "source": profile["source"],
                "fstype": "cifs",
                "root": "/",
            }
        )

    def fake_unmount(self, profile):
        self.calls.append(("unmount", profile["id"]))
        self.mounts[:] = [m for m in self.mounts if m["target"] != profile["local"]]

    def add(self, ident="docs", local="/mnt/nas-docs", remember_login=True):
        profile = {
            "id": ident,
            "label": ident.title(),
            "server": "fileserver",
            "remote": ident,
            "local": local,
        }
        self.window.manager.save(profile, LOGIN, True, remember_login)
        self.window.refresh()
        return profile

    def status(self):
        return self.window.status.widget.get_text()

    def status_classes(self):
        style = self.window.status.widget.get_style_context()
        return {c for c in ("error", "warning", "notice") if style.has_class(c)}


@unittest.skipUnless(AVAILABLE, "GTK display required")
class ManagerWindowTests(WindowFixture):
    # List and header ------------------------------------------------------

    def test_window_and_header_carry_the_plugin_name(self):
        self.assertEqual(self.window.get_title(), "Netmount")
        self.assertIn("Netmount", labels(self.window))

    def test_empty_list_offers_to_add_the_first_connection(self):
        self.assertEqual(self.window.summary.get_text(), "0 CONNECTIONS · 0 MOUNTED")
        self.assertIn("Your files, within reach", labels(self.window.cards))
        self.assertEqual(self.status(), "ADD A SHARE TO GET STARTED")

    def test_connections_render_in_order_with_counts(self):
        self.add("docs", "/mnt/nas-docs")
        self.add("photos", "/mnt/nas-photos")
        self.assertEqual(self.window.summary.get_text(), "2 CONNECTIONS · 0 MOUNTED")
        texts = labels(self.window.cards)
        self.assertLess(texts.index("Docs"), texts.index("Photos"))

    def test_unchanged_refresh_keeps_the_same_rows(self):
        self.add()
        rows = self.window.cards.get_children()
        self.window.refresh()
        self.assertEqual(self.window.cards.get_children(), rows)

    # Operations -------------------------------------------------------------

    def test_mount_with_a_remembered_login_mounts_and_reports(self):
        self.add()
        self.window.card_clicked("docs", self.window.do_mount)
        self.assertIn(("mount", "docs", "<USERNAME>"), self.calls)
        self.assertEqual(self.status(), "Mounted.")
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.summary.get_text(), "1 CONNECTION · 1 MOUNTED")

    def test_mount_failure_is_shown_as_an_error(self):
        self.add()
        self.mount_error = OperationError("The NAS is unreachable.", "server")
        self.window.card_clicked("docs", self.window.do_mount)
        self.assertEqual(self.status(), "The NAS is unreachable.")
        self.assertIn("error", self.status_classes())
        self.assertEqual(self.window.error_field, "server")

    def test_unexpected_failure_uses_a_fixed_message(self):
        self.window.work(lambda: 1 / 0)
        self.assertEqual(
            self.status(),
            "The operation could not complete. Check the connection and try again.",
        )

    def test_warning_result_is_highlighted(self):
        self.window.work(lambda: Warning("The keyring could not save the login."))
        self.assertIn("warning", self.status_classes())

    def test_unmount_reports(self):
        self.add()
        self.window.card_clicked("docs", self.window.do_mount)
        self.window.card_clicked("docs", self.window.do_unmount)
        self.assertIn(("unmount", "docs"), self.calls)
        self.assertEqual(self.status(), "Unmounted.")

    def test_busy_window_ignores_clicks_and_reorders(self):
        self.add("docs", "/mnt/nas-docs")
        self.add("photos", "/mnt/nas-photos")
        self.window.busy = True
        self.window.card_clicked("docs", self.window.do_mount)
        self.window.reorder("photos", 0)
        self.assertNotIn("mount", [c[0] for c in self.calls if isinstance(c, tuple)])
        self.assertEqual(
            [p["id"] for p in self.window.manager.profiles], ["docs", "photos"]
        )

    def test_reorder_moves_and_reports_missing_connections(self):
        self.add("docs", "/mnt/nas-docs")
        self.add("photos", "/mnt/nas-photos")
        self.window.reorder("photos", 0)
        self.assertEqual(
            [p["id"] for p in self.window.manager.profiles], ["photos", "docs"]
        )
        self.window.reorder("missing", 0)
        self.assertIn("error", self.status_classes())

    def test_forget_after_confirmation(self):
        self.add()
        with patch.object(Gtk.Dialog, "run", return_value=Gtk.ResponseType.OK):
            self.window.card_clicked("docs", self.window.forget)
        self.assertEqual(self.window.manager.profiles, [])
        self.assertEqual(self.status(), "Connection forgotten.")

    def test_forget_cancelled_keeps_the_connection(self):
        self.add()
        with patch.object(Gtk.Dialog, "run", return_value=Gtk.ResponseType.CANCEL):
            self.window.card_clicked("docs", self.window.forget)
        self.assertEqual(len(self.window.manager.profiles), 1)

    def test_open_folder_only_for_a_live_mount(self):
        self.add()
        launched = []
        gio = types.SimpleNamespace(
            AppInfo=types.SimpleNamespace(
                launch_default_for_uri=lambda uri, _ctx: launched.append(uri)
            )
        )
        with patch("nas_window.Gio", gio):
            self.window.open_folder("docs")
            self.assertEqual(launched, [])
            self.window.card_clicked("docs", self.window.do_mount)
            with patch.object(self.window, "close") as close:
                self.window.open_folder("docs")
        self.assertEqual(launched, ["file:///mnt/nas-docs"])
        close.assert_called_once()

    # Closing ----------------------------------------------------------------

    def test_close_while_busy_is_refused_with_a_notice(self):
        self.window.busy = True
        self.assertTrue(self.window.on_delete())
        self.assertIn("Wait for the current operation", self.status())

    def test_resident_close_hides_and_starts_a_fresh_session(self):
        self.window.resident = True
        self.add(remember_login=False)
        self.assertTrue(self.window.on_delete())
        self.assertEqual(len(self.managers), 2)  # session-only logins dropped

    def test_toggle_reopens_with_the_new_bar_edge(self):
        with (
            patch.object(self.window, "show_all"),
            patch.object(self.window, "present"),
        ):
            self.window.toggle("left", 32)
        self.assertEqual((self.window.position, self.window.bar_size), ("left", 32))
        self.assertIn("initial", self.calls)
        self.assertIn("style", self.calls)

    def test_hidden_window_skips_polling(self):
        self.calls.clear()
        self.assertTrue(self.window.poll())
        self.assertNotIn("style", self.calls)


@unittest.skipUnless(AVAILABLE, "GTK display required")
class EditorTests(WindowFixture):
    """The Add/Edit form, with Gtk.Dialog.run replaced by scripted answers."""

    def answer(self, *responses, values=None):
        """Fill the form's entries, then return each response in turn."""
        seen = []

        def run(dialog):
            entries = [w for w in walk(dialog) if isinstance(w, Gtk.Entry)]
            if values is not None and len(entries) == 7:
                for entry, value in zip(entries, values, strict=True):
                    entry.set_text(value)
            visible = [
                w.get_text()
                for w in walk(dialog)
                if isinstance(w, Gtk.Label)
                and w.get_style_context().has_class("error")
                and w.get_text()
            ]
            seen.append((dialog.get_title(), visible))
            return responses[min(len(seen), len(responses)) - 1]

        # The form calls show_all(); show only its contents so no dialog
        # window is ever mapped on the desktop.
        def show_contents(dialog):
            dialog.get_content_area().show_all()

        stack = ExitStack()
        stack.enter_context(patch.object(Gtk.Dialog, "run", run))
        stack.enter_context(patch.object(Gtk.Dialog, "show_all", show_contents))
        return stack, seen

    FORM = ("Docs", "fileserver", "docs", "/mnt/nas-docs") + (
        "<USERNAME>",
        "<PASSWORD>",
        "",
    )

    def test_add_saves_and_mounts_in_one_step(self):
        runner, seen = self.answer(Gtk.ResponseType.OK, values=self.FORM)
        with runner:
            self.window.new()
        self.assertEqual(seen[0][0], "Add connection")
        self.assertEqual(len(self.window.manager.profiles), 1)
        self.assertIn("mount", [c[0] for c in self.calls if isinstance(c, tuple)])
        self.assertEqual(self.status(), "Mounted.")

    def test_invalid_input_stays_in_the_form_under_its_field(self):
        bad = ("Docs", "bad host!") + self.FORM[2:]
        runner, seen = self.answer(
            Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, values=bad
        )
        with runner:
            self.window.new()
        self.assertEqual(len(seen), 2)  # reopened run loop, same dialog
        self.assertTrue(any("IP address or hostname" in t for t in seen[1][1]))
        self.assertEqual(self.window.manager.profiles, [])

    def test_failed_mount_reopens_the_form_with_the_error(self):
        self.mount_error = OperationError("NAS login failed.", "password")
        runner, seen = self.answer(
            Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, values=self.FORM
        )
        with runner:
            self.window.new()
        self.assertEqual(seen[1][0], "Add connection")
        self.assertIn("NAS login failed.", seen[1][1])

    def test_edit_only_saves(self):
        self.add()
        renamed = ("Renamed",) + self.FORM[1:]
        runner, seen = self.answer(Gtk.ResponseType.OK, values=renamed)
        with runner:
            self.window.card_clicked("docs", self.window.edit)
        self.assertEqual(seen[0][0], "Edit connection")
        self.assertEqual(self.window.manager.find("docs")["label"], "Renamed")
        self.assertEqual(self.status(), "Changes saved.")
        self.assertNotIn("mount", [c[0] for c in self.calls if isinstance(c, tuple)])

    def test_mount_without_a_saved_login_asks_for_it(self):
        self.add(remember_login=False)
        self.window.manager.session_logins.clear()
        runner, seen = self.answer(Gtk.ResponseType.CANCEL)
        with runner:
            self.window.card_clicked("docs", self.window.do_mount)
        self.assertEqual(seen[0][0], "Connect to NAS")


@unittest.skipUnless(AVAILABLE, "GTK display required")
class ConnectionFormTests(WindowFixture):
    """The dialog itself, built directly and never mapped."""

    def form(self, **options):
        from nas_dialog import ConnectionForm
        from nas_ui import new_connection

        settings = dict(adding=True, login_only=False, remembered=True)
        settings.update(options)
        profile = dict(new_connection("new"), label="Docs", source="//fs/docs")
        with patch.object(
            Gtk.Dialog, "show_all", lambda d: d.get_content_area().show_all()
        ):
            form = ConnectionForm(
                self.window,
                profile,
                None,
                place=lambda *_: None,
                focus_changed=lambda *_: None,
                **settings,
            )
        self.addCleanup(form.dialog.destroy)
        return form

    def test_folder_picker_fills_the_mount_folder(self):
        form = self.form()
        with (
            patch.object(Gtk.FileChooserDialog, "show_all"),
            patch.object(
                Gtk.FileChooserDialog, "run", return_value=Gtk.ResponseType.OK
            ),
            patch.object(
                Gtk.FileChooserDialog, "get_filename", return_value="/mnt/picked"
            ),
        ):
            form.choose_folder()
        self.assertEqual(form.entries["local"].get_text(), "/mnt/picked")

    def test_login_can_only_be_remembered_with_the_connection(self):
        form = self.form()
        form.remember_login.set_active(True)
        form.remember.set_active(False)
        self.assertFalse(form.remember_login.get_active())
        self.assertFalse(form.remember_login.get_sensitive())

    def test_errors_without_a_field_show_at_the_bottom(self):
        form = self.form()
        form.show_error("Something went wrong.", None)
        self.assertEqual(form.error_label.get_text(), "Something went wrong.")

    def test_login_only_form_locks_the_saved_paths(self):
        form = self.form(login_only=True, adding=False)
        self.assertFalse(form.entries["server"].get_sensitive())
        self.assertFalse(form.remember.get_sensitive())
        self.assertEqual(form.heading.get_text(), "Docs · //fs/docs")

    def test_close_clears_the_typed_login(self):
        form = self.form()
        form.entries["password"].set_text("<PASSWORD>")
        entry = form.entries["password"]
        form.close()
        self.assertEqual(entry.get_text(), "")


if __name__ == "__main__":
    unittest.main()
