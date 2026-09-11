"""Sweep harness: run the engine across a grid of configurations and aggregate.

The simulator answers one question per invocation. The project goals ask
comparative ones - does a five-sock unit beat a four-sock unit, is a pooled
drawer better than separate ones - and a single run cannot answer those,
because the spread across seeds is wider than the effect being measured. This
runs each configuration over a set of seeds and reports the distribution.

    uv run sweep.py configs/goal2_unit_comparison.json
    uv run sweep.py configs/goal3_pooling.json --days 3600 --seeds 1 2 3 4 5

Determinism is the point of the whole exercise, so nothing here is allowed to
disturb it. Cells run in separate processes, but each engine seeds its own
``random.Random``, results are sorted back into config order before being
aggregated, and no timestamp is written into the output. Two invocations over
the same seed set produce byte-identical files.
"""

import argparse
import csv
import json
import multiprocessing as mp
import random
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

from core.engine import Engine
from core.registry import discover

METRICS = (
	'spend_per_year',
	'total_embarrassment',
	'mean_daily_embarrassment',
	'sockless_days',
	'total_sockless_days',
)

DEFAULTS = {
	'capacity': 40,
	'unit': 4,
	'days': 360,
	'timeout': 1.0,
	'budget': None,
}


@dataclass(frozen=True)
class Cell:
	"""One configuration in the grid, to be run over every seed."""

	label: str
	players: tuple[tuple[str, int], ...]
	capacity: int
	unit: int
	days: int
	timeout: float
	budget: float | None = None

	@property
	def budget_text(self) -> str:
		return 'unlimited' if self.budget is None else f'{self.budget:g}'

	@property
	def roommates(self) -> int:
		return sum(count for _, count in self.players)

	@property
	def roster_text(self) -> str:
		return ' '.join(f'{code}x{count}' for code, count in self.players)


@dataclass
class SweepConfig:
	name: str
	description: str
	seeds: list[int]
	cells: list[Cell]
	source: Path = field(default=Path('.'))


# ----------------------------------------------------------------- config


def _players_of(raw: Any) -> tuple[tuple[str, int], ...]:
	"""Normalise a players spec into (code, count) pairs.

	Accepts ``[['g', 4]]``, ``[{'code': 'g', 'count': 4}]`` or the shorthand
	``'g'`` for a single roommate, so configs stay readable.
	"""
	if isinstance(raw, str):
		return ((raw, 1),)

	pairs: list[tuple[str, int]] = []
	for entry in raw:
		if isinstance(entry, dict):
			pairs.append((str(entry['code']), int(entry['count'])))
		elif isinstance(entry, str):
			pairs.append((entry, 1))
		else:
			code, count = entry
			pairs.append((str(code), int(count)))
	return tuple(pairs)


def _cell_from(raw: dict, defaults: dict, index: int) -> Cell:
	merged = {**defaults, **raw}
	if 'players' not in merged:
		raise ValueError(f'cell {index} has no "players" and no default for it')

	players = _players_of(merged['players'])
	label = str(merged.get('label') or f'cell{index}')
	return Cell(
		label=label,
		players=players,
		capacity=int(merged['capacity']),
		unit=int(merged['unit']),
		days=int(merged['days']),
		timeout=float(merged['timeout']),
		budget=None if merged.get('budget') is None else float(merged['budget']),
	)


def load_config(path: Path | str) -> SweepConfig:
	"""Read a sweep description. ``grid`` is expanded as a cross product,
	``cells`` are taken verbatim, and a config may use either or both."""
	path = Path(path)
	raw = json.loads(path.read_text())
	defaults = {**DEFAULTS, **raw.get('defaults', {})}

	cells: list[Cell] = []

	grid = raw.get('grid') or {}
	if grid:
		keys = sorted(grid)
		for combo in product(*(grid[k] for k in keys)):
			entry = dict(zip(keys, combo, strict=True))
			label = entry.pop('label', None)
			spec = {**entry}
			if label:
				spec['label'] = label
			else:
				parts = [f'{k}={_label_part(entry[k])}' for k in sorted(entry)]
				spec['label'] = ' '.join(parts)
			cells.append(_cell_from(spec, defaults, len(cells)))

	for entry in raw.get('cells', []):
		cells.append(_cell_from(entry, defaults, len(cells)))

	if not cells:
		raise ValueError(f'{path} defines no cells (need "grid" or "cells")')

	seeds = [int(s) for s in raw.get('seeds', [4444])]
	if not seeds:
		raise ValueError(f'{path} defines an empty seed list')

	return SweepConfig(
		name=str(raw.get('name') or path.stem),
		description=str(raw.get('description', '')),
		seeds=seeds,
		cells=cells,
		source=path,
	)


def _label_part(value: Any) -> str:
	if isinstance(value, list | tuple):
		return ''.join(f'{c}{n}' for c, n in _players_of(value))
	if value is None:
		return 'unlimited'
	return str(value)


# ----------------------------------------------------------------- running


def _run_one(job: dict) -> dict:
	"""Run a single (cell, seed) pair. Executed in a worker process.

	Takes player *codes* rather than classes: the registry resolves them
	inside the worker, so nothing student-authored has to survive pickling
	and a spawn-based process still finds the roster.
	"""
	available, _ = discover()
	roster = []
	for code, count in job['players']:
		roster.extend([available[code]] * count)

	# RandomPlayer draws from the global `random` module rather than the
	# engine's rng, so without this the same seed gives different answers in
	# every process. Seeding here keeps a sweep reproducible without changing
	# what a plain `main.py` run does.
	random.seed(job['seed'])

	engine = Engine(
		players=roster,
		capacity=job['capacity'],
		selection_unit=job['unit'],
		days=job['days'],
		seed=job['seed'],
		timeout=job['timeout'],
		budget=job['budget'],
		keep_records=job['keep_records'],
	)
	results = engine.run()

	per_player = results['players']
	mean_daily = (
		statistics.fmean(p['mean_daily_embarrassment'] for p in per_player) if per_player else 0.0
	)
	# Per-roommate, so cells with different n stay comparable. The run-level
	# figure is reported alongside it as total_sockless_days.
	mean_sockless = statistics.fmean(p['sockless_days'] for p in per_player) if per_player else 0.0

	return {
		'cell': job['cell'],
		'seed': job['seed'],
		'spend_per_year': results['spend_per_year'],
		'total_spent': results['total_spent'],
		'total_embarrassment': results['total_embarrassment'],
		'mean_daily_embarrassment': mean_daily,
		'sockless_days': mean_sockless,
		'total_sockless_days': results['total_sockless_days'],
		'budget_exhausted_on_day': results['budget_exhausted_on_day'],
		'budget_remaining': results['budget_remaining'],
		'faults': len(results['faults']),
	}


def build_jobs(config: SweepConfig, keep_records: bool) -> list[dict]:
	jobs = []
	for i, cell in enumerate(config.cells):
		for seed in config.seeds:
			jobs.append(
				{
					'cell': i,
					'seed': seed,
					'players': list(cell.players),
					'capacity': cell.capacity,
					'unit': cell.unit,
					'days': cell.days,
					'timeout': cell.timeout,
					'budget': cell.budget,
					'keep_records': keep_records,
				}
			)
	return jobs


def validate(config: SweepConfig) -> None:
	"""Fail before spawning anything. A grid typo should not surface as ten
	identical tracebacks from ten workers."""
	available, errors = discover()
	for err in errors:
		print(f"warning: player '{err.code}' failed to load - {err.message}", file=sys.stderr)

	for cell in config.cells:
		unknown = [code for code, _ in cell.players if code not in available]
		if unknown:
			codes = ', '.join(sorted(available)) or 'none'
			raise SystemExit(
				f"cell '{cell.label}' names unloadable player(s) {unknown}. Available: {codes}"
			)
		# Surfaces the multiple-of-4 and C > unit*n+10 rules with the cell
		# label attached, which a raw ValueError from a worker would not have.
		try:
			Engine(
				players=[available[cell.players[0][0]]] * cell.roommates,
				capacity=cell.capacity,
				selection_unit=cell.unit,
				days=0,
				seed=0,
			)
		except ValueError as exc:
			raise SystemExit(f"cell '{cell.label}' is not a legal configuration: {exc}") from exc


def execute(
	jobs: list[dict],
	workers: int,
	worker: Callable[[dict], dict] = _run_one,
	on_progress: Callable[[dict, int, int], None] | None = None,
) -> list[dict]:
	"""Run every job and return the results in job order.

	Workers hand back results as they finish, so the list is sorted before it
	goes anywhere near the aggregates. Parallelism must not be visible in the
	output.

	``worker`` is a parameter so the tournament runner can reuse this instead
	of growing its own copy of the pool, the progress line and the sort.
	``on_progress(result, done, total)`` replaces the default progress line
	when a caller wants a live leaderboard.
	"""
	done: list[dict] = []

	def take(result: dict) -> None:
		done.append(result)
		n = len(done)
		if on_progress is None:
			_track(result, n - 1, len(jobs))
		else:
			on_progress(result, n, len(jobs))

	if workers <= 1 or len(jobs) == 1:
		for job in jobs:
			take(worker(job))
	else:
		ctx = mp.get_context('spawn')
		with ctx.Pool(processes=workers) as pool:
			for result in pool.imap_unordered(worker, jobs):
				take(result)

	return sorted(done, key=lambda r: (r['cell'], r['seed']))


def execute_live(
	jobs: list[dict],
	workers: int,
	worker: Callable[[dict], dict],
	on_progress: Callable[[dict, int, int], None],
	idle: Callable[[], None],
	pace: float = 0.0,
) -> list[dict]:
	"""Like ``execute``, but yields the event loop between results.

	The GUI has to keep pumping pygame while workers run, otherwise macOS
	shows a frozen first frame and then the finished table.
	``pace`` is extra seconds to hold each new ranking on screen so a
	projector can actually see the numbers move.
	"""
	import time

	done: list[dict] = []
	n_workers = max(1, workers)
	ctx = mp.get_context('spawn')
	with ctx.Pool(processes=n_workers) as pool:
		iterator = pool.imap_unordered(worker, jobs)
		while len(done) < len(jobs):
			idle()
			try:
				result = iterator.next(timeout=0.03)
			except mp.TimeoutError:
				continue
			done.append(result)
			on_progress(result, len(done), len(jobs))
			if pace > 0:
				hold = time.monotonic() + pace
				while time.monotonic() < hold:
					idle()

	return sorted(done, key=lambda r: (r['cell'], r['seed']))


def _track(result: dict, index: int, total: int) -> dict:
	print(f'\r  {index + 1}/{total} runs complete', end='', file=sys.stderr, flush=True)
	if index + 1 == total:
		print(file=sys.stderr)
	return result


# ----------------------------------------------------------------- aggregation


def summarise(values: list[float]) -> dict:
	return {
		'mean': statistics.fmean(values),
		'median': statistics.median(values),
		'stddev': statistics.stdev(values) if len(values) > 1 else 0.0,
		'min': min(values),
		'max': max(values),
	}


def summarise_exhaustion(values: list) -> dict:
	"""Budget exhaustion is a day number or nothing at all.

	Averaging it naively would either crash on the None or, worse, quietly
	treat "never ran out" as day zero. A cell where three seeds survived and
	two collapsed is the interesting case, so the count is reported next to
	the timing rather than folded into it.
	"""
	hit = sorted(v for v in values if v is not None)
	return {
		'runs_exhausted': len(hit),
		'runs_survived': len(values) - len(hit),
		'mean_day': statistics.fmean(hit) if hit else None,
		'median_day': statistics.median(hit) if hit else None,
		'earliest_day': hit[0] if hit else None,
		'latest_day': hit[-1] if hit else None,
	}


def aggregate(config: SweepConfig, runs: list[dict]) -> dict:
	by_cell: dict[int, list[dict]] = {i: [] for i in range(len(config.cells))}
	for run in runs:
		by_cell[run['cell']].append(run)

	cells = []
	for i, cell in enumerate(config.cells):
		mine = by_cell[i]
		if not mine:
			# Live --gui updates mid-sweep. A cell with no finished seed yet
			# is omitted rather than crashing summarise on an empty list.
			continue
		cells.append(
			{
				'label': cell.label,
				'players': [list(p) for p in cell.players],
				'roommates': cell.roommates,
				'capacity': cell.capacity,
				'selection_unit': cell.unit,
				'days': cell.days,
				'budget': cell.budget,
				'seeds': [r['seed'] for r in mine],
				'aggregates': {m: summarise([r[m] for r in mine]) for m in METRICS},
				'budget_exhausted': summarise_exhaustion(
					[r['budget_exhausted_on_day'] for r in mine]
				),
				'faults': sum(r['faults'] for r in mine),
				'runs': [{k: v for k, v in r.items() if k != 'cell'} for r in mine],
			}
		)

	return {
		'sweep': config.name,
		'description': config.description,
		'config': str(config.source),
		'seeds': config.seeds,
		'cells': cells,
	}


# ----------------------------------------------------------------- output


def write_outputs(report: dict, out_dir: Path) -> list[Path]:
	out_dir.mkdir(parents=True, exist_ok=True)
	stem = report['sweep']

	json_path = out_dir / f'{stem}.json'
	json_path.write_text(json.dumps(report, indent=2) + '\n')

	csv_path = out_dir / f'{stem}.csv'
	header = [
		'label',
		'players',
		'roommates',
		'capacity',
		'unit',
		'days',
		'budget',
		'seeds',
		'faults',
		'runs_exhausted',
		'runs_survived',
		'exhausted_mean_day',
		'exhausted_earliest_day',
	]
	for metric in METRICS:
		header += [f'{metric}_{stat}' for stat in ('mean', 'median', 'stddev', 'min', 'max')]

	with csv_path.open('w', newline='') as fh:
		writer = csv.writer(fh)
		writer.writerow(header)
		for cell in report['cells']:
			spent = cell['budget_exhausted']
			row = [
				cell['label'],
				' '.join(f'{c}x{n}' for c, n in cell['players']),
				cell['roommates'],
				cell['capacity'],
				cell['selection_unit'],
				cell['days'],
				'' if cell['budget'] is None else cell['budget'],
				len(cell['seeds']),
				cell['faults'],
				spent['runs_exhausted'],
				spent['runs_survived'],
				'' if spent['mean_day'] is None else spent['mean_day'],
				'' if spent['earliest_day'] is None else spent['earliest_day'],
			]
			for metric in METRICS:
				stats = cell['aggregates'][metric]
				row += [stats[s] for s in ('mean', 'median', 'stddev', 'min', 'max')]
			writer.writerow(row)

	runs_path = out_dir / f'{stem}_runs.csv'
	with runs_path.open('w', newline='') as fh:
		writer = csv.writer(fh)
		writer.writerow(
			[
				'label',
				'seed',
				'roommates',
				'capacity',
				'unit',
				'days',
				'spend_per_year',
				'total_spent',
				'total_embarrassment',
				'mean_daily_embarrassment',
				'sockless_days',
				'total_sockless_days',
				'budget',
				'budget_remaining',
				'budget_exhausted_on_day',
				'faults',
			]
		)
		for cell in report['cells']:
			for run in cell['runs']:
				writer.writerow(
					[
						cell['label'],
						run['seed'],
						cell['roommates'],
						cell['capacity'],
						cell['selection_unit'],
						cell['days'],
						run['spend_per_year'],
						run['total_spent'],
						run['total_embarrassment'],
						run['mean_daily_embarrassment'],
						run['sockless_days'],
						run['total_sockless_days'],
						'' if cell['budget'] is None else cell['budget'],
						'' if run['budget_remaining'] is None else run['budget_remaining'],
						''
						if run['budget_exhausted_on_day'] is None
						else run['budget_exhausted_on_day'],
						run['faults'],
					]
				)

	return [json_path, csv_path, runs_path]


def print_table(report: dict) -> None:
	width = max(len(c['label']) for c in report['cells'])
	print(f'\n{report["sweep"]}  ({len(report["seeds"])} seeds)')
	print(
		f'{"cell":<{width}}  {"embarr/day":>16}  {"$/year":>14}  '
		f'{"sockless":>10}  {"ran dry":>9}  faults'
	)
	for cell in report['cells']:
		emb = cell['aggregates']['mean_daily_embarrassment']
		spend = cell['aggregates']['spend_per_year']
		sockless = cell['aggregates']['sockless_days']
		spent = cell['budget_exhausted']

		emb_text = f'{emb["mean"]:,.1f} +/- {emb["stddev"]:,.1f}'
		spend_text = f'{spend["mean"]:.0f} +/- {spend["stddev"]:.0f}'
		sockless_text = f'{sockless["mean"]:,.0f}'
		if spent['runs_exhausted']:
			dry = f'{spent["runs_exhausted"]}/{len(cell["seeds"])} d{spent["mean_day"]:.0f}'
		else:
			dry = '-'

		print(
			f'{cell["label"]:<{width}}  {emb_text:>16}  {spend_text:>14}  '
			f'{sockless_text:>10}  {dry:>9}  {cell["faults"]:>6}'
		)


# ----------------------------------------------------------------- cli


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description='Run the sock simulator across a grid of configurations.'
	)
	parser.add_argument(
		'config', type=Path, help='Sweep description, e.g. configs/goal3_pooling.json'
	)
	parser.add_argument(
		'--out-dir', type=Path, default=Path('results'), help='Where to write JSON and CSV.'
	)
	parser.add_argument('--seeds', type=int, nargs='+', help='Override the seed list.')
	parser.add_argument('--days', type=int, help='Override days for every cell.')
	parser.add_argument('--capacity', type=int, help='Override C for every cell.')
	parser.add_argument(
		'--unit', type=int, choices=(4, 5), help='Override the unit for every cell.'
	)
	parser.add_argument('--timeout', type=float, help='Override the player time budget.')
	parser.add_argument(
		'--budget',
		type=float,
		help='Override the dollar budget for every cell. Cannot set a cell back to unlimited; '
		'edit the config for that.',
	)
	parser.add_argument(
		'--workers',
		type=int,
		default=0,
		help='Worker processes. 0 picks one per CPU, 1 runs sequentially.',
	)
	parser.add_argument(
		'--keep-records',
		action='store_true',
		help='Retain per-day DayRecords in each engine. Off by default: a long sweep does not '
		'need them and they dominate memory.',
	)
	parser.add_argument(
		'--gui',
		action='store_true',
		help='Open a comparison window that updates as cells finish. No socks.',
	)
	return parser.parse_args(argv)


def apply_overrides(config: SweepConfig, args: argparse.Namespace) -> SweepConfig:
	if args.seeds:
		config.seeds = args.seeds

	changes = {
		key: getattr(args, key)
		for key in ('days', 'capacity', 'timeout', 'budget')
		if getattr(args, key) is not None
	}
	if args.unit is not None:
		changes['unit'] = args.unit

	if changes:
		config.cells = [
			Cell(
				label=cell.label,
				players=cell.players,
				capacity=changes.get('capacity', cell.capacity),
				unit=changes.get('unit', cell.unit),
				days=changes.get('days', cell.days),
				timeout=changes.get('timeout', cell.timeout),
				budget=changes.get('budget', cell.budget),
			)
			for cell in config.cells
		]

	return config


def main(argv: list[str] | None = None) -> None:
	args = parse_args(argv)
	if not args.config.exists():
		raise SystemExit(f'no such config: {args.config}')

	config = apply_overrides(load_config(args.config), args)
	validate(config)

	jobs = build_jobs(config, keep_records=args.keep_records)
	workers = args.workers or min(len(jobs), mp.cpu_count())
	print(
		f'{config.name}: {len(config.cells)} cells x {len(config.seeds)} seeds '
		f'= {len(jobs)} runs on {workers} worker(s)',
		file=sys.stderr,
	)

	board = None
	if args.gui:
		from ui.sweepboard import SweepBoard

		board = SweepBoard(
			title=config.name,
			labels=[c.label for c in config.cells],
			total=len(jobs),
		)

	partial: list[dict] = []

	def apply_result(result: dict, n: int, total: int) -> None:
		partial.append(result)
		if board is None:
			return
		report = aggregate(config, partial)
		last = f'{config.cells[result["cell"]].label}  seed {result["seed"]}'
		board.update(report['cells'], n, last_run=last)

	if board is not None:
		import pygame

		pace = 0.0 if pygame.display.get_driver() == 'dummy' else 0.12
		runs = execute_live(
			jobs,
			workers,
			worker=_run_one,
			on_progress=apply_result,
			idle=lambda: board.tick(),
			pace=pace,
		)
	else:
		runs = execute(jobs, workers)

	report = aggregate(config, runs)
	written = write_outputs(report, args.out_dir)

	print_table(report)
	print('\nwrote:')
	for path in written:
		print(f'  {path}')

	if board is not None:
		board.update(report['cells'], len(jobs))
		board.wait_to_close()


if __name__ == '__main__':
	main()
