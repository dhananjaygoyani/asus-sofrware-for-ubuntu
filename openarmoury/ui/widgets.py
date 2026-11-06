"""Custom drawing widgets, and the generic row for a firmware attribute."""
import math

import gi

gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402


ACCENT = (0.85, 0.02, 0.16)


def _colour(r, g, b, a=1.0):
    # Gdk.RGBA ignores constructor arguments in GTK4's bindings, leaving it transparent.
    value = Gdk.RGBA()
    value.red, value.green, value.blue, value.alpha = r, g, b, a
    return value


def rgba(colour):
    return _colour(colour[0] / 255, colour[1] / 255, colour[2] / 255)


def to_colour(value):
    return [round(value.red * 255), round(value.green * 255), round(value.blue * 255)]


def colour_button(colour, on_change):
    button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), rgba=rgba(colour), valign=Gtk.Align.CENTER)
    button.connect("notify::rgba", lambda b, _p: on_change(to_colour(b.get_rgba())))
    return button


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def _point(x, y):
    return Graphene.Point().init(x, y)


def _fill_rounded(snapshot, x, y, w, h, radius, colour):
    outline = Gsk.RoundedRect()
    outline.init_from_rect(_rect(x, y, w, h), radius)
    snapshot.push_rounded_clip(outline)
    snapshot.append_color(colour, _rect(x, y, w, h))
    snapshot.pop()


class Canvas(Gtk.Widget):
    """A widget drawn with GTK's own snapshot API, so no Cairo bindings are needed."""

    def __init__(self, height, **kwargs):
        super().__init__(hexpand=True, **kwargs)
        self.natural_height = height

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.VERTICAL:
            return self.natural_height, self.natural_height, -1, -1
        return 200, 600, -1, -1

    def _text(self, snapshot, text, x, y, colour):
        layout = self.create_pango_layout(text)
        snapshot.save()
        snapshot.translate(_point(x, y))
        snapshot.append_layout(layout, colour)
        snapshot.restore()


class Gauge(Canvas):
    """A dial showing a value within a range. It turns brighter as it nears the top."""

    SWEEP = 1.5 * math.pi
    START = 0.75 * math.pi

    def __init__(self, title, unit, maximum):
        super().__init__(150)
        self.title = title
        self.unit = unit
        self.maximum = maximum
        self.value = None

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.VERTICAL:
            return self.natural_height, self.natural_height, -1, -1
        return 130, 150, -1, -1

    def set_value(self, value):
        self.value = value
        reading = f"{value:.0f} {self.unit}" if value is not None else "not available"
        self.update_property([Gtk.AccessibleProperty.LABEL], [f"{self.title}: {reading}"])
        self.queue_draw()

    def _arc(self, centre_x, centre_y, radius, amount):
        builder = Gsk.PathBuilder.new()
        steps = max(2, int(48 * amount))
        for step in range(steps + 1):
            angle = self.START + self.SWEEP * amount * step / steps
            x, y = centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle)
            (builder.line_to if step else builder.move_to)(x, y)
        return builder.to_path()

    def _centred(self, snapshot, text, centre_x, y, colour, markup=None):
        layout = self.create_pango_layout(text)
        if markup:
            layout.set_markup(markup, -1)
        width, _height = layout.get_pixel_size()
        snapshot.save()
        snapshot.translate(_point(centre_x - width / 2, y))
        snapshot.append_layout(layout, colour)
        snapshot.restore()

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        centre_x, centre_y = width / 2, height / 2 - 4
        radius = min(width, height) / 2 - 14
        stroke = Gsk.Stroke.new(9)
        stroke.set_line_cap(Gsk.LineCap.ROUND)
        snapshot.append_stroke(self._arc(centre_x, centre_y, radius, 1.0), stroke, _colour(1, 1, 1, 0.09))
        fg = self.get_color()
        if self.value is None:
            self._centred(snapshot, "–", centre_x, centre_y - 10, fg)
        else:
            amount = max(0.0, min(1.0, self.value / self.maximum))
            if amount > 0.005:
                colour = _colour(1.0, 0.2, 0.3) if amount > 0.85 else _colour(*ACCENT)
                snapshot.append_stroke(self._arc(centre_x, centre_y, radius, amount), stroke, colour)
            text = GLib.markup_escape_text(f"{self.value:,.0f}")
            self._centred(snapshot, "", centre_x, centre_y - 20, fg, f"<span size='x-large' weight='heavy'>{text}</span>")
            self._centred(snapshot, self.unit, centre_x, centre_y + 8, _colour(fg.red, fg.green, fg.blue, 0.6))
        self._centred(snapshot, self.title, centre_x, height - 22, _colour(fg.red, fg.green, fg.blue, 0.75))


class Sparkline(Canvas):
    """A small history chart, from 0 to 100."""

    def __init__(self):
        super().__init__(48, margin_top=6)
        self.values = []
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Recent history"])

    def set_values(self, values):
        self.values = values
        self.queue_draw()

    def do_snapshot(self, snapshot):
        if len(self.values) < 2:
            return
        width, height = self.get_width(), self.get_height()
        step = width / (len(self.values) - 1)
        y = lambda v: height - max(0, min(100, v)) / 100 * (height - 2) - 1  # noqa: E731
        area = Gsk.PathBuilder.new()
        area.move_to(0, height)
        for index, value in enumerate(self.values):
            area.line_to(index * step, y(value))
        area.line_to(width, height)
        area.close()
        snapshot.append_fill(area.to_path(), Gsk.FillRule.WINDING, _colour(*ACCENT, 0.25))
        line = Gsk.PathBuilder.new()
        for index, value in enumerate(self.values):
            (line.line_to if index else line.move_to)(index * step, y(value))
        snapshot.append_stroke(line.to_path(), Gsk.Stroke.new(2), _colour(*ACCENT))


class KeyboardView(Canvas):
    """Draws the layout lit by a frame of colours. Keys can be clicked or dragged over to paint."""

    def __init__(self, on_paint=None):
        super().__init__(250)
        self.keys = []
        self.frame = {}
        self.on_paint = on_paint
        self.scale = 1.0
        self.origin = (0, 0)
        self.drag_start = (0, 0)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Keyboard lighting preview"])
        if on_paint:
            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", self._begin)
            drag.connect("drag-update", self._drag_update)
            self.add_controller(drag)

    def _begin(self, _gesture, x, y):
        self.drag_start = (x, y)
        self._paint_at(x, y)

    def _drag_update(self, _gesture, dx, dy):
        self._paint_at(self.drag_start[0] + dx, self.drag_start[1] + dy)

    def set_keys(self, keys):
        self.keys = keys
        self.queue_draw()

    def set_frame(self, frame):
        self.frame = frame
        self.queue_draw()

    def _key_at(self, px, py):
        x = (px - self.origin[0]) / self.scale
        y = (py - self.origin[1]) / self.scale
        for key in self.keys:
            if key["x"] <= x <= key["x"] + key["w"] and key["y"] <= y <= key["y"] + key["h"]:
                return key
        return None

    def _paint_at(self, x, y):
        key = self._key_at(x, y)
        if key:
            self.on_paint(key)

    def do_snapshot(self, snapshot):
        if not self.keys:
            return
        width, height = self.get_width(), self.get_height()
        extent_x = max(k["x"] + k["w"] for k in self.keys)
        extent_y = max(k["y"] + k["h"] for k in self.keys)
        self.scale = scale = max(0.01, min((width - 24) / extent_x, (height - 24) / extent_y))
        self.origin = ((width - extent_x * scale) / 2, (height - extent_y * scale) / 2)
        _fill_rounded(snapshot, self.origin[0] - 8, self.origin[1] - 8, extent_x * scale + 16, extent_y * scale + 16, 10, _colour(0.09, 0.09, 0.1))
        for key in self.keys:
            colour = self.frame.get(key["code"], (0, 0, 0))
            x = self.origin[0] + key["x"] * scale
            y = self.origin[1] + key["y"] * scale
            w, h = key["w"] * scale, key["h"] * scale
            r, g, b = (c / 255 for c in colour)
            # A soft glow behind lit keys, like light through the keycap edge.
            if max(r, g, b) > 0.02:
                _fill_rounded(snapshot, x - 1.5, y - 1.5, w + 3, h + 3, min(6, scale * 0.3), _colour(r, g, b, 0.35))
            _fill_rounded(snapshot, x, y, w, h, min(4, scale * 0.2), _colour(0.17 + r * 0.83, 0.17 + g * 0.83, 0.18 + b * 0.82))


class CurveView(Canvas):
    """A fan curve with draggable points. Arrow keys also work: left/right pick, up/down change speed."""

    TEMP_MIN, TEMP_MAX = 20, 110

    def __init__(self, on_change):
        super().__init__(280, focusable=True)
        self.points = []
        self.on_change = on_change
        self.selected = None
        self.area = (0, 0, 1, 1)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Fan curve editor. Left and right arrows pick a point, up and down change its speed."],
        )
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        self.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.drag_start = (0, 0)

    def set_points(self, points):
        self.points = [list(p) for p in points]
        self.queue_draw()

    def _xy(self, point):
        left, top, width, height = self.area
        x = left + (point[0] - self.TEMP_MIN) / (self.TEMP_MAX - self.TEMP_MIN) * width
        y = top + height - point[1] / 255 * height
        return x, y

    def _begin(self, _gesture, x, y):
        self.grab_focus()
        self.drag_start = (x, y)
        best, best_distance = None, 28
        for index, point in enumerate(self.points):
            px, py = self._xy(point)
            distance = math.hypot(px - x, py - y)
            if distance < best_distance:
                best, best_distance = index, distance
        self.selected = best
        self.queue_draw()

    def _update(self, _gesture, dx, dy):
        if self.selected is None:
            return
        left, top, width, height = self.area
        temp = self.TEMP_MIN + (self.drag_start[0] + dx - left) / width * (self.TEMP_MAX - self.TEMP_MIN)
        pwm = (top + height - (self.drag_start[1] + dy)) / height * 255
        self._move(self.selected, temp, pwm)

    def _move(self, index, temp, pwm):
        """Clamp between the neighbours so the curve always stays monotonic."""
        low_temp = self.points[index - 1][0] if index else self.TEMP_MIN
        high_temp = self.points[index + 1][0] if index < len(self.points) - 1 else self.TEMP_MAX
        low_pwm = self.points[index - 1][1] if index else 0
        high_pwm = self.points[index + 1][1] if index < len(self.points) - 1 else 255
        self.points[index] = [round(max(low_temp, min(high_temp, temp))), round(max(low_pwm, min(high_pwm, pwm)))]
        self.queue_draw()
        self.on_change(self.points)

    def _key(self, _controller, keyval, _code, _state):
        if not self.points:
            return False
        names = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1}
        if keyval in names:
            current = 0 if self.selected is None else self.selected + names[keyval]
            self.selected = max(0, min(len(self.points) - 1, current))
            self.queue_draw()
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and self.selected is not None:
            temp, pwm = self.points[self.selected]
            self._move(self.selected, temp, pwm + (5 if keyval == Gdk.KEY_Up else -5))
            return True
        return False

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        self.area = (46, 12, max(1, width - 76), max(1, height - 42))
        left, top, w, h = self.area
        fg = self.get_color()
        grid = _colour(fg.red, fg.green, fg.blue, 0.15)
        label = _colour(fg.red, fg.green, fg.blue, 0.7)
        for percent in range(0, 101, 25):
            y = top + h - percent / 100 * h
            snapshot.append_color(grid, _rect(left, y, w, 1))
            self._text(snapshot, f"{percent}%", 4, y - 9, label)
        for temp in range(self.TEMP_MIN, self.TEMP_MAX + 1, 10):
            x = left + (temp - self.TEMP_MIN) / (self.TEMP_MAX - self.TEMP_MIN) * w
            snapshot.append_color(grid, _rect(x, top, 1, h))
            self._text(snapshot, f"{temp}°", x - 10, top + h + 6, label)
        if not self.points:
            return
        accent = _colour(*ACCENT)
        area = Gsk.PathBuilder.new()
        area.move_to(self._xy(self.points[0])[0], top + h)
        for point in self.points:
            area.line_to(*self._xy(point))
        area.line_to(self._xy(self.points[-1])[0], top + h)
        area.close()
        snapshot.append_fill(area.to_path(), Gsk.FillRule.WINDING, _colour(*ACCENT, 0.18))
        line = Gsk.PathBuilder.new()
        for index, point in enumerate(self.points):
            (line.line_to if index else line.move_to)(*self._xy(point))
        snapshot.append_stroke(line.to_path(), Gsk.Stroke.new(2.5), accent)
        for index, point in enumerate(self.points):
            x, y = self._xy(point)
            radius = 8 if index == self.selected else 6
            _fill_rounded(snapshot, x - radius, y - radius, radius * 2, radius * 2, radius, accent)
            _fill_rounded(snapshot, x - 3, y - 3, 6, 6, 3, _colour(1, 1, 1))
        if self.selected is not None:
            temp, pwm = self.points[self.selected]
            x, y = self._xy(self.points[self.selected])
            self._text(snapshot, f"{temp}°C · {round(pwm / 255 * 100)}%", min(x + 10, left + w - 90), max(y - 26, top), fg)


ATTRIBUTE_TITLES = {
    "apu_mem": "Integrated GPU memory",
    "boot_sound": "Boot sound",
    "charge_mode": "Charging source",
    "dgpu_disable": "Turn off discrete GPU",
    "dgpu_power_state": "Discrete GPU power state",
    "egpu_connected": "External GPU connected",
    "egpu_enable": "Use external GPU",
    "gpu_mux_mode": "GPU MUX mode",
    "mini_led_mode": "Mini-LED mode",
    "nv_base_tgp": "GPU base power",
    "nv_dynamic_boost": "GPU dynamic boost",
    "nv_temp_target": "GPU temperature target",
    "nv_tgp": "GPU power limit",
    "panel_overdrive": "Panel overdrive",
    "ppt_apu_sppt": "APU fast power limit",
    "ppt_pl1_spl": "CPU sustained power limit",
    "ppt_pl2_sppt": "CPU fast power limit",
    "ppt_pl3_fppt": "CPU peak power limit",
    "ppt_platform_sppt": "Platform power limit",
}


def attribute_row(ctx, attribute, warning=None, on_written=None):
    """One row for any firmware attribute, built from what the kernel reports about it."""
    label = attribute["label"]
    title = ATTRIBUTE_TITLES.get(attribute["name"], attribute["name"].replace("_", " ").capitalize())
    choices = [c for c in attribute["choices"] if c]

    state = {"quiet": False, "revert": None}

    def written(ok):
        if not ok and state["revert"]:
            # Cancelled or failed: nothing changed, so the control mustn't claim it did.
            state["quiet"] = True
            state["revert"]()
            state["quiet"] = False
        if on_written:
            on_written()

    def send(value):
        if not state["quiet"]:
            ctx.submit([ctx.write_op(f"attr:{attribute['name']}", attribute["path"], value)], written, warning)

    if attribute["value"] is None:
        row = Adw.ActionRow(title=title, subtitle=f"{label}. Not available on this laptop.")
        row.add_css_class("dim-label")
        return row
    if not attribute["writable"]:
        row = Adw.ActionRow(title=title, subtitle=label)
        row.add_suffix(Gtk.Label(label=attribute["value"], css_classes=["dim-label"]))
        return row
    if attribute["type"] == "integer" and attribute["min"] is not None and attribute["max"] is not None:
        row = Adw.SpinRow.new_with_range(attribute["min"], attribute["max"], attribute["step"] or 1)
        row.set_title(title)
        row.set_subtitle(f"{label} ({attribute['min']} to {attribute['max']})")
        row.set_value(float(attribute["value"]))
        apply_button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        apply_button.connect("clicked", lambda _b: send(int(row.get_value())))
        row.add_suffix(apply_button)
        return row
    if choices == ["0", "1"]:
        row = Adw.SwitchRow(title=title, subtitle=label, active=attribute["value"] == "1")
        state["revert"] = lambda: row.set_active(ctx.hw.read(attribute["path"]) == "1")
        row.connect("notify::active", lambda r, _p: send("1" if r.get_active() else "0"))
        return row
    if choices:
        row = Adw.ComboRow(title=title, subtitle=label, model=Gtk.StringList.new(choices))
        if attribute["value"] in choices:
            row.set_selected(choices.index(attribute["value"]))
        def revert():
            current = ctx.hw.read(attribute["path"])
            if current in choices:
                row.set_selected(choices.index(current))

        state["revert"] = revert
        row.connect("notify::selected", lambda r, _p: send(choices[r.get_selected()]))
        return row
    row = Adw.ActionRow(title=title, subtitle=label)
    row.add_suffix(Gtk.Label(label=attribute["value"], css_classes=["dim-label"]))
    return row


def stat_tile(title):
    """A dashboard tile. Returns the widget and the labels to update."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["card", "stat-tile"])
    heading = Gtk.Label(label=title, xalign=0, css_classes=["dim-label", "caption-heading"])
    value = Gtk.Label(label="–", xalign=0, css_classes=["title-1"])
    detail = Gtk.Label(label="", xalign=0, wrap=True, css_classes=["dim-label", "caption"])
    box.append(heading)
    box.append(value)
    box.append(detail)
    return box, value, detail
