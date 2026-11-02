# Need for Speed: HPR Zapper

**Version 0.1.0b1 — telemetry beta.** A starting point for exploring damage-based
feedback in Need for Speed: Hot Pursuit Remastered.

This beta reads a candidate health/damage value from game memory and records its
changes. It does not write to game memory or send Arduino/serial commands.
The original prototype's hardware output is disabled while the readings are verified.

## Setup

Live monitoring requires Windows, Python 3.10 or newer, and the game running.
In PowerShell, from the repository folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe zapper.py --demo
```

The demo and automated tests use only Python's standard library and can also run
with `python zapper.py --demo` before installing dependencies.
The Windows `py -3` launcher selects an installed Python rather than a copy
bundled with another application. If it reports no installed Python, create the
environment using the full path to your Python installation instead:

```powershell
& 'C:\path\to\Python\python.exe' -m venv .venv
```

## Record a session

Start the game, enter a driving session, then run:

```powershell
.\.venv\Scripts\python.exe zapper.py --csv logs/session-01.csv
```

Press Ctrl+C to stop. Choose a fresh CSV filename for each run; existing files
are never overwritten. Logs contain UTC timestamps, raw values, signed deltas,
candidate-event status, source (game/demo), direction, and threshold. The `logs/`
folder is ignored by Git.

The defaults preserve the original prototype's assumptions:

| Setting | Default |
| --- | --- |
| Process/module | `NFS11Remastered.exe` |
| Base offset | `0x12AF050` |
| Pointer offsets | `0x125F68 0x239C0 0x85C0` |
| Pointer width | 32 bits (now read unsigned) |
| Value type | Signed 32-bit integer |
| Candidate event | Increase strictly greater than 100,000 per sample |
| Poll interval | 0.5 seconds |

These addresses, types, and thresholds are **unverified**. They may depend on the
game build. A candidate event is a numeric change, not confirmed collision damage.
Use `python zapper.py --help` to see all settings. For example, after confirming
that the value represents health that decreases:

```powershell
.\.venv\Scripts\python.exe zapper.py --direction decrease --threshold 100000 --csv logs/session-02.csv
```

Use `--pointer-bits 64` or `--value-type float` only if inspection of the game's
memory confirms those types. Changing the value type also requires recalibrating
the threshold.

## Detection behavior and limits

- The first positive, finite reading establishes a baseline without an event.
- Zero, negative, and non-finite readings clear the baseline. The next positive
  reading establishes a new one. A fall to zero is currently treated as a reset,
  so a final damage event may be missed.
- An unchanged value does not repeat an event. Changes below the threshold are
  not accumulated across samples.
- Positive-to-positive race resets, repairs, and unrelated memory changes can
  still look like damage. There is no race-state detection yet.
- Polling can miss brief changes or combine multiple collisions into one sample.
- A missing process, null pointer, or failed memory read stops monitoring with an
  error. Restart after the game is ready; automatic reconnection is not implemented.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests cover thresholds, both change directions, baseline resets, pointer traversal,
memory failures, and CSV output. GitHub Actions runs these tests on Windows.
They do not verify addresses against a running game or validate physical hardware.

## Next experiment

1. Log an idle car, then one light collision and one heavier collision.
2. Note the times and compare the raw values and deltas in the CSV.
3. Record a wreck, repair, race restart, and return to the menu separately.
4. Confirm the pointer width, value type, and direction before tuning the threshold.
5. Use the captured observations to add regression tests and race-state handling.

Physical feedback is deferred; this beta makes no claim about electrical hardware
safety. A vibration motor is an option for testing the eventual feedback path.

## Dependency reference

Memory access uses [Pymem 1.14.0](https://pypi.org/project/Pymem/1.14.0/).
See the [Pymem API documentation](https://pymem.readthedocs.io/en/latest/api.html).
