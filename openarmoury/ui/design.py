"""The motion and layout system: spring physics, the gliding selection pill, and page structure."""
import gi

gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gsk, Gtk  # noqa: E402

# Spring tuning. The leading edge is quicker than the trailing edge, so the pill stretches as it travels
# and settles back into shape, which is what makes it feel liquid rather than simply sliding.
LEAD = Adw.SpringParams.new(0.82, 1.0, 420.0)
TRAIL = Adw.SpringParams.new(0.88, 1.0, 230.0)
PAGE = Adw.SpringParams.new(1.0, 1.0, 260.0)
GAUGE = Adw.SpringParams.new(1.0, 1.0, 90.0)
CURVE = Adw.SpringParams.new(0.86, 1.0, 170.0)
PAGE_TRAVEL = 44
MAX_SEGMENTS = 4
ACCENT = (0.04, 0.52, 1.0)


def rgba(r, g, b, a=1.0):
    # Gdk.RGBA ignores constructor arguments in GTK4's bindings, leaving it transparent.
    value = Gdk.RGBA()
    value.red, value.green, value.blue, value.alpha = r, g, b, a
    return value


def spring(widget, start, end, params, on_value, velocity=0.0, on_done=None):
    """Start a spring. Adwaita jumps to the end by itself if animations are off or the widget isn't shown."""
    animation = Adw.SpringAnimation.new(widget, start, end, params, Adw.CallbackAnimationTarget.new(on_value))
    animation.set_initial_velocity(velocity)
    animation.set_epsilon(0.0015)
    if on_done:
        animation.connect("done", lambda _a: on_done())
    animation.play()
    return animation


class Edge:
    """One edge of the pill, on its own spring. Keeps its velocity if interrupted part way."""

    def __init__(self, owner):
        self.owner = owner
        self.value = 0.0
        self.target = 0.0
        self.animation = None

    def jump(self, value):
        if self.animation:
            self.animation.pause()
            self.animation = None
        self.value = self.target = value

    def glide(self, target, params):
        if target == self.target and self.animation:
            return
        velocity = self.animation.get_velocity() if self.animation else 0.0
        if self.animation:
            self.animation.pause()
        self.target = target
        self.animation = spring(self.owner, self.value, target, params, self._step, velocity)

    def _step(self, value):
        self.value = value
        self.owner.queue_draw()


class GlidePill(Gtk.Widget):
    """The selection marker that glides behind a group of items, with a glass-like sheen."""

    def __init__(self, style="accent", radius=10):
        super().__init__(can_target=False, can_focus=False)
        self.style = style
        self.radius = radius
        self.left, self.right, self.top, self.bottom = (Edge(self) for _ in range(4))
        self.placed = False

    def do_measure(self, _orientation, _for_size):
        return 0, 0, -1, -1

    def move_to(self, x, y, width, height, animate=True):
        if not animate or not self.placed:
            for edge, value in ((self.left, x), (self.right, x + width), (self.top, y), (self.bottom, y + height)):
                edge.jump(value)
            self.placed = True
            self.queue_draw()
            return
        # Whichever edge faces the direction of travel leads.
        forward_x = x >= self.left.target
        forward_y = y >= self.top.target
        self.left.glide(x, TRAIL if forward_x else LEAD)
        self.right.glide(x + width, LEAD if forward_x else TRAIL)
        self.top.glide(y, TRAIL if forward_y else LEAD)
        self.bottom.glide(y + height, LEAD if forward_y else TRAIL)

    def do_snapshot(self, snapshot):
        if not self.placed:
            return
        x, y = self.left.value, self.top.value
        width, height = self.right.value - x, self.bottom.value - y
        if width <= 1 or height <= 1:
            return
        dark = Adw.StyleManager.get_default().get_dark()
        if self.style == "accent":
            fill = rgba(*ACCENT)
            sheen = 0.22
            shadow = rgba(*ACCENT, 0.42)
            blur = 14
        else:
            fill = rgba(1, 1, 1, 0.16) if dark else rgba(1, 1, 1, 1)
            sheen = 0.10 if dark else 0.0
            shadow = rgba(0, 0, 0, 0.32 if dark else 0.16)
            blur = 5
        bounds = Graphene.Rect().init(x, y, width, height)
        outline = Gsk.RoundedRect()
        outline.init_from_rect(bounds, min(self.radius, height / 2, width / 2))
        snapshot.append_outset_shadow(outline, shadow, 0, 2, 0, blur)
        snapshot.push_rounded_clip(outline)
        snapshot.append_color(fill, bounds)
        if sheen:
            stops = [Gsk.ColorStop(), Gsk.ColorStop()]
            stops[0].offset, stops[0].color = 0.0, rgba(1, 1, 1, sheen)
            stops[1].offset, stops[1].color = 0.55, rgba(1, 1, 1, 0.0)
            snapshot.append_linear_gradient(bounds, Graphene.Point().init(x, y), Graphene.Point().init(x, y + height), stops)
        snapshot.pop()


class GlideGroup(Gtk.Overlay):
    """Lays a pill behind content, and glides it to whichever item is selected."""

    def __init__(self, content, style="accent", radius=10):
        super().__init__()
        self.pill = GlidePill(style, radius)
        self.content = content
        self.selected_widget = None
        self.last_size = (0, 0)
        self.set_child(self.pill)
        self.add_overlay(content)
        self.set_measure_overlay(content, True)
        self.add_tick_callback(self._watch_size)

    def _watch_size(self, _widget, _clock):
        """Layout changes, such as resizing the window, move the pill without animating."""
        size = (self.get_width(), self.get_height())
        if size != self.last_size and size[0] > 0:
            self.last_size = size
            self.select(self.selected_widget, animate=False)
        return GLib.SOURCE_CONTINUE

    def select(self, widget, animate=True):
        self.selected_widget = widget
        if widget is None or self.get_width() == 0:
            return
        ok, bounds = widget.compute_bounds(self)
        if ok:
            self.pill.move_to(bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height(), animate)


class SegmentedRow(Adw.ActionRow):
    """A row with a segmented control. Same methods as a combo row, so the two swap freely."""

    selected = GObject.Property(type=int, default=0)

    def __init__(self, title, labels, selected=0, subtitle=None):
        super().__init__(title=title)
        if subtitle:
            self.set_subtitle(subtitle)
        self.labels = []
        self.buttons = []
        self.box = Gtk.Box(css_classes=["segments"], homogeneous=True)
        self.group = GlideGroup(self.box, "neutral", 7)
        holder = Gtk.Box(css_classes=["segmented"], valign=Gtk.Align.CENTER)
        holder.append(self.group)
        self.add_suffix(holder)
        self.set_options(labels)
        self.set_selected(selected)

    def set_options(self, labels):
        for button in self.buttons:
            self.box.remove(button)
        self.labels = list(labels)
        self.buttons = []
        leader = None
        for index, label in enumerate(self.labels):
            button = Gtk.ToggleButton(label=label, group=leader, css_classes=["segment"])
            leader = leader or button
            button.connect("toggled", self._toggled, index)
            self.box.append(button)
            self.buttons.append(button)

    def set_model(self, model):
        self.set_options([model.get_string(i) for i in range(model.get_n_items())])
        self.set_selected(0)

    def _toggled(self, button, index):
        if button.get_active():
            self.group.select(button)
            self.props.selected = index

    def get_selected(self):
        return self.props.selected

    def set_selected(self, index):
        if 0 <= index < len(self.buttons):
            self.buttons[index].set_active(True)
            self.props.selected = index


def choice_row(title, labels, selected=0, subtitle=None):
    """A segmented control for a few short choices, otherwise a menu."""
    if len(labels) <= MAX_SEGMENTS and sum(len(label) for label in labels) <= 34:
        return SegmentedRow(title, labels, selected, subtitle)
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(list(labels)))
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_selected(selected)
    return row


class GlideStack(Gtk.Widget):
    """Pages that glide in the direction you moved, driven by a spring, without re-rendering their contents."""

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, overflow=Gtk.Overflow.HIDDEN)
        self.children = {}
        self.order = []
        self.visible_name = None
        self.leaving = None
        self.direction = 1
        self.progress = 1.0
        self.animation = None

    def add_named(self, child, name):
        child.set_parent(self)
        child.set_child_visible(False)
        self.children[name] = child
        self.order.append(name)
        if self.visible_name is None:
            self.visible_name = name
            child.set_child_visible(True)

    def set_visible_child_name(self, name):
        if name == self.visible_name:
            return
        if self.animation:
            self.animation.pause()
            self._finished()
        self.direction = 1 if self.order.index(name) > self.order.index(self.visible_name) else -1
        self.leaving = self.visible_name
        self.visible_name = name
        self.children[name].set_child_visible(True)
        self.queue_allocate()
        self.progress = 0.0
        self.animation = spring(self, 0.0, 1.0, PAGE, self._step, on_done=self._finished)

    def _step(self, value):
        self.progress = value
        self.queue_draw()

    def _finished(self):
        self.animation = None
        self.progress = 1.0
        if self.leaving:
            self.children[self.leaving].set_child_visible(False)
            self.leaving = None
        self.queue_draw()

    def do_measure(self, orientation, for_size):
        sizes = [child.measure(orientation, for_size)[:2] for child in self.children.values()]
        return max((s[0] for s in sizes), default=0), max((s[1] for s in sizes), default=0), -1, -1

    def do_size_allocate(self, width, height, baseline):
        for child in self.children.values():
            child.allocate(width, height, baseline, None)

    def _paint(self, snapshot, child, offset, opacity):
        snapshot.save()
        snapshot.translate(Graphene.Point().init(0, offset))
        snapshot.push_opacity(max(0.0, min(1.0, opacity)))
        self.snapshot_child(child, snapshot)
        snapshot.pop()
        snapshot.restore()

    def do_snapshot(self, snapshot):
        current = self.children.get(self.visible_name)
        if not current:
            return
        if not self.leaving:
            self.snapshot_child(current, snapshot)
            return
        progress = self.progress
        self._paint(snapshot, self.children[self.leaving], -self.direction * PAGE_TRAVEL * progress * 0.5, 1 - progress * 1.6)
        self._paint(snapshot, current, self.direction * PAGE_TRAVEL * (1 - progress), progress)


def icon_badge(icon, colour, size=28):
    """A coloured rounded square behind a white icon."""
    box = Gtk.CenterBox(css_classes=["badge", f"badge-{colour}"], halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=False)
    box.set_size_request(size, size)
    image = Gtk.Image(icon_name=icon, pixel_size=int(size * 0.58))
    image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    box.set_center_widget(image)
    return box


def large_title(title, subtitle=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_bottom=2)
    box.append(Gtk.Label(label=title, xalign=0, wrap=True, css_classes=["home-title"]))
    if subtitle:
        box.append(Gtk.Label(label=subtitle, xalign=0, wrap=True, css_classes=["page-subtitle"]))
    return box


def new_page(title, subtitle=None):
    """A settings page: a wider column with a large title at the top."""
    page = Adw.PreferencesPage(css_classes=["designed-page"])
    heading = Adw.PreferencesGroup()
    heading.add(large_title(title, subtitle))
    page.add(heading)
    for child in descendants(page):
        if isinstance(child, Adw.Clamp):
            child.set_maximum_size(780)
            child.set_tightening_threshold(620)
    return page


def descendants(widget):
    child = widget.get_first_child()
    while child:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def decorate_rows(widget, icons):
    """Give known settings rows their icon, so pages stay simple and every row is consistent."""
    for child in descendants(widget):
        if isinstance(child, (Adw.ActionRow, Adw.EntryRow)) and not getattr(child, "decorated", False):
            found = icons.get(child.get_title())
            if found:
                child.add_prefix(icon_badge(*found))
                child.decorated = True
