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
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID = "session-timer"
STATE_FILE = Path(GLib.get_user_config_dir()) / APP_ID / "state.json"

WIDGET_WIDTH = 272
RADIUS = 24
SHADOW = 22  # transparent margin around the glass, used for the drop shadow

CSS = b"""
window { background-color: transparent; }

label {
  color: white;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.45);
}

.title  { font-size: 11px; font-weight: 700; letter-spacing: 1px; color: rgba(255, 255, 255, 0.80); }
.status { font-size: 11px; font-weight: 500; color: rgba(255, 255, 255, 0.85); }
.clock  { font-size: 46px; font-weight: 300; letter-spacing: -1px; font-feature-settings: "tnum"; }
.clock.paused { color: #F6C453; }
.sub    { font-size: 12px; font-weight: 500; color: rgba(255, 255, 255, 0.70); font-feature-settings: "tnum"; }

button {
  min-height: 0;
  padding: 5px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  background-color: rgba(255, 255, 255, 0.18);
  background-image: none;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.25);
  color: white;
  font-weight: 700;
  font-size: 13px;
  text-shadow: none;
  outline-color: rgba(255, 255, 255, 0.6);
  outline-offset: 2px;
}
button label { text-shadow: none; }
button:hover  { background-color: rgba(255, 255, 255, 0.30); }
button:active { background-color: rgba(255, 255, 255, 0.40); }

button.primary { background-color: rgba(255, 255, 255, 0.92); border-color: transparent; color: #2C5D95; }
button.primary label { color: #2C5D95; }
button.primary:hover { background-color: white; }

button.close {
  padding: 0 6px;
  border: none;
  box-shadow: none;
  background-color: transparent;
  color: rgba(255, 255, 255, 0.55);
  font-size: 13px;
}
button.close:hover { background-color: rgba(255, 255, 255, 0.20); color: white; }

menu, .menu { background-color: #2b3440; color: white; border-radius: 8px; padding: 4px; }
menuitem { padding: 6px 12px; border-radius: 6px; }
menuitem:hover { background-color: rgba(255, 255, 255, 0.15); }
"""


# ---- Timer state ---------------------------------------------------------
# Elapsed time is always derived from the wall clock, never from counting ticks,
# so it stays exact no matter how the process is scheduled.

class Session:
    def __init__(self):
        self.started_at = None  # wall-clock ms when the session first started
        self.resumed_at = None  # wall-clock ms of the latest resume, None while paused
        self.banked = 0         # ms accumulated before the latest resume
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
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(
                {"startedAt": self.started_at, "resumedAt": self.resumed_at, "banked": self.banked}))
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


def draw_glass(cr, x, y, w, h, r):
    # Soft drop shadow: stacked, growing, faint rounded rects.
    for i in range(16, 0, -1):
        rounded_rect(cr, x - i * 0.55, y + 6 - i * 0.35, w + i * 1.1, h + i * 0.7, r + i * 0.5)
        cr.set_source_rgba(0, 0, 0, 0.018)
        cr.fill()

    # Body: a light tint that fades towards the bottom, like thick clear glass.
    rounded_rect(cr, x, y, w, h, r)
    body = cairo.LinearGradient(x, y, x, y + h)
    body.add_color_stop_rgba(0, 1, 1, 1, 0.36)
    body.add_color_stop_rgba(1, 1, 1, 1, 0.20)
    cr.set_source(body)
    cr.fill()

    cr.save()
    rounded_rect(cr, x, y, w, h, r)
    cr.clip()

    # Specular sheen sweeping in from the top-left corner.
    sheen = cairo.LinearGradient(x, y, x + w * 0.6, y + h)
    sheen.add_color_stop_rgba(0.0, 1, 1, 1, 0.22)
    sheen.add_color_stop_rgba(0.45, 1, 1, 1, 0.0)
    cr.set_source(sheen)
    cr.paint()

    # Refracted inner edge: a wide, faint band just inside the outline.
    rounded_rect(cr, x + 4, y + 4, w - 8, h - 8, r - 4)
    cr.set_line_width(7)
    cr.set_source_rgba(1, 1, 1, 0.07)
    cr.stroke()
    rounded_rect(cr, x + 1.5, y + 1.5, w - 3, h - 3, r - 1.5)
    cr.set_line_width(1.5)
    cr.set_source_rgba(1, 1, 1, 0.16)
    cr.stroke()
    cr.restore()

    # Outline: bright where light hits (top-left), dim opposite.
    rounded_rect(cr, x + 0.5, y + 0.5, w - 1, h - 1, r - 0.5)
    rim = cairo.LinearGradient(x, y, x + w, y + h)
    rim.add_color_stop_rgba(0.0, 1, 1, 1, 0.85)
    rim.add_color_stop_rgba(0.5, 1, 1, 1, 0.35)
    rim.add_color_stop_rgba(1.0, 1, 1, 1, 0.55)
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
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_app_paintable(True)
        self.set_default_size(WIDGET_WIDTH + 2 * SHADOW, -1)

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
        self.render()
        GLib.timeout_add(250, self.tick)

    # -- layout --

    def build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_margin_top(SHADOW + 13)
        root.set_margin_bottom(SHADOW + 16)
        root.set_margin_start(SHADOW + 18)
        root.set_margin_end(SHADOW + 18)
        self.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(header, False, False, 0)

        title = Gtk.Label(label="⏱  SESSION")
        title.get_style_context().add_class("title")
        header.pack_start(title, False, False, 0)

        close = Gtk.Button(label="✕")
        close.get_style_context().add_class("close")
        close.set_tooltip_text("Quit (Ctrl+Q)")
        close.set_can_focus(False)
        close.connect("clicked", lambda *_: self.destroy())
        header.pack_end(close, False, False, 0)

        self.status = Gtk.Label()
        self.status.get_style_context().add_class("status")
        header.pack_end(self.status, False, False, 0)

        self.clock = Gtk.Label(xalign=0)
        self.clock.get_style_context().add_class("clock")
        self.clock.set_margin_top(2)
        root.pack_start(self.clock, False, False, 0)

        self.sub = Gtk.Label(xalign=0)
        self.sub.get_style_context().add_class("sub")
        root.pack_start(self.sub, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        controls.set_margin_top(14)
        root.pack_start(controls, False, False, 0)

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
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self.destroy())
        self.menu.append(quit_item)
        self.menu.show_all()

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
        draw_glass(cr, SHADOW, SHADOW, w - 2 * SHADOW, h - 2 * SHADOW, RADIUS)
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
    GLib.set_prgname(APP_ID)  # becomes the X11 window class, used by blur extensions and the .desktop file
    # Subpixel (LCD) text antialiasing leaves colour fringes on a transparent window.
    Gtk.Settings.get_default().set_property("gtk-xft-rgba", "none")
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    window = TimerWindow()
    window.show_all()
    area = Gdk.Display.get_default().get_primary_monitor().get_workarea()
    window.move(area.x + area.width - WIDGET_WIDTH - 2 * SHADOW - 24, area.y + 48)
    Gtk.main()


if __name__ == "__main__":
    main()
