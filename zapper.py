"""NFS: HPR memory monitor. Beta 0.1.0b1 never sends hardware commands."""

import argparse
import csv
import math
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__version__ = "0.1.0b1"
DEFAULT_OFFSETS = (0x125F68, 0x239C0, 0x85C0)


@dataclass(frozen=True)
class Sample:
    value: int | float
    delta: int | float | None
    status: str


class ChangeDetector:
    """Mark candidate changes; the meaning of the memory value is unverified."""

    def __init__(self, threshold=100000, direction="increase"):
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("Threshold must be finite and greater than zero.")
        if direction not in ("increase", "decrease"):
            raise ValueError("Direction must be increase or decrease.")
        self.threshold = threshold
        self.direction = direction
        self.previous = None

    def update(self, value):
        if not math.isfinite(value) or value <= 0:
            self.previous = None
            return Sample(value, None, "reset")
        previous, self.previous = self.previous, value
        if previous is None:
            return Sample(value, None, "baseline")
        delta = value - previous
        change = delta if self.direction == "increase" else -delta
        status = "candidate" if change > self.threshold else "sample"
        return Sample(value, delta, status)


def read_value(memory, base_address, offsets, pointer_bits=32, value_type="int"):
    """Follow the original pointer chain using unsigned pointer reads."""
    if not offsets:
        raise ValueError("At least one offset is required.")
    if pointer_bits not in (32, 64):
        raise ValueError("Pointer width must be 32 or 64.")
    if value_type not in ("int", "float"):
        raise ValueError("Value type must be int or float.")
    read_pointer = memory.read_uint if pointer_bits == 32 else memory.read_ulonglong
    address = read_pointer(base_address)
    if not address:
        raise ValueError("Null pointer at the base address.")
    for offset in offsets[:-1]:
        address = read_pointer(address + offset)
        if not address:
            raise ValueError("Null pointer in the pointer chain.")
    reader = memory.read_int if value_type == "int" else memory.read_float
    return reader(address + offsets[-1])


def positive_number(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("Must be finite and greater than zero.")
    return value


def address_number(text):
    value = int(text, 0)
    if value < 0:
        raise argparse.ArgumentTypeError("Address offsets cannot be negative.")
    return value


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--demo", action="store_true", help="Run synthetic readings without the game.")
    parser.add_argument("--process", default="NFS11Remastered.exe")
    parser.add_argument("--base-offset", type=address_number, default=0x12AF050)
    parser.add_argument("--offsets", type=address_number, nargs="+", default=DEFAULT_OFFSETS)
    parser.add_argument("--pointer-bits", type=int, choices=(32, 64), default=32)
    parser.add_argument("--value-type", choices=("int", "float"), default="int")
    parser.add_argument("--direction", choices=("increase", "decrease"), default="increase")
    parser.add_argument("--threshold", type=positive_number, default=100000)
    parser.add_argument("--interval", type=positive_number, default=0.5, help="Seconds between readings.")
    parser.add_argument("--csv", type=Path, help="Write a new CSV file; existing files are never overwritten.")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    detector = ChangeDetector(args.threshold, args.direction)
    try:
        with ExitStack() as stack:
            writer = None
            if args.csv:
                args.csv.parent.mkdir(parents=True, exist_ok=True)
                csv_file = stack.enter_context(args.csv.open("x", newline="", encoding="utf-8"))
                writer = csv.writer(csv_file)
                writer.writerow(("timestamp_utc", "source", "value", "delta", "status", "direction", "threshold"))
                csv_file.flush()

            if args.demo:
                readings = iter((0, 1000000, 1000000, 1150001, 1150001, 0, 900000, 700000))
            else:
                # Lazy import keeps tests and demo usable without Windows or Pymem.
                import pymem
                import pymem.process

                memory = pymem.Pymem(args.process, exact_match=True)
                stack.callback(memory.close_process)
                module = pymem.process.module_from_name(memory.process_handle, args.process)
                if module is None:
                    raise RuntimeError(f"Module not found: {args.process}")
                base_address = module.lpBaseOfDll + args.base_offset

            print(f"NFS: HPR Zapper {__version__} | logging only | hardware output disabled")
            print(f"direction={args.direction}, threshold={args.threshold}, interval={args.interval}s")
            while True:
                if args.demo:
                    value = next(readings, None)
                    if value is None:
                        break
                else:
                    value = read_value(memory, base_address, args.offsets, args.pointer_bits, args.value_type)
                sample = detector.update(value)
                timestamp = datetime.now(timezone.utc).isoformat()
                print(f"{timestamp} value={sample.value} delta={sample.delta} status={sample.status}")
                if writer is not None:
                    writer.writerow((timestamp, "demo" if args.demo else "game", sample.value,
                                     sample.delta, sample.status, args.direction, args.threshold))
                    csv_file.flush()
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    except Exception as error:
        print(f"Monitoring stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
