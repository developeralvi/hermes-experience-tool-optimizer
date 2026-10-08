"""EBTTO CLI — the ``hermes experience`` subcommands.

The plugin registers this as a Hermes CLI command. Every command exposes:

* ``--help``
* predictable exit code (0 on success; nonzero on user error)
* JSON output via ``--json``

Only the plugin-registered command surface is defined here. All heavy logic
(live benchmark, trajectory replay, DB->learning pipeline) lives in the core
modules and benchmark suite.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes experience",
                                     description="EBTTO experience management")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable JSON output")
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")

    # status
    p = sub.add_parser("status", help="show status")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # stats
    p = sub.add_parser("stats", help="show stats")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # tools
    p = sub.add_parser("tools", help="tool reliability")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # tasks
    p = sub.add_parser("tasks", help="task list")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # patterns
    p = sub.add_parser("patterns", help="pattern list")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # strategies
    p = sub.add_parser("strategies", help="strategy list")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # failures
    p = sub.add_parser("failures", help="failure list")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # regressions
    p = sub.add_parser("regressions", help="regression list")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # trajectory
    p = sub.add_parser("trajectory", help="trajectory dump")
    p.add_argument("task_id", nargs="?", help="task_id to dump")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # benchmark
    p = sub.add_parser("benchmark", help="benchmark run")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # mode
    p = sub.add_parser("mode", help="set mode")
    p.add_argument("mode", nargs="?", help="OFF|RECORD_ONLY|SHADOW|ADVISORY|GUARDED|CONTROLLED_AUTO")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # doctor
    p = sub.add_parser("doctor", help="health check")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    # enable / disable
    p = sub.add_parser("enable", help="enable")
    p = sub.add_parser("disable", help="disable")
    p = sub.add_parser("on", help="alias for enable")
    p = sub.add_parser("off", help="alias for disable")

    args = parser.parse_args(argv)
    cmd = args.cmd or "help"
    if args.json and cmd in ("status", "stats", "tools", "tasks", "patterns",
                              "strategies", "failures", "regressions",
                              "trajectory", "benchmark", "doctor", "mode",
                              "enable", "disable", "on", "off"):
        # JSON mode: print object and exit nonzero on error
        pass
    # ---- dispatch to plugin methods ----
    # Examples below assume access to an ebtto plugin instance with:
    #   store: hermes_ebtto.storage.Store
    #   mode: str
    # In the real Hermes plugin, these are bound in `register()`.
    print(json.dumps({"error": "EBTTO CLI invoked without a running plugin instance.",
                      "note": "This module is included for documentation purposes. "
                              "The real command surface is registered in "
                              "hermes_ebtto.plugins.EBTTOPlugin._register_commands."},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
