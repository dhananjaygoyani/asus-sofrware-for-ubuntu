"""All writes to hardware go through here, on to the root helper or a hidraw node we may open."""
import fcntl
import json
import os
import pathlib
import subprocess
import threading

INSTALLED_HELPER = "/usr/libexec/openarmoury/openarmoury-helper"
DEV_HELPER = pathlib.Path(__file__).resolve().parent.parent / "helper" / "openarmoury-helper"


class WriteError(Exception):
    pass


class Helper:
    """One helper process per session. pkexec asks for the password when it first starts."""

    def __init__(self, test_root=None):
        self.test_root = test_root
        self.process = None
        self.lock = threading.Lock()

    def _start(self):
        if self.test_root:
            env = {**os.environ, "OPENARMOURY_TEST_ROOT": self.test_root}
            command = [str(DEV_HELPER)]
        else:
            if not os.path.exists(INSTALLED_HELPER):
                raise WriteError("OpenArmoury isn't installed. Run install.sh to enable writing to hardware.")
            env = None
            command = ["pkexec", INSTALLED_HELPER]
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=env
        )

    def request(self, **request):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()
            try:
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
                line = self.process.stdout.readline()
            except (BrokenPipeError, OSError) as err:
                self.process = None
                raise WriteError(f"Helper stopped: {err}") from err
            if not line:
                self.process = None
                raise WriteError("Permission was refused, or the helper stopped.")
            reply = json.loads(line)
            if not reply.get("ok"):
                raise WriteError(reply.get("error", "Helper refused the request"))
            return reply

    def close(self):
        with self.lock:
            if self.process:
                self.process.stdin.close()
                self.process.wait(timeout=2)
                self.process = None


def _hidraw_ioc(nr, size):
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


class Writer:
    def __init__(self, helper, root=""):
        self.helper = helper
        self.root = root

    def write(self, path, value):
        self.helper.request(op="write", path=path, value=str(value))

    def _open_direct(self, node):
        """Use the node directly if the udev rule allows it, so lighting needs no password."""
        if self.root:
            return None
        try:
            return os.open(f"/dev/{node}", os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            return None

    def hid(self, node, kind, packet):
        fd = self._open_direct(node)
        if fd is None:
            self.helper.request(op="hid", node=node, kind=kind, data=packet.hex())
            return
        try:
            if kind == "output":
                os.write(fd, packet)
            else:
                fcntl.ioctl(fd, _hidraw_ioc(0x06, len(packet)), bytearray(packet))
        except OSError as err:
            raise WriteError(f"Keyboard write failed: {err}") from err
        finally:
            os.close(fd)

    def get_feature(self, node, report_id, length):
        fd = self._open_direct(node)
        if fd is None:
            reply = self.helper.request(op="get_feature", node=node, report_id=report_id, length=length)
            return bytes.fromhex(reply["data"])
        try:
            buffer = bytearray(length)
            buffer[0] = report_id
            fcntl.ioctl(fd, _hidraw_ioc(0x07, length), buffer)
            return bytes(buffer)
        except OSError as err:
            raise WriteError(f"Keyboard read failed: {err}") from err
        finally:
            os.close(fd)
