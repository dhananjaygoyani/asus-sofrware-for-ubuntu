"""Command line entry point."""
import argparse
import signal
import sys
import tempfile

from . import __version__


def main():
    parser = argparse.ArgumentParser(prog="openarmoury", description="Laptop control for ASUS machines on Linux.")
    parser.add_argument("--demo", action="store_true", help="run against a simulated laptop, touching no hardware")
    parser.add_argument("--restore", action="store_true", help="re-apply saved settings, then exit")
    parser.add_argument("--background", action="store_true", help="re-apply saved settings and run with no window")
    parser.add_argument("--macro", metavar="NAME", help="play a saved macro, then exit")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    if args.restore or args.background:
        from .restore import run

        status = run()
        if args.restore:
            return status
    if args.macro:
        from .restore import play_macro

        return play_macro(args.macro)

    from .ui.app import App, build_context

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if args.demo:
        from . import demo

        with tempfile.TemporaryDirectory(prefix="openarmoury-demo-") as root:
            demo.build(root)
            # A throwaway config, so demo clicks can't change what's saved for the real laptop.
            ctx = build_context(demo_root=root, config_dir=root + "/config")
            return App(ctx).run([])
    return App(build_context(), start_hidden=args.background).run([])


if __name__ == "__main__":
    sys.exit(main())
