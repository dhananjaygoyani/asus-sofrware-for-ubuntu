"""Shared app state, and the gate every hardware write passes through."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from gi.repository import Adw, GLib, Gtk

from .. import audio, effects, hid, keyboard, monitor, packets, system
from ..writer import WriteError


@dataclass
class Op:
    """One hardware action, described exactly as the confirmation dialog shows it."""

    key: str  # approval category
    where: str
    what: str
    call: Callable
    uncertain: Optional[str] = None


class FakeMeter:
    """Sound level for demo mode, so it doesn't listen to your real audio."""

    level = 0.0

    def available(self):
        return True

    def start(self):
        pass

    def stop(self):
        pass


class Context:
    def __init__(self, hw, config, helper, writer, desktop, demo_root=None):
        self.desktop = desktop
        self.monitor = monitor.Monitor(hw)
        self.meter = FakeMeter() if demo_root else audio.MusicMeter()
        self.hw = hw
        self.config = config
        self.helper = helper
        self.writer = writer
        self.demo_root = demo_root
        self.window = None
        self.toasts = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.board = self._make_board()
        self.board_listeners = []
        self.live_effect = None
        self.live_listeners = []
        self.frame_busy = False
        self.limiter = effects.RateLimiter()
        self.save_source = None

    @property
    def is_demo(self):
        return self.demo_root is not None

    def _make_board(self):
        interfaces = self.hw.hidraw_keyboards()
        interface = interfaces[0] if interfaces else None
        identity = self.hw.identity()
        support = keyboard.match_support(identity["board"], interface["product"] if interface else "")
        return keyboard.Keyboard(interface, self.config["capabilities"], support, self.hw.has_tuf_rgb())

    def refresh_board(self):
        self.board = self._make_board()
        for listener in self.board_listeners:
            listener()

    def effect_input(self, effect):
        """The sensor reading an effect follows."""
        source = effect.get("source", "cpu_temp")
        if source == "cpu_load":
            return self.monitor.cpu_percent
        if source == "igpu_temp":
            return self.hw.igpu_temp()
        if source == "dgpu_temp":
            return (self.monitor.gpu_stats or {}).get("temperature")
        if source == "battery":
            battery = self.hw.battery()
            return battery["capacity"] if battery else None
        cached = self.monitor.temperature_cache
        return cached if cached is not None else self.hw.cpu_temp()

    def render(self, effect, now):
        return effects.render(effect, self.board.light_keys(), now, self.effect_input(effect), self.meter.level)

    def save_soon(self):
        """Save settings shortly after the last change, so dragging a control never waits on the disk."""
        if self.save_source:
            GLib.source_remove(self.save_source)

        def save():
            self.save_source = None
            self.config.save()
            return False

        self.save_source = GLib.timeout_add(400, save)

    def toast(self, message):
        if self.toasts:
            self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message)))

    # Building operations

    def write_op(self, key, path, value, uncertain=None):
        return Op(key, path, str(value), lambda: self.writer.write(path, value), uncertain)

    def hid_op(self, key, packet, uncertain=None, kind=None):
        interface = self.board.interface
        kind = kind or interface["transport"][0]
        node = interface["node"]
        return Op(
            key,
            f"/dev/{node} ({kind} report)",
            packet.hex(" "),
            lambda: self.writer.hid(node, kind, packet),
            uncertain,
        )

    # The gate

    def is_approved(self, op):
        return op.key in self.config["approved"]

    def submit(self, ops, done=None, warning=None, before=None):
        """Show exactly what will be written the first time, then run it off the UI thread.

        before runs only once the change is really going ahead, not if you cancel.
        """
        pending = [] if self.is_demo else [op for op in ops if not self.is_approved(op)]
        if not pending and not warning:
            self._run(ops, done, before)
            return
        self._confirm(ops, pending, warning, done, before)

    def _confirm(self, ops, pending, warning, done, before):
        dialog = Adw.AlertDialog(heading="Write to your laptop?" if pending else "Are you sure?")
        lines = []
        reasons = sorted({op.uncertain for op in pending if op.uncertain})
        if warning:
            lines.append(warning)
        if reasons:
            lines.append("Unverified, so it may not behave as expected:\n" + "\n".join(f"• {r}" for r in reasons))
        if pending:
            lines.append("This is the first time for this kind of change, so here is exactly what will be sent:")
        dialog.set_body("\n\n".join(lines))
        if pending:
            text = Gtk.Label(
                label="\n".join(f"{op.where}\n    {op.what}" for op in ops),
                selectable=True,
                xalign=0,
                wrap=True,
                wrap_mode=2,
            )
            text.add_css_class("monospace")
            scroller = Gtk.ScrolledWindow(child=text, min_content_height=160, max_content_height=320)
            scroller.set_propagate_natural_height(True)
            dialog.set_extra_child(scroller)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("write", "Write")
        dialog.set_response_appearance("write", Adw.ResponseAppearance.DESTRUCTIVE if warning or reasons else Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            if response != "write":
                if done:
                    done(False)
                return
            approved = self.config["approved"]
            for op in pending:
                if op.key not in approved:
                    approved.append(op.key)
            self.config.save()
            self._run(ops, done, before)

        dialog.connect("response", respond)
        dialog.present(self.window)

    def _send(self, ops, finished):
        """Run operations off the UI thread, then call finished(error) back on it."""

        def work():
            try:
                for op in ops:
                    op.call()
                return None
            except (WriteError, OSError) as err:
                return str(err)

        self.executor.submit(work).add_done_callback(lambda future: GLib.idle_add(finished, future.result()))

    def _run(self, ops, done, before=None):
        if before:
            before()
        self._send(ops, lambda error: self._finish(error, done))

    def _finish(self, error, done):
        if error:
            self.toast(error)
        if done:
            done(error is None)
        return False

    # Live colour. Direct packets only, capped by the rate limiter.

    def start_live(self, effect, done=None):
        """Stream a software effect. The first frame goes through the gate."""
        board = self.board
        if not board.can_color:
            self.toast("This keyboard only supports brightness.")
            return
        frame = self.render(effect, 0.0)
        ops = self._frame_ops(frame, first=True, uncertain=board.uncertain_reason("direct"))

        def started(ok):
            if ok:
                self.live_effect = effect
            if done:
                done(ok)

        self.submit(ops, started)

    def stop_live(self):
        self.live_effect = None
        for listener in self.live_listeners:
            listener()

    def _frame_ops(self, frame, first=False, uncertain=None):
        board = self.board
        if board.kind == "single":
            colours = [[sum(c[i] for c in frame.values()) / max(1, len(frame)) for i in range(3)]]
            value = packets.tuf_rgb_mode("Static", colours[0])
            return [self.write_op("direct", f"{system.LED}/kbd_rgb_mode", value, uncertain)]
        ops = []
        length = board.interface["transport"][1]
        if first:
            ops.append(self.hid_op("direct", packets.direct_init(board.direct_init_byte(), length), uncertain))
        for packet in board.frame_to_packets(frame):
            assert packets.is_live_safe(packet)
            ops.append(self.hid_op("direct", packet, uncertain))
        return ops

    def tick_live(self, now):
        """Called by the app timer. Drops the frame if the last is still sending, or if it's too soon."""
        if not self.live_effect or self.frame_busy or not self.limiter.allow(now):
            return
        frame = self.render(self.live_effect, now)
        self.frame_busy = True
        self._send(self._frame_ops(frame), self._frame_done)

    def _frame_done(self, error):
        self.frame_busy = False
        if error:
            self.stop_live()
            self.toast(f"Live lighting stopped: {error}")
        return False

    # Asking the keyboard what it is

    def detect_keyboard(self, done=None):
        interface = self.board.interface
        if not interface or not interface["report"].feature:
            self.toast("This keyboard has no feature report to ask.")
            return
        length = interface["report"].feature + 1
        magic, ask = hid.handshake_packets(length, self.hw.identity()["board"])
        node = interface["node"]
        reply = {}

        def read_reply():
            reply["data"] = self.writer.get_feature(node, hid.LIGHTING_REPORT, length)

        ops = [
            self.hid_op("detect", magic, kind="feature"),
            Op("detect", f"/dev/{node} (read feature report)", "no data sent", lambda: self.writer.get_feature(node, hid.LIGHTING_REPORT, length)),
            self.hid_op("detect", ask, kind="feature"),
            Op("detect", f"/dev/{node} (read feature report)", "no data sent", read_reply),
        ]

        def finished(ok):
            capabilities = hid.parse_capabilities(reply.get("data", b"")) if ok else None
            if capabilities:
                self.config["capabilities"] = capabilities
                self.refresh_board()
                self.toast("The keyboard described itself.")
            elif ok:
                self.toast("The keyboard didn't answer, so settings stay conservative.")
            if done:
                done(capabilities)

        self.submit(ops, finished)

    def close(self):
        if self.save_source:
            GLib.source_remove(self.save_source)
            self.save_source = None
        self.config.save()
        self.stop_live()
        self.meter.stop()
        self.executor.shutdown(wait=True)
        self.helper.close()

