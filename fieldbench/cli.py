"""Command line: fieldbench run | simulate | analyze | guidance | serve"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROCEDURES_DIR = Path(__file__).resolve().parent.parent / "procedures"


def cmd_run(args) -> int:
    """Run the system test campaign with pytest."""
    import pytest

    argv = [str(PROCEDURES_DIR), f"--release={args.release}", f"--results={args.results}", "-p", "no:cacheprovider"]
    if args.k:
        argv += ["-k", args.k]
    if args.no_plots:
        argv.append("--no-plots")
    return pytest.main(argv)


def cmd_simulate(args) -> int:
    """Record one scenario (with optional faults) to BLF + ASC."""
    from .analysis import write_logs
    from .bench import simulate
    from .ecus import RELEASES
    from .spec import load_spec

    spec = load_spec(args.spec)
    faults = [json.loads(f) for f in args.fault]
    messages = simulate(spec.scenarios[args.scenario], RELEASES[args.release], faults)
    for path in write_logs(messages, args.out):
        print(f"wrote {path} ({len(messages)} frames)")
    return 0


def cmd_analyze(args) -> int:
    """Decode a Vector ASC/BLF log, list dropouts, plot signals."""
    from .analysis import dbc_cycle_times, decode, find_dropouts, message_stats, plot_signals, read_log
    from .bench import load_dbc

    db = load_dbc(args.dbc) if args.dbc else load_dbc()
    capture = decode(read_log(args.log), db)
    cycles = dbc_cycle_times(db)
    dropouts = find_dropouts(capture, cycles, args.factor)
    print(message_stats(capture, cycles).to_string(index=False))
    print(f"\nerror frames: {capture.error_frames}")
    print(f"dropouts (gap > {args.factor:g} x cycle): {len(dropouts)}")
    for d in dropouts:
        print(f"  {d.message:<16} {d.start_s:8.3f} s -> {d.end_s:8.3f} s  ({d.gap_ms:.0f} ms)")
    if args.plot:
        plot_signals(capture, args.signals, args.plot, dropouts=dropouts, title=Path(args.log).name)
        print(f"plot: {args.plot}")
    return 0


def cmd_guidance(args) -> int:
    """Cross-track error of a GNSS track (file or serial port) against an AB line."""
    from .guidance import AbLine, ab_line_from_track, evaluate_track, plot_track
    from .nmea import read_fixes, read_nmea_file, serial_lines
    from .spec import load_spec

    cfg = load_spec(args.spec).guidance
    if args.serial:
        fixes = read_fixes(serial_lines(args.serial, args.baud, args.max_lines))
    else:
        fixes = read_nmea_file(args.nmea)
    line = AbLine(*args.ab) if args.ab else ab_line_from_track(fixes, cfg["min_speed_mps"])
    result = evaluate_track(fixes, line, cfg["classes"], cfg["min_speed_mps"], cfg["max_heading_dev_deg"])
    print(f"AB line heading {line.heading_deg:.1f} deg, accuracy class {result.fix_class}")
    for key, value in result.stats.items():
        print(f"  {key:<12} {value}")
    verdict = "PASS" if result.passed else "FAIL"
    print(f"95th percentile |XTE| {result.stats['xte_p95_m']} m vs limit {result.limit_m} m: {verdict}")
    if args.plot:
        plot_track(result, args.plot)
        print(f"plot: {args.plot}")
    return 0 if result.passed or not args.strict else 1


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("fieldbench.api:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    from .spec import DEFAULT_SPEC

    parser = argparse.ArgumentParser(prog="fieldbench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the test campaign (pytest)")
    run.add_argument("--release", default="1.4.0")
    run.add_argument("--results", default="results")
    run.add_argument("-k", help="pytest -k expression, e.g. TP-GUI")
    run.add_argument("--no-plots", action="store_true")
    run.set_defaults(func=cmd_run)

    sim = sub.add_parser("simulate", help="record a scenario to BLF/ASC")
    sim.add_argument("--release", default="1.4.0")
    sim.add_argument("--scenario", default="field_pass")
    sim.add_argument(
        "--fault", action="append", default=[], help='JSON, e.g. \'{"type":"gnss_dropout","at_s":6,"duration_s":2}\''
    )
    sim.add_argument("--out", default="results/recording")
    sim.add_argument("--spec", default=str(DEFAULT_SPEC))
    sim.set_defaults(func=cmd_simulate)

    ana = sub.add_parser("analyze", help="decode an ASC/BLF log and find dropouts")
    ana.add_argument("log")
    ana.add_argument("--dbc")
    ana.add_argument("--factor", type=float, default=3.0, help="dropout = gap > factor x cycle time")
    ana.add_argument("--plot")
    ana.add_argument("--signals", nargs="+", default=["WheelBasedSpeed", "SteeringEngaged", "ExitReason", "Latitude"])
    ana.set_defaults(func=cmd_analyze)

    gui = sub.add_parser("guidance", help="cross-track error of a GNSS track vs an AB line")
    src = gui.add_mutually_exclusive_group(required=True)
    src.add_argument("--nmea", help="NMEA log file")
    src.add_argument("--serial", help="serial port of a GNSS receiver, e.g. COM5 or /dev/ttyUSB0")
    gui.add_argument("--baud", type=int, default=9600)
    gui.add_argument("--max-lines", type=int, default=3000)
    gui.add_argument("--ab", type=float, nargs=4, metavar=("A_LAT", "A_LON", "B_LAT", "B_LON"))
    gui.add_argument("--plot")
    gui.add_argument("--strict", action="store_true", help="exit 1 when the accuracy check fails")
    gui.add_argument("--spec", default=str(DEFAULT_SPEC))
    gui.set_defaults(func=cmd_guidance)

    srv = sub.add_parser("serve", help="start the web API")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
