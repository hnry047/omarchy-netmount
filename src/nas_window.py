"""The NAS manager window: connection list, status line and operations.

GTK only; profiles, mounts and the keyring are reached through injected
callables, so nothing here touches them directly.
"""

import threading
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
# require_version must run first, so these imports cannot move to the top.
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # type: ignore  # noqa: E402

from nas_core import (  # noqa: E402
    OperationError,
    mount,
    mount_state,
    read_mounts,
    unmount,
)
from nas_dialog import ConnectionForm  # noqa: E402
from nas_geometry import initial_placement, prepare_window  # noqa: E402
from nas_ui import (  # noqa: E402
    StatusLine,
    connection_card,
    empty_state,
    label,
    new_connection,
    status_messages,
)


class ManagerWindow(Gtk.Window):
    """The NAS manager popup.

    Everything outside the window is passed in, so tests can build it offscreen
    with fakes (it is never shown there, so Hyprland is not involved).
    """

    def __init__(
        self,
        manager_factory,
        resident=False,
        position="top",
        bar_size=28,
        prepare_window=prepare_window,
        initial_placement=initial_placement,
        refresh_style=lambda: None,
        mount=mount,
        unmount=unmount,
        read_mounts=read_mounts,
        run_in_background=lambda job: threading.Thread(target=job, daemon=True).start(),
        defer=GLib.idle_add,
    ):
        super().__init__(title="Netmount")
        self.manager_factory, self.resident = manager_factory, resident
        self.position, self.bar_size = position, bar_size
        self.prepare_window, self.initial_placement = prepare_window, initial_placement
        self.refresh_style = refresh_style
        self.mount, self.unmount, self.read_mounts = mount, unmount, read_mounts
        self.run_in_background, self.defer = run_in_background, defer
        self.set_decorated(False)
        self.set_default_size(440, 360)
        self.place(self)
        self.set_border_width(12)
        self.get_style_context().add_class("nas-manager")
        self.busy = False
        self.error_field = None
        self.ever_active = False
        self.selected_id = None
        self.card_controls = []
        self.rendered = None
        self.manager = self.manager_factory()
        self.connect("delete-event", self.on_delete)
        self.connect("notify::is-active", self.focus_changed)
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", lambda *_: Gtk.main_level() and Gtk.main_quit())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(box)
        header = Gtk.Box(spacing=8)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        heading.pack_start(label(Gtk, "Netmount", "nas-title"), False, False, 0)
        status_row = Gtk.Box(spacing=6)
        self.spinner = Gtk.Spinner()
        self.spinner.set_no_show_all(True)
        status_row.pack_start(self.spinner, False, False, 0)
        status = label(Gtk, "", "nas-status")
        # At most two lines, so long messages never resize the header; the
        # full text stays available as a tooltip.
        status.set_line_wrap(True)
        status.set_max_width_chars(36)
        status.set_lines(2)
        status.set_ellipsize(Pango.EllipsizeMode.END)
        status.connect(
            "notify::label",
            lambda widget, _: widget.set_tooltip_text(widget.get_text()),
        )
        status_row.pack_start(status, True, True, 0)
        heading.pack_start(status_row, False, False, 0)
        # Rotating status, replaced by progress and (red) errors.
        self.status = StatusLine(status, GLib.timeout_add)
        header.pack_start(heading, True, True, 0)
        add = Gtk.Button(label="＋  Add connection")
        add.set_valign(Gtk.Align.CENTER)
        add.get_style_context().add_class("suggested-action")
        add.get_style_context().add_class("nas-primary")
        add.connect("clicked", self.new)
        header.pack_end(add, False, False, 0)
        box.pack_start(header, False, False, 0)
        box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )
        subheader = Gtk.Box(spacing=8)
        self.summary = label(Gtk, "Your connections", "nas-section")
        subheader.pack_start(self.summary, True, True, 0)
        refresh = Gtk.Button.new_from_icon_name(
            "view-refresh-symbolic", Gtk.IconSize.BUTTON
        )
        refresh.set_tooltip_text("Refresh mount status")
        refresh.get_style_context().add_class("nas-quiet")
        refresh.connect("clicked", self.refresh)
        subheader.pack_end(refresh, False, False, 0)
        box.pack_start(subheader, False, False, 0)
        self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.cards)
        box.pack_start(scroll, True, True, 0)
        self.buttons = {"New": add, "Refresh": refresh}
        self.refresh()
        GLib.timeout_add_seconds(5, self.poll)
        GLib.timeout_add(2800, self.tick_status)

    def place(self, widget):
        # Reads the current edge, which toggle() updates on each opening.
        self.prepare_window(widget, GLib, self.position, self.bar_size)

    def on_delete(self, *_):
        if self.busy:
            # A timed notice; the operation's progress text returns after it.
            self.status.show("Wait for the current operation to finish before closing.")
            return True
        if self.resident:
            for child in Gtk.Window.list_toplevels():
                if isinstance(child, Gtk.Dialog) and child.get_visible():
                    child.response(Gtk.ResponseType.CANCEL)
            self.hide()
            self.ever_active = False
            # Closing still ends session-only connections and login memory.
            self.manager = self.manager_factory()
            self.rendered = None
            self.selected_id = None
            self.status.reset()
            return True
        return False

    def toggle(self, edge, size):
        if self.get_visible():
            self.close()
            return
        self.position, self.bar_size = edge, size
        self.initial_placement(self.position, self.bar_size)
        self.refresh_style()
        self.refresh()
        self.show_all()
        self.present()

    def focus_changed(self, window, *_):
        if window.is_active():
            self.ever_active = True
        elif self.ever_active:
            # Let focus settle on another NAS dialog before deciding that
            # the click was outside the whole manager.
            GLib.timeout_add(180, self.dismiss_unfocused)

    def on_key(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def dismiss_unfocused(self):
        if self.busy:
            return False
        if any(w.get_visible() and w.is_active() for w in Gtk.Window.list_toplevels()):
            return False
        self.close()
        return False

    def selected(self):
        return next(
            (p for p in self.manager.profiles if p["id"] == self.selected_id), None
        )

    def card_clicked(self, ident, callback):
        if not self.busy:
            self.selected_id = ident
            callback()

    def controls(self):
        for button in self.buttons.values():
            button.set_sensitive(not self.busy)
        for control, enabled in self.card_controls:
            control.set_sensitive(enabled and not self.busy)
        if self.busy:
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

    def refresh(self, *_):
        mounts = self.read_mounts()
        states = [(p, mount_state(p, mounts)) for p in self.manager.profiles]
        signature = tuple(
            (
                p["id"],
                p["label"],
                p["source"],
                p["local"],
                state,
                p["id"] in self.manager.persistent,
            )
            for p, state in states
        )
        self.status.set_lines(status_messages(states))
        count = len(states)
        mounted = sum(state == "mounted" for _, state in states)
        self.summary.set_text(
            f"{count} CONNECTION{'S' if count != 1 else ''} · {mounted} MOUNTED"
        )
        if signature == self.rendered:
            self.controls()
            return
        self.rendered = signature
        for child in self.cards.get_children():
            child.destroy()
        self.card_controls = []
        if not states:
            empty, add_button = empty_state(Gtk, self.new)
            self.cards.pack_start(empty, True, True, 0)
            self.card_controls.append((add_button, True))
        for index, (p, state) in enumerate(states):
            callback = self.do_unmount if state == "mounted" else self.do_mount
            ident = p["id"]
            card, action_button, menu_button = connection_card(
                Gtk,
                p,
                state,
                ident in self.manager.persistent,
                self.busy,
                action=lambda ident=ident, cb=callback: self.card_clicked(ident, cb),
                edit=lambda ident=ident: self.card_clicked(ident, self.edit),
                forget=lambda ident=ident: self.card_clicked(ident, self.forget),
                open_folder=lambda ident=ident: self.open_folder(ident),
                position=(index, len(states)),
                move=lambda delta, ident=ident, index=index: self.reorder(
                    ident, index + delta
                ),
                # A dropped connection takes the place of the card under it.
                dropped=lambda moved, index=index: self.reorder(moved, index),
            )
            self.cards.pack_start(card, False, False, 0)
            self.card_controls.extend(
                ((action_button, state != "occupied"), (menu_button, True))
            )
        self.cards.show_all()
        self.controls()

    def reorder(self, ident, position):
        # Order only: no mount, keyring, or authorization involved.
        if self.busy:
            return
        try:
            self.manager.move(ident, position)
        except (OperationError, ValueError) as exc:
            self.status.show(str(exc), "error")
        self.refresh()

    def tick_status(self):
        if self.get_visible():
            self.status.advance()
        return True

    def poll(self):
        # Hidden resident manager: skip theme and mount reads; toggle()
        # refreshes both when the window is shown again.
        if not self.get_visible():
            return True
        self.refresh_style()
        if not self.busy:
            self.refresh()
        return True

    def work(
        self,
        callback,
        after=None,
        message="Working… respond to any authorization prompt.",
    ):
        self.busy = True
        self.status.begin(message)
        self.controls()

        def worker():
            field = None
            try:
                result = callback()
                error = None
            except (OperationError, ValueError) as exc:
                result, error = None, str(exc)
                field = getattr(exc, "field", None)
            except Exception:
                result, error = (
                    None,
                    "The operation could not complete. Check the connection and try again.",
                )
            self.defer(finished, result, error, field)

        def finished(result, error, field):
            self.busy = False
            self.error_field = field
            self.refresh()
            if error:
                self.status.end(error, "error")
            elif isinstance(result, Warning):
                self.status.end(str(result), "warning")
            else:
                self.status.end(
                    result if isinstance(result, str) and result else "Ready."
                )
            if after:
                after(result, error)
            return False

        self.run_in_background(worker)

    def new(self, *_):
        self.editor(None, None)

    def edit(self, *_):
        p = self.selected()
        if p:
            self.work(
                lambda: self.manager.login(p["id"]),
                after=lambda login, error: self.editor(p, login),
                message="Loading this connection’s login…",
            )

    def editor(self, profile, login, login_only=False, error=None, adding=None):
        adding = profile is None if adding is None else adding
        p = profile or new_connection(str(uuid.uuid4()))
        form = ConnectionForm(
            self,
            p,
            login,
            adding=adding,
            login_only=login_only,
            remembered=profile is None or p["id"] in self.manager.persistent,
            place=self.place,
            focus_changed=self.focus_changed,
        )
        if error:
            form.show_error(*error)
        while form.run():
            values = form.read()
            if values is None:
                continue  # the form shows what to fix
            form.close()
            self.save_from_form(values, adding, login_only)
            return
        form.close()

    def save_from_form(self, values, adding, login_only):
        clean, entered, save_paths, save_login = values

        def save_and_mount():
            warning = self.manager.save(clean, entered, save_paths, save_login)
            if not (adding or login_only):
                return Warning(warning) if warning else "Changes saved."
            self.mount(clean, entered)
            return Warning(warning) if warning else "Mounted."

        def reopen_on_error(_result, error):
            # Keep what was typed and point at the field to fix. The login
            # stays in this process only, as for any session login.
            if error:
                self.editor(
                    clean,
                    entered,
                    login_only,
                    error=(error, self.error_field),
                    adding=adding,
                )

        self.work(
            save_and_mount,
            after=reopen_on_error,
            message="Mounting… respond to any authorization prompt.",
        )

    def do_mount(self, *_):
        p = self.selected()
        if not p:
            return

        def loaded(login, error):
            if login is None:
                self.editor(p, None, login_only=True)
            else:
                self.work(lambda: (self.mount(p, login), "Mounted.")[1])

        self.work(
            lambda: self.manager.login(p["id"]),
            after=loaded,
            message="Loading login…",
        )

    def open_folder(self, ident):
        p = next((x for x in self.manager.profiles if x["id"] == ident), None)
        # Re-check: only open a folder that is this connection's live mount.
        if not p or self.manager.state(p) != "mounted":
            self.refresh()
            return
        try:
            Gio.AppInfo.launch_default_for_uri(Path(str(p["local"])).as_uri(), None)
        except GLib.Error:
            self.status.show("No file manager could open this folder.", "error")
            return
        self.close()

    def do_unmount(self, *_):
        p = self.selected()
        if p:
            self.work(lambda: (self.unmount(p), "Unmounted.")[1])

    def forget(self, *_):
        p = self.selected()
        if not p:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Forget this connection?",
        )
        dialog.format_secondary_text(
            "Its saved paths and remembered login will be removed. Your NAS files remain untouched."
        )
        dialog.connect("notify::is-active", self.focus_changed)
        self.place(dialog)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            self.work(
                lambda: (self.manager.forget(p["id"]), "Connection forgotten.")[1]
            )
