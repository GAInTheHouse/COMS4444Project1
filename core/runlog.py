"""Per-run debug log for students.

The engine never opens a file. ``main.py`` constructs a ``RunLog`` and hands
``record_day`` to ``Engine.run`` / the visualiser as an ``on_day`` callback, so
sweeps and the tournament — which never go through ``main.py`` — stay silent.

Written incrementally, one day at a time, so a crash or a GUI quit still leaves
everything that did run. The log is a post-hoc view of the same numbers the
visualiser already shows; it is not a new channel into ``select_socks``.
"""

import json
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from core.engine import DayRecord, Engine
from models.sock import Color

DEFAULT_DIR = Path('logs')


def default_path(seed: int) -> Path:
	stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
	return DEFAULT_DIR / f'socks-{stamp}-seed{seed}.log'


def _money(value: float) -> str:
	if value == float('inf'):
		return 'inf'
	return f'${value:,.0f}'


def _counter(counts: Counter) -> str:
	white = counts.get(Color.WHITE, 0)
	black = counts.get(Color.BLACK, 0)
	return f'{white}w {black}b'


def _join(values: tuple[object, ...] | list[object]) -> str:
	return ','.join(str(v) for v in values) if values else '-'


class RunLog:
	"""Append-only text log of a single ``main.py`` run."""

	def __init__(self, path: Path, stream: TextIO) -> None:
		self.path = path
		self._stream = stream
		self._closed = False

	@classmethod
	def create(
		cls,
		path: str,
		engine: Engine,
		*,
		seed: int,
		budget: float | None,
	) -> 'RunLog':
		target = Path(path) if path else default_path(seed)
		target.parent.mkdir(parents=True, exist_ok=True)
		stream = target.open('w', encoding='utf-8')
		log = cls(target, stream)
		log._write_header(engine, seed=seed, budget=budget)
		return log

	def _write(self, text: str) -> None:
		self._stream.write(text)
		if not text.endswith('\n'):
			self._stream.write('\n')
		self._stream.flush()

	def _write_header(
		self,
		engine: Engine,
		*,
		seed: int,
		budget: float | None,
	) -> None:
		roster = ' '.join(f'{i}={name}' for i, name in enumerate(engine.player_names))
		budget_s = 'unlimited' if budget is None else _money(budget)
		self._write('socks debug log')
		self._write(
			f'seed={seed}  C={engine.capacity}  unit={engine.selection_unit}  '
			f'n={engine.roommates}  days={engine.days}  budget={budget_s}  '
			f'timeout={engine.timeout}'
		)
		self._write(f'roster: {roster}')
		self._write('')

	def record_day(self, record: DayRecord, engine: Engine) -> None:
		"""One block per simulated morning, in dress order."""
		budget = record.budget_remaining
		lines = [
			f'day {record.day}  order {_join(tuple(record.order))}  '
			f'spent today {_money(record.spent_today)}  '
			f'total {_money(engine.total_spent)}  '
			f'budget {_money(budget)}  '
			f'drawer {len(engine.drawer)}  '
			f'trash {_counter(engine.pending_discards)}'
		]
		for index in record.order:
			lines.append(_turn_line(record, engine, index))
		if record.packs_bought or record.holes:
			lines.append(
				f'  packs {_counter(record.packs_bought)}  holes {_counter(record.holes)}  '
				f'discarded {_counter(record.discarded)}'
			)
		if record.faults:
			for fault in record.faults:
				lines.append(f'  FAULT {fault}')
		# sorted() copies. Logging the live drawer in place would change
		# which indices rng.sample picks tomorrow.
		shades = sorted(s.shade for s in engine.drawer)
		lines.append(f'  drawer_shades {_join(shades)}')
		self._write('\n'.join(lines))
		self._write('')

	def finish(self, engine: Engine) -> None:
		if self._closed:
			return
		self._write(f'======== snapshot after day {engine.day} / {engine.days} ========')
		self._write(json.dumps(engine.results(), indent=2))
		self._stream.close()
		self._closed = True

	def close(self) -> None:
		if not self._closed:
			self._stream.close()
			self._closed = True


def _turn_line(record: DayRecord, engine: Engine, index: int) -> str:
	name = engine.player_names[index]
	offered = record.offered.get(index, ())
	prefix = f'  [{index}] {name}'

	if index in record.sockless:
		return (
			f'{prefix}  SOCKLESS  offered {_join(offered)}  '
			f'penalty {record.embarrassment.get(index, 0):,.0f}'
		)

	wear = record.wear_idx.get(index, ())
	worn = record.worn.get(index)
	worn_s = f'{worn[0]}/{worn[1]}' if worn else '-'
	discard = record.discard_idx.get(index, ())
	score = record.embarrassment.get(index, 0.0)
	return (
		f'{prefix}  offered {_join(offered)}  '
		f'wear {_join(wear)} {worn_s}  '
		f'discard {_join(discard)}  '
		f'embarr {score:,.0f}'
	)


def bind(log: RunLog, engine: Engine) -> Callable[[DayRecord], None]:
	"""Adapt ``record_day`` to the one-argument ``on_day`` callback."""

	def on_day(record: DayRecord) -> None:
		log.record_day(record, engine)

	return on_day
