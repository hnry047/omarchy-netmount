"""Theme-aware GTK presentation helpers; no stored profile or login access."""


def new_connection(ident):
    return {"id": ident, "label": "", "server": "", "remote": "", "local": ""}


def status_messages(states):
    """Rotating header lines, like Omarchy's Tailscale panel, but each one useful.

    `states` is a list of (profile, mount state). Only counts and flags are
    used, never names, servers, or paths.
    """
    if not states:
        return ["Add a share to get started"]
    mounted = [p for p, state in states if state == "mounted"]
    messages = []
    if mounted:
        count = len(mounted)
        messages.append(f"{count} share{'s' if count != 1 else ''} ready to open")
        if all(p.get("encrypt") is not False for p in mounted):
            messages.append("Traffic encrypted with SMB 3")
        else:
            messages.append("A mounted share is not encrypted")
    if any(state == "unmounted" for _, state in states):
        messages.append("Mount a share from its ⋮ menu")
    if any(state == "occupied" for _, state in states):
        messages.append("A mount folder is in use")
    if any(p.get("remember_login") for p, _ in states):
        messages.append("Logins kept in GNOME Keyring")
    messages.append("Press Esc to close")
    return messages


class StatusLine:
    """The header line: rotating status, replaced by progress and notices.

    Takes the label and a `timeout_add(ms, callback)` so it runs without GTK in
    tests. `begin`/`end` bracket an operation; `show` is a timed notice that
    falls back to the operation's progress text, or to the rotation.
    """

    HOLD_MS = {"info": 4000, "warning": 10000, "error": 10000}
    KINDS = ("notice", "warning", "error")

    def __init__(self, widget, timeout_add):
        self.widget, self.timeout_add = widget, timeout_add
        self.lines, self.index = [], 0
        self.progress, self.notice, self.token, self.fading = None, None, 0, False

    def _style(self, *classes):
        style = self.widget.get_style_context()
        for name in self.KINDS:
            (style.add_class if name in classes else style.remove_class)(name)

    def _show_line(self):
        self.widget.set_opacity(1)
        if self.progress is not None:
            self._style("notice")
            self.widget.set_text(self.progress)
            return
        self._style()
        self.widget.set_text(self.lines[self.index].upper() if self.lines else "")

    def set_lines(self, lines):
        if lines == self.lines:
            return
        self.lines = lines
        self.index %= max(1, len(lines))
        if self.notice is None and not self.fading:
            self._show_line()

    def begin(self, text):
        """Show progress until `end`; notices in between return to it."""
        self.progress = text
        self.show(text, "progress")

    def end(self, text, kind="info"):
        self.progress = None
        self.show(text, kind)

    def show(self, text, kind="info"):
        self.token += 1
        self.notice = kind
        self.widget.set_opacity(1)
        # Sentences get a readable style; errors and warnings are highlighted.
        self._style("notice", *(kind,) if kind in ("warning", "error") else ())
        self.widget.set_text(text)
        if kind in self.HOLD_MS:
            token = self.token
            self.timeout_add(self.HOLD_MS[kind], lambda: self._expire(token))

    def _expire(self, token):
        if token == self.token:
            self.notice = "progress" if self.progress is not None else None
            self._show_line()
        return False

    def reset(self):
        """Forget progress and notices, e.g. when the manager window hides."""
        self.token += 1
        self.progress, self.notice = None, None
        self._show_line()

    def advance(self):
        """Fade to the next line, with Omarchy's PanelHero timing (180/260ms)."""
        if self.notice is not None or self.fading or len(self.lines) < 2:
            return True
        self.fading = True
        fade_out, fade_in = 6, 9  # 30ms frames: 180ms out, 270ms in
        frame = 0

        def step():
            nonlocal frame
            if self.notice is not None:
                self.fading = False
                return False
            frame += 1
            if frame <= fade_out:
                self.widget.set_opacity(1 - frame / fade_out)
                if frame == fade_out:
                    self.index = (self.index + 1) % len(self.lines)
                    self._show_line()
                    self.widget.set_opacity(0)
                return True
            progress = (frame - fade_out) / fade_in
            self.widget.set_opacity(progress)
            if progress >= 1:
                self.fading = False
                # Lines may have changed mid-fade; end on the current ones.
                self._show_line()
                return False
            return True

        self.timeout_add(30, step)
        return True


def card_action(state, busy=False):
    label = {"mounted": "Unmount", "unmounted": "Mount", "occupied": "Folder occupied"}[
        state
    ]
    return label, not busy and state != "occupied"


CSS = b"""
@define-color nas_bg @theme_bg_color;
@define-color nas_fg @theme_fg_color;
@define-color nas_accent @theme_selected_bg_color;
@define-color nas_muted @insensitive_fg_color;
@define-color nas_success #7fb590;
@define-color nas_warning #e1b66c;
@define-color nas_error #db7c75;
.nas-manager, .nas-editor { border-radius: 0; background-color: @nas_bg; color: @nas_fg; font-family: monospace; }
.nas-manager label, .nas-editor label { color: @nas_fg; }
.nas-manager button, .nas-editor button {
  background-image: none; background-color: alpha(@nas_fg, 0.04); color: @nas_fg;
  border: 1px solid alpha(@nas_fg, 0.40); border-radius: 0; box-shadow: none; text-shadow: none; }
.nas-manager button:hover, .nas-editor button:hover { background-color: alpha(@nas_fg, 0.10); }
.nas-manager button.suggested-action, .nas-editor button.suggested-action {
  background-color: alpha(@nas_accent, 0.20); border-color: @nas_accent; color: @nas_fg; }
.nas-manager button:disabled, .nas-editor button:disabled { opacity: 0.4; }
.nas-manager button.nas-flat {
  border-color: transparent; background-color: transparent; }
.nas-manager button.nas-flat:hover { background-color: alpha(@nas_fg, 0.10); }
.nas-editor entry { background-color: alpha(@nas_fg, 0.04); color: @nas_fg;
  border: 1px solid alpha(@nas_fg, 0.25); box-shadow: none; }
.nas-editor entry:focus { border-color: @nas_accent; }
.nas-editor checkbutton { color: @nas_fg; }
.nas-editor check:checked { background-color: @nas_accent; color: @nas_bg; }
.nas-title { font-weight: 700; }
.nas-subtitle { opacity: 0.65; }
/* Matches Omarchy PanelHero meta: bold caption, letter-spaced, dimmed. */
.nas-status { font-weight: 700; letter-spacing: 1.2px; color: shade(@nas_fg, 0.714); }
.nas-status.notice { letter-spacing: 0; font-weight: 400; color: @nas_fg; }
.nas-status.warning { color: @nas_warning; }
.nas-status.error { color: @nas_error; }
/* Matches Omarchy PanelSectionHeader: bold caption, foreground darkened 1.4x. */
.nas-section { font-weight: 700; color: shade(@nas_fg, 0.714); }
/* Only state draws a border: mounted looks like Hyprland's focused window
   (2px accent), disconnected stays plain. The transparent 2px keeps sizes equal. */
.nas-card { background-color: transparent;
  border: 2px solid transparent; border-radius: 0; }
.nas-card:hover { background-color: alpha(@nas_fg, 0.06); }
.nas-card.mounted { border-color: @nas_accent; }
.nas-card.occupied { border-color: @nas_warning; }
.nas-card-title { font-weight: 600; }
.nas-handle { opacity: 0.45; padding: 0 2px; }
.nas-path { opacity: 0.65; }
.nas-badge { border-radius: 0; padding: 5px 10px;
  background-color: alpha(@nas_fg, 0.06); }
.nas-badge.mounted { background-color: alpha(@nas_success, 0.18); }
.nas-badge.occupied { background-color: alpha(@nas_warning, 0.18); }
.nas-primary { border-radius: 0; padding: 5px 8px; font-weight: 600; }
.nas-quiet { border-radius: 0; padding: 4px 7px; }
.nas-empty { padding: 8px 12px; }
.nas-empty-icon { opacity: 0.5; }
.nas-editor entry { border-radius: 0; padding: 5px 7px; }
.nas-editor button { border-radius: 0; }
.nas-editor check { border-radius: 0; }
.nas-manager separator, .nas-editor separator { background-color: alpha(@nas_fg, 0.15); min-height: 1px; }
.nas-form-heading { font-weight: 700; }
.nas-message { opacity: 0.8; }
.nas-message.error { color: @nas_error; opacity: 1; }
"""


def install_style(Gtk, Gdk):
    from nas_theme import font_css, palette_css, read_fonts, read_palette

    provider = Gtk.CssProvider()
    last = None

    def refresh():
        nonlocal last
        data = b"\n".join((CSS, palette_css(read_palette()), font_css(read_fonts())))
        if data != last:
            provider.load_from_data(data)
            last = data
        return True

    refresh()
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    return refresh


def label(Gtk, text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.get_style_context().add_class(style)
    return widget


def connection_card(
    Gtk,
    profile,
    state,
    persistent,
    busy,
    action,
    edit,
    forget,
    open_folder=None,
    position=None,
    move=None,
    dropped=None,
):
    from gi.repository import Pango  # type: ignore  # generated at runtime

    # An EventBox row (unlike a Box) receives pointer events, so it can show
    # :hover and accept drops. The border shows mount state; the badge spells
    # it out.
    row = Gtk.EventBox()
    row.get_style_context().add_class("nas-card")
    row.get_style_context().add_class(state)
    card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    card.set_border_width(7)  # EventBox ignores CSS padding
    row.add(card)
    if dropped is not None:
        _make_reorderable(Gtk, row, card, profile["id"], busy, dropped)
    title = label(Gtk, profile["label"], "nas-card-title")
    title.set_ellipsize(Pango.EllipsizeMode.END)
    title.set_tooltip_text(profile["label"])
    card.pack_start(title, True, True, 0)
    badge = label(
        Gtk,
        {
            "mounted": "●  Mounted",
            "unmounted": "○  Disconnected",
            "occupied": "!  Folder occupied",
        }[state],
        "nas-badge",
    )
    badge.get_style_context().add_class(state)
    card.pack_start(badge, False, False, 0)
    if state == "mounted" and open_folder:
        # The most common next step after mounting: browse the files.
        open_button = Gtk.Button(label="Open")
        open_button.set_tooltip_text("Open in the file manager")
        open_button.get_style_context().add_class("nas-quiet")
        open_button.connect("clicked", lambda *_: open_folder())
        card.pack_start(open_button, False, False, 0)
    menu_button = Gtk.MenuButton(label="⋮")
    menu_button.set_tooltip_text("Connection options")
    menu_button.get_style_context().add_class("nas-quiet")
    menu_button.get_style_context().add_class("nas-flat")
    menu_button.set_sensitive(not busy)
    card.pack_end(menu_button, False, False, 0)

    menu = Gtk.Popover.new(menu_button)
    menu.get_style_context().add_class("nas-editor")
    options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    options.set_border_width(8)
    menu.add(options)

    def menu_action(text, enabled, callback):
        button = Gtk.Button(label=text)
        button.set_sensitive(enabled and not busy)

        def activate(*_):
            menu.popdown()
            callback()

        button.connect("clicked", activate)
        options.pack_start(button, False, False, 0)
        return button

    text, enabled = card_action(state, busy)
    primary = menu_action("Disconnect" if state == "mounted" else text, enabled, action)
    menu_action("Edit", state == "unmounted", edit)
    menu_action("Forget", state == "unmounted", forget)
    if move is not None and position is not None:
        index, count = position
        menu_action("Move up", index > 0, lambda: move(-1))
        menu_action("Move down", index < count - 1, lambda: move(1))
    options.pack_start(
        Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4
    )
    details = Gtk.Expander(label="Details")
    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    info.set_border_width(6)
    for caption, value in (
        ("SHARED FOLDER", profile["source"]),
        ("MOUNT FOLDER", profile["local"]),
        ("SAVED", "Remembered connection" if persistent else "This session only"),
    ):
        info.pack_start(label(Gtk, caption, "nas-section"), False, False, 0)
        text = label(Gtk, value, "nas-path")
        text.set_selectable(True)
        text.set_line_wrap(True)
        text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text.set_max_width_chars(32)
        info.pack_start(text, False, False, 0)
    details.add(info)
    options.pack_start(details, False, False, 0)
    options.show_all()
    menu_button.set_popover(menu)
    return row, primary, menu_button


def _make_reorderable(Gtk, row, card, ident, busy, dropped):
    """A drag handle on the card, and the card as a drop target.

    Drags carry only the connection id and are limited to this app
    (SAME_APP), so nothing outside the manager can drop onto a card.
    """
    from gi.repository import Gdk  # type: ignore  # generated at runtime

    targets = [
        Gtk.TargetEntry.new("omarchy-netmount/connection", Gtk.TargetFlags.SAME_APP, 0)
    ]
    handle = Gtk.EventBox()
    handle.set_tooltip_text("Drag to reorder")
    handle.add(label(Gtk, "⠿", "nas-handle"))
    handle.set_sensitive(not busy)
    handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, targets, Gdk.DragAction.MOVE)
    handle.connect(
        "drag-data-get",
        lambda _w, _ctx, data, _info, _time: data.set(
            data.get_target(), 8, ident.encode()
        ),
    )
    handle.connect(
        "realize",
        lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "grab")
        ),
    )
    card.pack_start(handle, False, False, 0)
    row.drag_dest_set(Gtk.DestDefaults.ALL, targets, Gdk.DragAction.MOVE)

    def received(_w, _ctx, _x, _y, data, _info, _time):
        moved = data.get_data().decode("utf-8", "ignore")
        if moved and moved != ident:
            dropped(moved)

    row.connect("drag-data-received", received)


def empty_state(Gtk, add):
    # Must fit the manager's scroll area (about 190px) without scrolling.
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.get_style_context().add_class("nas-empty")
    image = Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.DND)
    image.get_style_context().add_class("nas-empty-icon")
    box.pack_start(image, False, False, 0)
    title = label(Gtk, "Your files, within reach", "nas-card-title")
    title.set_xalign(0.5)
    box.pack_start(title, False, False, 0)
    hint = label(
        Gtk, "Add a NAS connection to mount your shared folders.", "nas-subtitle"
    )
    hint.set_xalign(0.5)
    hint.set_line_wrap(True)
    box.pack_start(hint, False, False, 0)
    button = Gtk.Button(label="Add your first connection")
    button.set_halign(Gtk.Align.CENTER)
    button.get_style_context().add_class("suggested-action")
    button.get_style_context().add_class("nas-primary")
    button.connect("clicked", add)
    box.pack_start(button, False, False, 4)
    return box, button
