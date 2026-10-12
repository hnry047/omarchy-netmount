#!/usr/bin/python3
"""Line coverage of src/ for the safe test suite, using only the stdlib.

Uses sys.monitoring (Python 3.12+), so no third-party coverage package is
needed. Run from tests/:  /usr/bin/python3 run_coverage.py [--min 89] [--all]
"""

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
SAFE = [
    "test_core",
    "test_app",
    "test_ui",
    "test_theme",
    "test_toggle",
    "test_geometry",
    "test_widgets",
    "test_keyring",
    "test_form",
    "test_single",
    "test_window",
    "test_status",
    "test_install",
]
# Nothing is excluded; nas_app.main() itself runs only in the live tests.
EXCLUDED = set()


def executable_lines(path):
    """Line numbers that hold bytecode, from every code object in the file."""
    lines, stack = set(), [compile(path.read_text(), str(path), "exec")]
    while stack:
        code = stack.pop()
        lines.update(line for _, _, line in code.co_lines() if line)
        stack.extend(c for c in code.co_consts if hasattr(c, "co_lines"))
    return lines


def main(argv):
    minimum = float(argv[argv.index("--min") + 1]) if "--min" in argv else None
    sys.path.insert(0, str(SRC))
    hits = {}
    mon = sys.monitoring
    tool = mon.COVERAGE_ID
    mon.use_tool_id(tool, "nas-coverage")

    def on_line(code, line):
        hits.setdefault(code.co_filename, set()).add(line)
        return mon.DISABLE  # each line only needs to be seen once

    mon.register_callback(tool, mon.events.LINE, on_line)
    mon.set_events(tool, mon.events.LINE)
    try:
        suite = unittest.defaultTestLoader.loadTestsFromNames(SAFE)
        result = unittest.TextTestRunner(verbosity=0).run(suite)
    finally:
        mon.set_events(tool, 0)
        mon.free_tool_id(tool)

    total_run = total_lines = 0
    print(f"\n{'file':<18}{'lines':>7}{'run':>7}{'cover':>8}  missing")
    for path in sorted(p for p in SRC.glob("*.py") if p.name not in EXCLUDED):
        lines = executable_lines(path)
        run = lines & hits.get(str(path), set())
        missing = sorted(lines - run)
        total_lines, total_run = total_lines + len(lines), total_run + len(run)
        limit = None if "--all" in argv else 12
        shown = ",".join(map(str, missing[:limit]))
        shown += " …" if limit and len(missing) > limit else ""
        print(
            f"{path.name:<18}{len(lines):>7}{len(run):>7}"
            f"{100 * len(run) / len(lines):>7.1f}%  {shown}"
        )
    percent = 100 * total_run / total_lines
    print(f"{'TOTAL':<18}{total_lines:>7}{total_run:>7}{percent:>7.1f}%")
    if not result.wasSuccessful():
        return 1
    if minimum is not None and percent < minimum:
        print(f"Coverage {percent:.1f}% is below the {minimum:.0f}% minimum.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
