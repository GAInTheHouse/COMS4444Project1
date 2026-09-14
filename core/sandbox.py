"""Isolation for student code.

The 2025 simulators called player methods directly, so a single group's
infinite loop or unhandled exception took down the whole run. That is fine
when you are debugging alone and fatal when you are demoing ten groups live
in class. Everything here exists so one bad player forfeits its own turn and
nothing else.
"""

import signal
from collections.abc import Callable
from typing import Any

_HAS_ALARM = hasattr(signal, 'SIGALRM')


class PlayerFault(Exception):
	"""Raised when player code times out, crashes or returns something illegal."""


class _Timeout(Exception):
	pass


def _raise_timeout(signum, frame):  # noqa: ARG001
	raise _Timeout


def call_player(fn: Callable[..., Any], *args: Any, timeout: float = 1.0) -> Any:
	"""Call ``fn`` with a wall-clock budget, converting any failure to PlayerFault.

	Uses SIGALRM, which is Unix-only and main-thread-only. On platforms
	without it the call proceeds unguarded rather than silently refusing to
	run, so Windows users can still develop against the simulator.

	A PlayerFault raised by ``fn`` passes through unchanged: the engine
	validates the returned move inside this guard, and its verdict is already
	the right message to report.
	"""
	if not _HAS_ALARM or timeout <= 0:
		try:
			return fn(*args)
		except PlayerFault:
			# Already a considered verdict on the player's move. Re-wrapping it
			# would double up the prefix in the fault report.
			raise
		except Exception as exc:
			raise PlayerFault(f'{type(exc).__name__}: {exc}') from exc

	previous = signal.signal(signal.SIGALRM, _raise_timeout)
	signal.setitimer(signal.ITIMER_REAL, timeout)
	try:
		return fn(*args)
	except _Timeout as exc:
		raise PlayerFault(f'exceeded {timeout:g}s time budget') from exc
	except PlayerFault:
		raise
	except Exception as exc:
		raise PlayerFault(f'{type(exc).__name__}: {exc}') from exc
	finally:
		signal.setitimer(signal.ITIMER_REAL, 0)
		signal.signal(signal.SIGALRM, previous)
