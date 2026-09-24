#!/usr/bin/env python3
"""Convert MiniSEED files into a SeisComP Data Structure (SDS) archive.

The output layout is:
  YEAR/NET/STA/CHAN.D/NET.STA.LOC.CHAN.D.YEAR.JDAY

Data are split at UTC day boundaries and overlapping input segments are merged.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from obspy import Stream, UTCDateTime, read


DEFAULT_PATTERNS = ("*.miniseed", "*.mseed", "*.msd", "*.seed")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path,
                        help=("MiniSEED file or folder (overrides config; "
                              "default: config input or current folder)"))
    parser.add_argument("output", nargs="?", type=Path, default=Path("SDS"),
                        help="SDS root folder (default: ./SDS)")
    parser.add_argument("--config", type=Path, default=Path("sds_config.json"),
                        help="header configuration (default: ./sds_config.json)")
    parser.add_argument("--recursive", action="store_true",
                        help="also find MiniSEED in input subfolders")
    parser.add_argument("--network", help="override network code")
    parser.add_argument("--station", help="override station code")
    parser.add_argument("--location", help="override location code; use --location '' for blank")
    parser.add_argument("--channel-prefix",
                        help="replace the first two channel characters, e.g. HH")
    parser.add_argument("--record-length", type=int, default=4096,
                        choices=(256, 512, 1024, 2048, 4096, 8192, 16384),
                        help="output MiniSEED record length (default: 4096)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read headers and show destinations without writing")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace existing SDS day files; otherwise merge with them")
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> None:
    """Load input path and header defaults; command-line values win."""
    args.channel_map = {}
    if not args.config.exists():
        print(f"Config not found, retaining input headers: {args.config}")
        return
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read config {args.config}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("config root must be a JSON object")

    config_input = config.get("input")
    if args.input is None and config_input is not None:
        if not isinstance(config_input, str) or not config_input.strip():
            raise ValueError("config value 'input' must be a non-empty string")
        configured_path = Path(config_input).expanduser()
        if not configured_path.is_absolute():
            configured_path = args.config.resolve().parent / configured_path
        args.input = configured_path

    for name in ("network", "station", "location", "channel_prefix"):
        value = config.get(name)
        if getattr(args, name) is None and value is not None:
            if not isinstance(value, str):
                raise ValueError(f"config value {name!r} must be a string or null")
            setattr(args, name, value)

    channel_map = config.get("channel_map", {})
    if not isinstance(channel_map, dict) or not all(
            isinstance(old, str) and isinstance(new, str)
            for old, new in channel_map.items()):
        raise ValueError("config value 'channel_map' must be an object of strings")
    args.channel_map = channel_map


def validate_seed_code(name: str, value: str, max_length: int) -> None:
    if len(value) > max_length or any(char.isspace() or char == "." for char in value):
        raise ValueError(
            f"invalid {name} code {value!r}: maximum {max_length} characters, "
            "without spaces or dots")


def input_files(source: Path, recursive: bool, output: Path) -> list[Path]:
    if source.is_file():
        return [source.resolve()]

    folder = source
    iterator = folder.rglob if recursive else folder.glob
    found = {p.resolve() for pattern in DEFAULT_PATTERNS for p in iterator(pattern)}
    output = output.resolve()
    return sorted(p for p in found if output not in p.parents)


def apply_overrides(trace, args: argparse.Namespace) -> None:
    if args.network is not None:
        trace.stats.network = args.network
    if args.station is not None:
        trace.stats.station = args.station
    if args.location is not None:
        trace.stats.location = args.location
    trace.stats.channel = args.channel_map.get(
        trace.stats.channel, trace.stats.channel)
    if args.channel_prefix is not None:
        if len(args.channel_prefix) != 2:
            raise ValueError("--channel-prefix must contain exactly two characters")
        trace.stats.channel = args.channel_prefix + trace.stats.channel[-1:]
    validate_seed_code("network", trace.stats.network, 2)
    validate_seed_code("station", trace.stats.station, 5)
    validate_seed_code("location", trace.stats.location, 2)
    validate_seed_code("channel", trace.stats.channel, 3)


def sds_relative_path(trace, day: UTCDateTime) -> Path:
    net = trace.stats.network or ""
    sta = trace.stats.station or ""
    loc = trace.stats.location or ""
    cha = trace.stats.channel or ""
    year, jday = day.year, day.julday
    filename = f"{net}.{sta}.{loc}.{cha}.D.{year}.{jday:03d}"
    return Path(str(year), net, sta, f"{cha}.D", filename)


def daily_pieces(trace):
    """Yield (UTC day, trace piece), with no sample duplicated across days."""
    day = UTCDateTime(trace.stats.starttime.date)
    delta = trace.stats.delta
    while day <= trace.stats.endtime:
        next_day = day + 86400
        piece = trace.slice(max(trace.stats.starttime, day),
                            min(trace.stats.endtime, next_day - delta),
                            nearest_sample=False)
        if piece.stats.npts:
            yield day, piece
        day = next_day


def covered_days(trace):
    """Yield every UTC calendar day touched by a trace header."""
    day = UTCDateTime(trace.stats.starttime.date)
    while day <= trace.stats.endtime:
        yield day
        day += 86400


def main() -> int:
    args = arguments()
    try:
        load_config(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    source = (args.input or Path.cwd()).resolve()
    output = args.output.resolve()
    if not source.exists() or not (source.is_file() or source.is_dir()):
        print(f"ERROR: input file/folder does not exist: {source}", file=sys.stderr)
        return 2

    files = input_files(source, args.recursive, output)
    if not files:
        print(f"No MiniSEED files found at {source}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} input files")
    if args.dry_run:
        destinations = set()
        for path in files:
            for trace in read(str(path), headonly=True):
                apply_overrides(trace, args)
                for day in covered_days(trace):
                    destinations.add(sds_relative_path(trace, day))
        for destination in sorted(destinations):
            print(destination)
        print(f"Dry run: {len(destinations)} SDS day files")
        return 0

    output.mkdir(parents=True, exist_ok=True)
    fragments: dict[Path, list[Path]] = defaultdict(list)
    temp_root = Path(tempfile.mkdtemp(prefix="mseed_to_sds_", dir=output))
    try:
        print("Splitting input at UTC day boundaries ...")
        sequence = 0
        for number, path in enumerate(files, 1):
            try:
                stream = read(str(path))
                for trace in stream:
                    apply_overrides(trace, args)
                    for day, piece in daily_pieces(trace):
                        relative = sds_relative_path(piece, day)
                        fragment = temp_root / f"{sequence:08d}.mseed"
                        piece.write(str(fragment), format="MSEED",
                                    reclen=args.record_length, encoding="STEIM2")
                        fragments[relative].append(fragment)
                        sequence += 1
            except Exception as exc:
                raise RuntimeError(f"failed to read {path.name}: {exc}") from exc
            print(f"  [{number}/{len(files)}] {path.name}")

        print("Merging and writing SDS day files ...")
        for number, relative in enumerate(sorted(fragments), 1):
            destination = output / relative
            combined = Stream()
            if destination.exists() and not args.overwrite:
                combined += read(str(destination))
            for fragment in fragments[relative]:
                combined += read(str(fragment))

            # method=1 resolves overlaps; identical duplicate data are collapsed.
            # Gaps become masked sections. Split them back into ordinary Trace
            # objects because MiniSEED intentionally has no representation for
            # a masked/missing sample.
            combined.merge(method=1, fill_value=None, interpolation_samples=0)
            combined = combined.split()
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged = temp_root / f"output_{number:05d}.mseed"
            combined.write(str(staged), format="MSEED",
                           reclen=args.record_length, encoding="STEIM2")
            staged.replace(destination)
            print(f"  [{number}/{len(fragments)}] {relative}")

        print(f"Done: {len(fragments)} SDS day files in {output}")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
