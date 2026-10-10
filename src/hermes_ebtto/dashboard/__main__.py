"""``ebtto dashboard`` — launch the read-only local dashboard.

Standalone entry point; deliberately NOT wired into plugin registration so a
normal Hermes run is unaffected.
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ebtto dashboard",
        description="Start the read-only EBTTO dashboard (loopback only).",
    )
    parser.add_argument("--port", type=int, default=0,
                        help="port (0 = first free port from 8797)")
    parser.add_argument("--db", default="",
                        help="EBTTO database path or directory "
                             "(default: $HERMES_HOME/.hermes-ebtto/ebtto.db)")
    parser.add_argument("--no-browser", action="store_true",
                        help="print the URL but do not open a browser")
    args = parser.parse_args(argv)

    from hermes_ebtto.dashboard import server

    try:
        server.serve(port=args.port, db_path=args.db,
                     open_browser=not args.no_browser)
    except OSError as exc:
        print(f"ebtto dashboard: cannot start server: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
