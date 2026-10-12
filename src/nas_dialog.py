"""The Add / Edit / Login dialog for one connection.

GTK only: it shows a profile and typed login and validates them with
nas_form.parse_form; saving and mounting stay with the manager window.
"""

import gi

gi.require_version("Gtk", "3.0")
# require_version must run first, so these imports cannot move to the top.
from gi.repository import Gtk  # type: ignore  # noqa: E402

from nas_form import (  # noqa: E402  # noqa: E402
    FIELDS,
    HINTS,
    LOGIN_KEYS,
    SECTIONS,
    field_group,
    form_copy,
    parse_form,
)

PATH_KEYS = ("label", "server", "remote", "local")


def _label(text, style=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.get_style_context().add_class(style)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_max_width_chars(38)
    return widget


def _vbox(spacing):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


class ConnectionForm:
    """Builds the dialog; `run()` waits for the user, `read()` validates."""

    def __init__(
        self,
        parent,
        profile,
        login,
        *,
        adding,
        login_only,
        remembered,
        place,
        focus_changed,
    ):
        self.profile, self.login = profile, login or {}
        self.adding, self.login_only = adding, login_only
        self.place, self.focus_changed = place, focus_changed
        self.entries, self.field_errors = {}, {}
        copy = form_copy(adding, login_only)
        self.dialog = self._dialog(parent, copy)
        content = self.dialog.get_content_area()
        content.set_spacing(8)
        self.heading = _label(copy["heading"], "nas-subtitle", wrap=True)
        content.pack_start(self.heading, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content.pack_start(scroller, True, True, 0)
        area = _vbox(8)
        area.set_margin_end(8)
        scroller.add(area)
        self.sections = self._sections(area)
        for key, caption in FIELDS:
            self._field(key, caption)
        security = self._security(area)
        self._preferences(area, remembered)
        self.error_label = _label("", wrap=True)
        for style in ("nas-message", "error"):
            self.error_label.get_style_context().add_class(style)
        content.pack_start(self.error_label, False, False, 0)
        if login_only:
            # Only the login is asked for; the saved paths are shown as context.
            for widget in (self.sections["Connection"], self.sections["Local folder"]):
                widget.set_no_show_all(True)
                widget.hide()
            security.set_no_show_all(True)
            security.hide()
            self.heading.set_text(profile["label"] + " · " + profile["source"])
        self.dialog.show_all()
        self.entries["username" if login_only else "label"].grab_focus()

    # Building ---------------------------------------------------------------

    def _dialog(self, parent, copy):
        dialog = Gtk.Dialog(
            title=copy["title"],
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.connect("notify::is-active", self.focus_changed)
        dialog.set_default_size(440, 340 if self.login_only else 520)
        self.place(dialog)
        dialog.set_border_width(12)
        dialog.get_style_context().add_class("nas-editor")
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL, copy["confirm"], Gtk.ResponseType.OK
        )
        dialog.set_default_response(Gtk.ResponseType.OK)
        confirm = dialog.get_widget_for_response(Gtk.ResponseType.OK)
        confirm.get_style_context().add_class("suggested-action")
        confirm.get_style_context().add_class("nas-primary")
        return dialog

    def _sections(self, area):
        sections = {}
        for name, description in SECTIONS:
            section = _vbox(6)
            section.pack_start(_label(name, "nas-form-heading"), False, False, 0)
            section.pack_start(
                _label(description, "nas-subtitle", wrap=True), False, False, 0
            )
            area.pack_start(section, False, False, 0)
            sections[name] = section
        return sections

    def _error_slot(self, key):
        slot = _label("", wrap=True)
        slot.get_style_context().add_class("nas-message")
        slot.get_style_context().add_class("error")
        slot.set_no_show_all(True)
        self.field_errors[key] = slot
        return slot

    def _entry(self, key):
        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_width_chars(16)
        entry.set_activates_default(True)
        value = self.login.get(key, "") if key in LOGIN_KEYS else self.profile[key]
        entry.set_text(value)
        if key == "password":
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.set_placeholder_text(HINTS[key])
        if self.login_only and key in PATH_KEYS:
            entry.set_sensitive(False)
        self.entries[key] = entry
        return entry

    def _field(self, key, caption_text):
        section = self.sections[field_group(key)]
        field = _vbox(5)
        caption = _label(caption_text)
        field.pack_start(caption, False, False, 0)
        row = Gtk.Box(spacing=8)
        field.pack_start(row, False, False, 0)
        field.pack_start(self._error_slot(key), False, False, 0)
        entry = self._entry(key)
        caption.set_mnemonic_widget(entry)
        row.pack_start(entry, True, True, 0)
        if key == "local" and not self.login_only:
            row.pack_end(self._browse_button(), False, False, 0)
        if key == "domain":
            expander = Gtk.Expander(label="Account domain (optional)")
            expander.set_expanded(bool(entry.get_text()))
            expander.add(field)
            section.pack_start(expander, False, False, 0)
        else:
            section.pack_start(field, False, False, 0)
        if key == "password":
            reveal = Gtk.CheckButton(label="Show password")
            reveal.connect("toggled", lambda b: entry.set_visibility(b.get_active()))
            section.pack_start(reveal, False, False, 0)

    def _browse_button(self):
        browse = Gtk.Button.new_from_icon_name(
            "folder-open-symbolic", Gtk.IconSize.BUTTON
        )
        browse.set_tooltip_text("Choose a local folder")
        browse.connect("clicked", self.choose_folder)
        return browse

    def choose_folder(self, *_):
        picker = Gtk.FileChooserDialog(
            title="Choose local mount folder",
            use_header_bar=False,
            transient_for=self.dialog,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            modal=True,
            destroy_with_parent=True,
        )
        picker.set_default_size(560, 420)
        self.place(picker)
        picker.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL, "Choose", Gtk.ResponseType.OK
        )
        picker.connect("notify::is-active", self.focus_changed)
        picker.set_default_response(Gtk.ResponseType.OK)
        picker.show_all()
        if picker.run() == Gtk.ResponseType.OK:
            folder = picker.get_filename()
            if folder:
                self.entries["local"].set_text(folder)
        picker.destroy()

    def _security(self, area):
        security = _vbox(8)
        security.pack_start(_label("Security", "nas-form-heading"), False, False, 0)
        self.encrypt = Gtk.CheckButton(label="Encrypt traffic (SMB 3)")
        self.encrypt.set_tooltip_text(
            "Protects files on shared or public networks. Turn off only for "
            "an older NAS without SMB 3 encryption."
        )
        self.encrypt.set_active(self.profile.get("encrypt") is not False)
        security.pack_start(self.encrypt, False, False, 0)
        security.pack_start(self._error_slot("encrypt"), False, False, 0)
        self.allow_exec = Gtk.CheckButton(
            label="Allow running programs from this share"
        )
        self.allow_exec.set_tooltip_text(
            "Off by default, so files on the NAS cannot be run as programs."
        )
        self.allow_exec.set_active(self.profile.get("allow_exec") is True)
        security.pack_start(self.allow_exec, False, False, 0)
        area.pack_start(security, False, False, 0)
        return security

    def _preferences(self, area, remembered):
        preferences = _vbox(8)
        preferences.pack_start(
            _label("Remember for next time", "nas-form-heading"), False, False, 0
        )
        area.pack_start(preferences, False, False, 0)
        self.remember = Gtk.CheckButton(label="Remember connection and folders")
        self.remember.set_active(remembered)
        self.remember.set_sensitive(not self.login_only)
        self.remember_login = Gtk.CheckButton(label="Remember login securely")
        self.remember_login.set_tooltip_text(
            "Stored in GNOME Keyring, never in the connection file."
        )
        self.remember_login.set_active(
            self.profile.get("remember_login", False) and self.remember.get_active()
        )
        self.remember_login.set_sensitive(self.remember.get_active())
        self.remember.connect("toggled", self._remember_changed)
        preferences.pack_start(self.remember, False, False, 0)
        preferences.pack_start(self.remember_login, False, False, 0)
        preferences.pack_start(
            _label(
                "Saved logins are kept in GNOME Keyring. Otherwise, your login "
                "lasts only while this window is open.",
                "nas-subtitle",
                wrap=True,
            ),
            False,
            False,
            0,
        )

    def _remember_changed(self, button):
        self.remember_login.set_sensitive(button.get_active())
        if not button.get_active():
            self.remember_login.set_active(False)

    # Using ------------------------------------------------------------------

    def show_error(self, message, field):
        """Show `message` under `field`, or at the bottom when it has none."""
        for slot in self.field_errors.values():
            slot.hide()
        self.error_label.set_text("")
        if field in self.field_errors:
            self.field_errors[field].set_text(message)
            self.field_errors[field].show()
            if field in self.entries:
                self.entries[field].grab_focus()
        else:
            self.error_label.set_text(message)

    def run(self):
        """True when the user confirmed; False when they cancelled or closed."""
        return self.dialog.run() == Gtk.ResponseType.OK

    def read(self):
        """Validated (profile, login, remember, remember_login), or None.

        On invalid input the error is shown in the form and None is returned,
        so the caller keeps the dialog open.
        """
        values = {key: entry.get_text() for key, entry in self.entries.items()}
        try:
            clean, entered = parse_form(
                values,
                self.profile["id"],
                self.encrypt.get_active(),
                self.allow_exec.get_active(),
            )
        except ValueError as exc:
            self.show_error(str(exc), getattr(exc, "field", None))
            return None
        return (
            clean,
            entered,
            self.remember.get_active(),
            self.remember_login.get_active(),
        )

    def close(self):
        """Clear typed login fields, then destroy the dialog."""
        for key in LOGIN_KEYS:
            self.entries[key].set_text("")
        self.dialog.destroy()
