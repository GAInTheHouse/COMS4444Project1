# Mock student submissions

Eleven throwaway group directories covering the ways a real submission breaks.
They live here rather than in `players/` for two reasons: `players/player_<k>/`
is gitignored, so anything left there vanishes from the shared history, and the
registry only scans `players/`, so nothing here can ever be loaded as a
competitor by accident.

This is a **manual smoke test** for the live-demo path end to end - discovery,
the roster warnings, `main.py`, and the fault report as the TA actually sees
them. The automatic coverage is `tests/test_adversarial.py`, which is what CI
runs; these exist for the sanity check before a class.

## Running them

```bash
cp -R tests/fixtures/mock_submissions/player_* players/
uv run main.py --player 1 1 --player 2 1 --player 3 1 --player 4 1 \
               --player 5 1 --player 6 1 --player 9 1 --player 10 1 \
               --player 11 1 --player g 1 \
               -C 52 --days 10 --seed 7 --timeout 0.25
rm -rf players/player_[0-9]*
```

Do not leave them in `players/`: every one of them is discovered, so they will
turn up in the registry listing and in `tournament.py`'s default entrant field.

## What each one does, and what should happen

| Group | Breakage | Expected |
| --- | --- | --- |
| 1 | none - a plausible good submission | no faults |
| 2 | raises from day 4 | a fault on days 4 onward only |
| 3 | infinite loop in `select_socks` | `exceeded Ns time budget`, one per day |
| 4 | `Selection(wear=7)` | `TypeError: 'int' object is not iterable` |
| 5 | numpy indices | `wear indices must be plain ints, not numpy.int64` |
| 6 | indices out of range | `wear indices must lie in [0, 4)` |
| 7 | imports a missing module | reported by `discover()`, never runs |
| 8 | no `__init__.py` | reported by `discover()` as invisible |
| 9 | blanks its history via `__closure__` | no fault; it is still scored |
| 10 | raises in `__init__` | `could not be constructed`, then forfeits daily |
| 11 | hangs in `__init__` | caught by the timeout, then forfeits daily |

The run must finish with exit 0 in every case, every fault must name its own
group, and the honest roommates (1 and `g`) must end on 0.0 embarrassment.

Groups 5 and 6 are the pair worth looking at: identical numbers, different
verdicts. They are why the type error and the range error are separate
sentences.
