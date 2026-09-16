#!/usr/bin/python3
"""Session Timer — a small frameless glass widget that floats above every window.

Made for online tutors who charge by the hour: start when the lesson begins,
pause for breaks, reset for the next student. The student can see the elapsed
time on your screen share.

Runs on Ubuntu with nothing beyond the stock GTK 3 Python bindings.
"""

import json
import os
import sys
import time
from pathlib import Path

# Always-on-top is not available to apps on native Wayland, so run through
# XWayland where GNOME/KDE honour the "keep above" hint. Must be set before GTK loads.
os.environ.setdefault("GDK_BACKEND", "x11")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import cairo  # noqa: E402
from gi.repository import Gdk, Gio, GLib  # noqa: E402

APP_ID = "session-timer"
# Becomes the X11 window class. GNOME's dock matches it to session-timer.desktop
# (StartupWMClass) to show the right icon. Must happen before GTK initialises.
GLib.set_prgname(APP_ID)
Gdk.set_program_class(APP_ID)
from gi.repository import Gtk  # noqa: E402
STATE_FILE = Path(GLib.get_user_config_dir()) / APP_ID / "state.json"

WIDGET_SIZE = 188  # the glass is square
RADIUS = 24
SHADOW = 22  # transparent margin around the glass, used for the drop shadow

CSS = b"""
window { background-color: transparent; }

label { font-family: "Ubuntu Sans", "Ubuntu", "Cantarell", sans-serif; }

.title  { font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
.status { font-size: 10px; font-weight: 500; }
.clock  { font-size: 40px; font-weight: 300; letter-spacing: -1px; font-feature-settings: "tnum"; }
.clock.paused { color: #B8780A; }
.sub    { font-size: 11px; font-weight: 500; font-feature-settings: "tnum"; }

button {
  min-height: 0;
  min-width: 0;
  padding: 5px 6px;
  border-radius: 999px;
  background-image: none;
  font-weight: 700;
  font-size: 12px;
  text-shadow: none;
  outline-offset: 2px;
}
button label { text-shadow: none; }
button.close { padding: 0 4px; border: none; box-shadow: none; background-color: transparent; font-size: 12px; }

/* ---- Dark: smoked glass, white text ---- */
window.dark label { color: white; text-shadow: 0 1px 3px rgba(0, 0, 0, 0.45); }
window.dark .title, window.dark .sub { color: rgba(255, 255, 255, 0.72); }
window.dark .status { color: rgba(255, 255, 255, 0.85); }
window.dark .clock.paused { color: #F6C453; }
window.dark button {
  border: 1px solid rgba(255, 255, 255, 0.30);
  background-color: rgba(255, 255, 255, 0.16);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.20);
  color: white;
  outline-color: rgba(255, 255, 255, 0.6);
}
window.dark button:hover  { background-color: rgba(255, 255, 255, 0.28); }
window.dark button:active { background-color: rgba(255, 255, 255, 0.38); }
window.dark button.primary { background-color: rgba(255, 255, 255, 0.92); border-color: transparent; }
window.dark button.primary label { color: #1E3A5C; }
window.dark button.primary:hover { background-color: white; }
window.dark button.close { background-color: transparent; border: none; box-shadow: none; }
window.dark button.close label { color: rgba(255, 255, 255, 0.55); }
window.dark button.close:hover { background-color: rgba(255, 255, 255, 0.20); }
window.dark button.close:hover label { color: white; }

/* ---- Light: frosted white glass, ink text ---- */
window.light label { color: #16263A; text-shadow: 0 1px 0 rgba(255, 255, 255, 0.45); }
window.light .title, window.light .sub { color: rgba(22, 38, 58, 0.68); }
window.light .status { color: rgba(22, 38, 58, 0.85); }
window.light button {
  border: 1px solid rgba(22, 38, 58, 0.18);
  background-color: rgba(255, 255, 255, 0.55);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
  color: #16263A;
  outline-color: rgba(22, 38, 58, 0.5);
}
window.light button:hover  { background-color: rgba(255, 255, 255, 0.80); }
window.light button:active { background-color: rgba(255, 255, 255, 0.95); }
window.light button.primary { background-color: #1E3A5C; border-color: transparent; box-shadow: none; }
window.light button.primary label { color: white; }
window.light button.primary:hover { background-color: #2A4E78; }
window.light button.close { background-color: transparent; border: none; box-shadow: none; }
window.light button.close label { color: rgba(22, 38, 58, 0.5); }
window.light button.close:hover { background-color: rgba(22, 38, 58, 0.10); }
window.light button.close:hover label { color: #16263A; }
"""

THEMES = ("system", "light", "dark")


def system_prefers_dark():
    """Read GNOME's light/dark preference; fall back to the GTK theme name elsewhere."""
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if source and source.lookup("org.gnome.desktop.interface", True):
            scheme = Gio.Settings.new("org.gnome.desktop.interface").get_string("color-scheme")
            return scheme == "prefer-dark"
    except Exception:  # noqa: BLE001
        pass
    settings = Gtk.Settings.get_default()
    return bool(settings.get_property("gtk-application-prefer-dark-theme")
                or "dark" in (settings.get_property("gtk-theme-name") or "").lower())


# ---- Timer state ---------------------------------------------------------
# Elapsed time is always derived from the wall clock, never from counting ticks,
# so it stays exact no matter how the process is scheduled.

class Session:
    def __init__(self):
        self.started_at = None  # wall-clock ms when the session first started
        self.resumed_at = None  # wall-clock ms of the latest resume, None while paused
        self.banked = 0         # ms accumulated before the latest resume
        self.theme = "system"   # "system", "light" or "dark"
        self.load()

    @staticmethod
    def now():
        return int(time.time() * 1000)

    @property
    def running(self):
        return self.resumed_at is not None

    @property
    def elapsed(self):
        return self.banked + (self.now() - self.resumed_at if self.running else 0)

    def start(self):
        if self.running:
            return
        now = self.now()
        if self.started_at is None:
            self.started_at = now
        self.resumed_at = now
        self.save()

    def pause(self):
        if not self.running:
            return
        self.banked += self.now() - self.resumed_at
        self.resumed_at = None
        self.save()

    def reset(self):
        self.started_at = self.resumed_at = None
        self.banked = 0
        self.save()

    def load(self):
        try:
            data = json.loads(STATE_FILE.read_text())
            self.started_at = data.get("startedAt")
            self.resumed_at = data.get("resumedAt")
            self.banked = int(data.get("banked", 0))
            if data.get("theme") in THEMES:
                self.theme = data["theme"]
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(
                {"startedAt": self.started_at, "resumedAt": self.resumed_at,
                 "banked": self.banked, "theme": self.theme}))
        except OSError:
            pass


def format_duration(ms):
    total = ms // 1000
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


# ---- Drawing the glass ---------------------------------------------------

def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.14159)
    cr.arc(x + r, y + r, r, 3.14159, 4.71239)
    cr.close_path()


def draw_glass(cr, x, y, w, h, r, dark):
    # Soft drop shadow: stacked, growing, faint rounded rects.
    for i in range(16, 0, -1):
        rounded_rect(cr, x - i * 0.55, y + 6 - i * 0.35, w + i * 1.1, h + i * 0.7, r + i * 0.5)
        cr.set_source_rgba(0, 0, 0, 0.022 if dark else 0.014)
        cr.fill()

    # Body: dark mode is smoked glass, light mode is frosted white. Both fade
    # towards the bottom like a thick slab.
    rounded_rect(cr, x, y, w, h, r)
    body = cairo.LinearGradient(x, y, x, y + h)
    if dark:
        body.add_color_stop_rgba(0, 0.10, 0.13, 0.18, 0.62)
        body.add_color_stop_rgba(1, 0.06, 0.08, 0.12, 0.72)
    else:
        body.add_color_stop_rgba(0, 1, 1, 1, 0.90)
        body.add_color_stop_rgba(1, 1, 1, 1, 0.82)
    cr.set_source(body)
    cr.fill()

    cr.save()
    rounded_rect(cr, x, y, w, h, r)
    cr.clip()

    # Specular sheen sweeping in from the top-left corner.
    sheen = cairo.LinearGradient(x, y, x + w * 0.6, y + h)
    sheen.add_color_stop_rgba(0.0, 1, 1, 1, 0.16 if dark else 0.35)
    sheen.add_color_stop_rgba(0.45, 1, 1, 1, 0.0)
    cr.set_source(sheen)
    cr.paint()

    # Refracted inner edge: a wide, faint band just inside the outline.
    rounded_rect(cr, x + 4, y + 4, w - 8, h - 8, r - 4)
    cr.set_line_width(7)
    cr.set_source_rgba(1, 1, 1, 0.06 if dark else 0.30)
    cr.stroke()
    rounded_rect(cr, x + 1.5, y + 1.5, w - 3, h - 3, r - 1.5)
    cr.set_line_width(1.5)
    cr.set_source_rgba(1, 1, 1, 0.14 if dark else 0.55)
    cr.stroke()
    cr.restore()

    # Outline: bright where light hits (top-left), dim opposite.
    rounded_rect(cr, x + 0.5, y + 0.5, w - 1, h - 1, r - 0.5)
    rim = cairo.LinearGradient(x, y, x + w, y + h)
    if dark:
        rim.add_color_stop_rgba(0.0, 1, 1, 1, 0.55)
        rim.add_color_stop_rgba(0.5, 1, 1, 1, 0.18)
        rim.add_color_stop_rgba(1.0, 1, 1, 1, 0.35)
    else:
        rim.add_color_stop_rgba(0.0, 1, 1, 1, 0.95)
        rim.add_color_stop_rgba(0.5, 0.09, 0.15, 0.23, 0.18)
        rim.add_color_stop_rgba(1.0, 1, 1, 1, 0.7)
    cr.set_source(rim)
    cr.set_line_width(1)
    cr.stroke()


# ---- Window --------------------------------------------------------------

class TimerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Session Timer")
        self.session = Session()

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.stick()  # visible on every workspace
        self.set_app_paintable(True)
        self.set_size_request(WIDGET_SIZE + 2 * SHADOW, WIDGET_SIZE + 2 * SHADOW)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)
        else:
            print("No compositor: the window can't be transparent.", file=sys.stderr)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("key-press-event", self.on_key_press)
        self.connect("size-allocate", self.on_size_allocate)
        self.connect("realize", self.on_realize)
        self.connect("destroy", Gtk.main_quit)

        self.build_ui()
        self.build_menu()
        self.apply_theme()
        self.watch_system_theme()
        self.render()
        GLib.timeout_add(250, self.tick)

    # -- layout --

    def build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_margin_top(SHADOW + 12)
        root.set_margin_bottom(SHADOW + 14)
        root.set_margin_start(SHADOW + 15)
        root.set_margin_end(SHADOW + 15)
        self.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(header, False, False, 0)

        title = Gtk.Label(label="\u23F1 SESSION")
        title.get_style_context().add_class("title")
        header.pack_start(title, False, False, 0)

        close = Gtk.Button(label="\u2715")
        close.get_style_context().add_class("close")
        close.set_tooltip_text("Quit (Ctrl+Q)")
        close.set_can_focus(False)
        close.connect("clicked", lambda *_: self.destroy())
        header.pack_end(close, False, False, 0)

        self.status = Gtk.Label()
        self.status.get_style_context().add_class("status")
        header.pack_end(self.status, False, False, 0)

        # Clock and start time sit in the middle of the tile, whatever height it gets.
        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, valign=Gtk.Align.CENTER)
        root.pack_start(middle, True, True, 0)

        self.clock = Gtk.Label(xalign=0)
        self.clock.get_style_context().add_class("clock")
        middle.pack_start(self.clock, False, False, 0)

        self.sub = Gtk.Label(xalign=0)
        self.sub.get_style_context().add_class("sub")
        middle.pack_start(self.sub, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        root.pack_end(controls, False, False, 0)

        self.toggle = Gtk.Button()
        self.toggle.get_style_context().add_class("primary")
        self.toggle.set_can_focus(False)
        self.toggle.connect("clicked", lambda *_: self.toggle_running())
        controls.pack_start(self.toggle, True, True, 0)

        reset = Gtk.Button(label="Reset")
        reset.set_can_focus(False)
        reset.connect("clicked", lambda *_: self.reset())
        controls.pack_start(reset, True, True, 0)

    def build_menu(self):
        self.menu = Gtk.Menu()
        self.on_top = Gtk.CheckMenuItem(label="Keep on top")
        self.on_top.set_active(True)
        self.on_top.connect("toggled", lambda item: self.set_keep_above(item.get_active()))
        self.menu.append(self.on_top)
        self.menu.append(Gtk.SeparatorMenuItem())

        group = None
        for value, label in (("system", "Match system"), ("light", "Light"), ("dark", "Dark")):
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or item
            item.set_active(value == self.session.theme)
            item.connect("toggled", self.on_theme_chosen, value)
            self.menu.append(item)
        self.menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self.destroy())
        self.menu.append(quit_item)
        self.menu.show_all()

    # -- appearance --

    @property
    def dark(self):
        if self.session.theme == "system":
            return system_prefers_dark()
        return self.session.theme == "dark"

    def apply_theme(self):
        style = self.get_style_context()
        style.remove_class("light")
        style.remove_class("dark")
        style.add_class("dark" if self.dark else "light")
        self.queue_draw()

    def watch_system_theme(self):
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source and source.lookup("org.gnome.desktop.interface", True):
                self._interface = Gio.Settings.new("org.gnome.desktop.interface")
                self._interface.connect("changed::color-scheme", lambda *_: self.apply_theme())
        except Exception:  # noqa: BLE001
            pass
        Gtk.Settings.get_default().connect("notify::gtk-theme-name", lambda *_: self.apply_theme())

    def on_theme_chosen(self, item, value):
        if item.get_active():
            self.session.theme = value
            self.session.save()
            self.apply_theme()

    # -- behaviour --

    def toggle_running(self):
        if self.session.running:
            self.session.pause()
        else:
            self.session.start()
        self.render()

    def reset(self):
        self.session.reset()
        self.render()

    def tick(self):
        self.render()
        return True

    def render(self):
        s = self.session
        self.clock.set_text(format_duration(s.elapsed))
        clock_style = self.clock.get_style_context()

        if s.started_at is None:
            self.status.set_markup("<span foreground='#DDE8F5'>●</span>  Ready")
            self.sub.set_text("Not started yet")
            self.toggle.set_label("Start")
            clock_style.remove_class("paused")
        elif s.running:
            self.status.set_markup("<span foreground='#7CF4A0'>●</span>  Live")
            self.sub.set_text("Started " + time.strftime("%-I:%M %p", time.localtime(s.started_at / 1000)))
            self.toggle.set_label("Pause")
            clock_style.remove_class("paused")
        else:
            self.status.set_markup("<span foreground='#F6C453'>●</span>  Paused")
            self.sub.set_text("Started " + time.strftime("%-I:%M %p", time.localtime(s.started_at / 1000)))
            self.toggle.set_label("Resume")
            clock_style.add_class("paused")

    # -- events --

    def on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        draw_glass(cr, SHADOW, SHADOW, w - 2 * SHADOW, h - 2 * SHADOW, RADIUS, self.dark)
        return False  # let children draw on top

    def on_button_press(self, widget, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True
        if event.button == 3:
            self.menu.popup_at_pointer(event)
            return True
        return False

    def on_key_press(self, widget, event):
        key = event.keyval
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if key == Gdk.KEY_space:
            self.toggle_running()
        elif key in (Gdk.KEY_r, Gdk.KEY_R):
            self.reset()
        elif ctrl and key in (Gdk.KEY_q, Gdk.KEY_Q):
            self.destroy()
        else:
            return False
        return True

    def on_size_allocate(self, widget, allocation):
        # Only the glass itself should catch clicks, not the transparent shadow margin.
        win = self.get_window()
        if win is None:
            return
        region = cairo.Region(cairo.RectangleInt(
            SHADOW, SHADOW, allocation.width - 2 * SHADOW, allocation.height - 2 * SHADOW))
        win.input_shape_combine_region(region, 0, 0)

    def on_realize(self, widget):
        self.request_compositor_blur()

    def request_compositor_blur(self):
        """Ask the compositor to blur what's behind the glass, where it can.

        KDE's KWin honours _KDE_NET_WM_BLUR_BEHIND_REGION. GNOME has no such
        hint; there the 'Blur my Shell' extension can blur this app by its
        window class (session-timer) — see the README.
        """
        win = self.get_window()
        if win is None or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
            return
        try:
            Gdk.property_change(
                win,
                Gdk.Atom.intern("_KDE_NET_WM_BLUR_BEHIND_REGION", False),
                Gdk.Atom.intern("CARDINAL", False),
                32, Gdk.PropMode.REPLACE, b"", 0)
        except Exception as error:  # noqa: BLE001 — a cosmetic hint, never fatal
            print(f"Could not request compositor blur: {error}", file=sys.stderr)


def main():
    # Subpixel (LCD) text antialiasing leaves colour fringes on a transparent window.
    Gtk.Settings.get_default().set_property("gtk-xft-rgba", "none")
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    window = TimerWindow()
    window.show_all()
    area = Gdk.Display.get_default().get_primary_monitor().get_workarea()
    window.move(area.x + area.width - WIDGET_SIZE - 2 * SHADOW - 24, area.y + 48)
    Gtk.main()


if __name__ == "__main__":
    main()
