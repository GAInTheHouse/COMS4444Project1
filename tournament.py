"""Tournament runner: rank groups by how they do across many shared drawers.

The course ruling on scoring: there is no scoring rule *within* a single
simulation. A run produces embarrassment and spend for each roommate, and that
is all it produces - no winner, no points. Groups are ranked by their averages
across many runs, in many different combinations of groups sharing a drawer.
The reasoning is that a group which consistently overspends drags down every
configuration it appears in, while configurations excluding it come out clean,
and that shows up in the averages without anyone having to invent a formula
weighing dollars against embarrassment.

So this generates combinations of the loaded players filling the roommate
slots - mixed groups and all-one-group rosters, both of which the handout
allows - runs each across seeds and configurations, and averages each group's
results over every run it appeared in.

    uv run tournament.py configs/tournament.json
    uv run tournament.py configs/tournament.json --rank-by spend_per_year

Everything about running jobs is borrowed from sweep.py rather than
reimplemented: the process pool, the progress line, the deterministic sort and
the per-cell statistics all come from there.
"""

import argparse
import csv
import json
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations_with_replacement, product
from pathlib import Path

from core.engine import PACK_COST, Engine
from core.registry import discover
from sweep import execute, execute_live, summarise, summarise_exhaustion

# Averaged per roommate belonging to the group, except spend, which belongs to
# the run: one drawer, one bill, and everyone sharing it is implicated.
GROUP_METRICS = ('mean_daily_embarrassment', 'total_embarrassment', 'sockless_days')
RUN_METRICS = ('spend_per_year', 'total_spent')

DEFAULTS = {
	'capacity': 40,
	'unit': 4,
	'days': 1080,
	'timeout': 1.0,
	'budget': None,
}


@dataclass(frozen=True)
class Arena:
	"""One set of table stakes. Every roster plays every arena."""

	capacity: int
	unit: int
	days: int
	timeout: float
	budget: float | None

	@property
	def label(self) -> str:
		budget = 'unlimited' if self.budget is None else f'${self.budget:g}'
		return f'C{self.capacity} u{self.unit} {self.days}d {budget}'


@dataclass(frozen=True)
class Match:
	"""One roster in one arena, to be run over every seed."""

	arena: Arena
	roster: tuple[str, ...]

	@property
	def label(self) -> str:
		return f'{"+".join(self.roster)} @ {self.arena.label}'


# ----------------------------------------------------------------- config


def load_config(path: Path | str) -> dict:
	path = Path(path)
	raw = json.loads(path.read_text())
	defaults = {**DEFAULTS, **raw.get('defaults', {})}

	grid = raw.get('grid') or {}
	keys = sorted(grid)
	arenas: list[Arena] = []
	for combo in product(*(grid[k] for k in keys)) if keys else [()]:
		merged = {**defaults, **dict(zip(keys, combo, strict=True))}
		arenas.append(
			Arena(
				capacity=int(merged['capacity']),
				unit=int(merged['unit']),
				days=int(merged['days']),
				timeout=float(merged['timeout']),
				budget=None if merged.get('budget') is None else float(merged['budget']),
			)
		)

	return {
		'name': str(raw.get('name') or path.stem),
		'description': str(raw.get('description', '')),
		'source': str(path),
		'roommates': [int(n) for n in raw.get('roommates', [4])],
		'seeds': [int(s) for s in raw.get('seeds', [4444])],
		'entrants': raw.get('entrants'),
		'arenas': arenas,
	}


def entrants_for(config: dict) -> list[str]:
	"""Which player codes compete. Defaults to everything the registry loaded."""
	available, errors = discover()
	for err in errors:
		print(f"warning: player '{err.code}' failed to load - {err.message}", file=sys.stderr)

	if config['entrants']:
		missing = [c for c in config['entrants'] if c not in available]
		if missing:
			raise SystemExit(f'entrants not loadable: {missing}. Available: {sorted(available)}')
		return sorted(config['entrants'])

	return sorted(available)


def build_matches(config: dict, entrants: list[str]) -> tuple[list[Match], list[str]]:
	"""Every multiset of entrants that fills the roommate slots.

	``combinations_with_replacement`` rather than ``permutations``: seating
	order is reshuffled daily by the engine, so g+r and r+g are the same match
	and running both would only double the bill. Rosters that are all one group
	fall out of it naturally, which the handout explicitly wants.
	"""
	matches: list[Match] = []
	skipped: list[str] = []

	for arena in config['arenas']:
		for n in config['roommates']:
			floor = arena.unit * n + 10
			if arena.capacity % 4 != 0 or arena.capacity <= floor:
				skipped.append(
					f'n={n} in {arena.label}: C must be a multiple of 4 and exceed {floor}'
				)
				continue
			for roster in combinations_with_replacement(entrants, n):
				matches.append(Match(arena=arena, roster=roster))

	return matches, skipped


# ----------------------------------------------------------------- running


def _run_match(job: dict) -> dict:
	"""Play one roster in one arena at one seed, in a worker process.

	Returns per-roommate detail, which is what ranking needs and what
	sweep's own worker does not keep.
	"""
	available, _ = discover()
	roster = [available[code] for code in job['roster']]

	# RandomPlayer draws from the global module rather than the engine's rng.
	# Seeding here is what makes a tournament re-runnable.
	random.seed(job['seed'])

	results = Engine(
		players=roster,
		capacity=job['capacity'],
		selection_unit=job['unit'],
		days=job['days'],
		seed=job['seed'],
		timeout=job['timeout'],
		budget=job['budget'],
		keep_records=False,
	).run()

	return {
		'cell': job['cell'],
		'seed': job['seed'],
		'roster': list(job['roster']),
		'spend_per_year': results['spend_per_year'],
		'total_spent': results['total_spent'],
		'budget_exhausted_on_day': results['budget_exhausted_on_day'],
		'total_sockless_days': results['total_sockless_days'],
		'faults': len(results['faults']),
		'seats': [
			{
				'code': job['roster'][p['index']],
				'index': p['index'],
				'mean_daily_embarrassment': p['mean_daily_embarrassment'],
				'total_embarrassment': p['total_embarrassment'],
				'sockless_days': p['sockless_days'],
			}
			for p in results['players']
		],
	}


def calibrate(matches: list[Match], seeds: list[int], workers: int, margin: float = 1.10) -> dict:
	"""Measure what the entrants actually spend, and price the arenas above it.

	The endgame is a cliff rather than a slope, so a budget below a roster's
	natural spend does not make that roster try harder - it collapses the
	drawer and buries every other signal under 65536-point sockless days.
	Averaging an arena above the cliff with one below it yields a mean that is
	entirely the starving arena, which is how an early config ranked
	RandomPlayer above GreedyPlayer: greedy discards, so a budget that starved
	greedy left random untouched.

	The safe threshold is therefore a property of who entered, not of the
	simulator, and it has to be re-measured whenever the field changes. This
	runs every match with no budget at all, takes the worst spend anyone
	incurs, and adds a margin - rounded up to a whole pack, since money only
	ever leaves in $10 units.
	"""
	uncapped = [
		Match(
			arena=Arena(
				capacity=m.arena.capacity,
				unit=m.arena.unit,
				days=m.arena.days,
				timeout=m.arena.timeout,
				budget=None,
			),
			roster=m.roster,
		)
		for m in matches
	]
	runs = execute(build_jobs(uncapped, seeds), workers, worker=_run_match)

	worst = max(runs, key=lambda r: r['total_spent'])
	recommended = math.ceil(worst['total_spent'] * margin / PACK_COST) * PACK_COST

	by_label: dict[str, float] = {}
	for run in runs:
		label = uncapped[run['cell']].arena.label
		by_label[label] = max(by_label.get(label, 0.0), run['total_spent'])
	per_arena = {
		label: {
			'max_total_spent': spend,
			'recommended_budget': math.ceil(spend * margin / PACK_COST) * PACK_COST,
		}
		for label, spend in sorted(by_label.items())
	}

	return {
		'margin': margin,
		'runs': len(runs),
		'max_total_spent': worst['total_spent'],
		'worst_roster': worst['roster'],
		'recommended_budget': float(recommended),
		'per_arena': per_arena,
	}


def build_jobs(matches: list[Match], seeds: list[int]) -> list[dict]:
	jobs = []
	for i, match in enumerate(matches):
		for seed in seeds:
			jobs.append(
				{
					'cell': i,
					'seed': seed,
					'roster': match.roster,
					'capacity': match.arena.capacity,
					'unit': match.arena.unit,
					'days': match.arena.days,
					'timeout': match.arena.timeout,
					'budget': match.arena.budget,
				}
			)
	return jobs


# ----------------------------------------------------------------- ranking


def rank(matches: list[Match], runs: list[dict], entrants: list[str], rank_by: str) -> dict:
	"""Average each group over every run it appeared in.

	A group occupying two seats in a roster contributes both, so an
	all-one-group roster counts as strongly as it should: the group really did
	take every seat, and every consequence of that is its own.
	"""
	seats: dict[str, dict[str, list[float]]] = {
		code: {m: [] for m in GROUP_METRICS} for code in entrants
	}
	run_level: dict[str, dict[str, list[float]]] = {
		code: {m: [] for m in RUN_METRICS} for code in entrants
	}
	appearances: dict[str, int] = defaultdict(int)
	seat_counts: dict[str, int] = defaultdict(int)
	exhaustions: dict[str, list] = defaultdict(list)

	for run in runs:
		for seat in run['seats']:
			code = seat['code']
			for metric in GROUP_METRICS:
				seats[code][metric].append(seat[metric])
			seat_counts[code] += 1
		for code in set(run['roster']):
			appearances[code] += 1
			for metric in RUN_METRICS:
				run_level[code][metric].append(run[metric])
			exhaustions[code].append(run['budget_exhausted_on_day'])

	table = []
	for code in entrants:
		if not seat_counts[code]:
			continue
		row = {
			'code': code,
			'runs': appearances[code],
			'seats': seat_counts[code],
			'budget_exhausted': summarise_exhaustion(exhaustions[code]),
		}
		for metric in GROUP_METRICS:
			row[metric] = summarise(seats[code][metric])
		for metric in RUN_METRICS:
			row[metric] = summarise(run_level[code][metric])
		table.append(row)

	table.sort(key=lambda r: r[rank_by]['mean'])
	for position, row in enumerate(table, start=1):
		row['rank'] = position

	return {
		'ranked_by': rank_by,
		'standings': table,
		'matches': [
			{'label': m.label, 'roster': list(m.roster), 'arena': m.arena.label} for m in matches
		],
	}


# ----------------------------------------------------------------- output


def write_outputs(report: dict, out_dir: Path) -> list[Path]:
	out_dir.mkdir(parents=True, exist_ok=True)
	stem = report['tournament']

	json_path = out_dir / f'{stem}.json'
	json_path.write_text(json.dumps(report, indent=2) + '\n')

	standings_path = out_dir / f'{stem}_standings.csv'
	header = ['rank', 'code', 'runs', 'seats', 'runs_exhausted']
	for metric in GROUP_METRICS + RUN_METRICS:
		header += [f'{metric}_{stat}' for stat in ('mean', 'median', 'stddev')]
	with standings_path.open('w', newline='') as fh:
		writer = csv.writer(fh)
		writer.writerow(header)
		for row in report['standings']:
			line = [
				row['rank'],
				row['code'],
				row['runs'],
				row['seats'],
				row['budget_exhausted']['runs_exhausted'],
			]
			for metric in GROUP_METRICS + RUN_METRICS:
				line += [row[metric][s] for s in ('mean', 'median', 'stddev')]
			writer.writerow(line)

	runs_path = out_dir / f'{stem}_runs.csv'
	with runs_path.open('w', newline='') as fh:
		writer = csv.writer(fh)
		writer.writerow(
			[
				'match',
				'arena',
				'roster',
				'seed',
				'seat_index',
				'code',
				'mean_daily_embarrassment',
				'total_embarrassment',
				'sockless_days',
				'spend_per_year',
				'total_spent',
				'budget_exhausted_on_day',
				'faults',
			]
		)
		for run in report['runs']:
			match = report['matches'][run['cell']]
			for seat in run['seats']:
				writer.writerow(
					[
						match['label'],
						match['arena'],
						'+'.join(run['roster']),
						run['seed'],
						seat['index'],
						seat['code'],
						seat['mean_daily_embarrassment'],
						seat['total_embarrassment'],
						seat['sockless_days'],
						run['spend_per_year'],
						run['total_spent'],
						''
						if run['budget_exhausted_on_day'] is None
						else run['budget_exhausted_on_day'],
						run['faults'],
					]
				)

	return [json_path, standings_path, runs_path]


def print_standings(report: dict) -> None:
	print(f'\n{report["tournament"]}  -  ranked by {report["ranked_by"]}')
	print(
		f'{"#":>2}  {"group":<6}  {"runs":>5}  {"seats":>5}  '
		f'{"embarr/day":>16}  {"$/year":>14}  {"sockless":>9}'
	)
	for row in report['standings']:
		emb = row['mean_daily_embarrassment']
		spend = row['spend_per_year']
		sockless = row['sockless_days']
		print(
			f'{row["rank"]:>2}  {row["code"]:<6}  {row["runs"]:>5}  {row["seats"]:>5}  '
			f'{emb["mean"]:>10,.1f} +/-{emb["stddev"]:>4,.0f}  '
			f'{spend["mean"]:>9,.0f} +/-{spend["stddev"]:>3,.0f}  {sockless["mean"]:>9,.1f}'
		)


def print_live_board(
	name: str,
	matches: list[Match],
	entrants: list[str],
	runs: list[dict],
	rank_by: str,
	done: int,
	total: int,
) -> None:
	"""Redraw a text leaderboard. No socks, no GUI - just the ranking so far."""
	sys.stdout.write('\033[2J\033[H')
	print(f'{name}  LIVE  {done}/{total} runs')
	print('Order can jump until every mix has finished. This is not the sock window.\n')
	if not runs:
		print('  waiting for the first match...')
		sys.stdout.flush()
		return
	partial = {
		'tournament': name,
		**rank(matches, runs, entrants, rank_by),
	}
	print_standings(partial)
	seen = {row['code'] for row in partial['standings']}
	for code in entrants:
		if code not in seen:
			print(f'     {code:<6}  (no results yet)')
	sys.stdout.flush()


# ----------------------------------------------------------------- cli


def print_calibration(report: dict) -> None:
	"""Say what the field spends and what budget clears it."""
	print()
	print(f'Measured over {report["runs"]} runs with no budget:')
	print()
	print(f'  worst spend       ${report["max_total_spent"]:,.0f}')
	print(f'  by roster         {"+".join(report["worst_roster"])}')
	print(f'  margin            x{report["margin"]:g}')
	print()
	for label, arena in report['per_arena'].items():
		print(
			f'  {label}: max ${arena["max_total_spent"]:,.0f} '
			f'-> ${arena["recommended_budget"]:,.0f}'
		)
	print()
	print(f'  recommended budget for every arena: ${report["recommended_budget"]:,.0f}')
	print()
	print('  A budget below the worst spend does not make that roster economise - it')
	print('  collapses the drawer and the ranking measures starvation instead of')
	print('  sock matching. Set the arena budgets at or above the figure above.')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description='Rank groups across many shared-drawer runs.')
	parser.add_argument(
		'config', type=Path, help='Tournament description, e.g. configs/tournament.json'
	)
	parser.add_argument('--out-dir', type=Path, default=Path('results'))
	parser.add_argument('--seeds', type=int, nargs='+', help='Override the seed list.')
	parser.add_argument('--days', type=int, help='Override days for every arena.')
	parser.add_argument('--budget', type=float, help='Override the budget for every arena.')
	parser.add_argument(
		'--entrants', nargs='+', help='Restrict to these player codes instead of everything loaded.'
	)
	parser.add_argument(
		'--rank-by',
		default='mean_daily_embarrassment',
		choices=GROUP_METRICS + RUN_METRICS,
		help='Which average to sort the standings on. There is deliberately no combined score, so '
		'the other columns are reported but never folded in.',
	)
	parser.add_argument(
		'--gui',
		action='store_true',
		help='Open a leaderboard window that updates as matches finish. No socks.',
	)
	parser.add_argument(
		'--live',
		action='store_true',
		help='Redraw a text leaderboard after every finished run. No GUI, no socks.',
	)
	parser.add_argument(
		'--calibrate',
		action='store_true',
		help='Do not rank anything. Run every match with no budget, report what the '
		'entrants actually spend, and recommend a budget that clears the cliff for '
		'all of them. Re-run this whenever the field changes.',
	)
	parser.add_argument(
		'--calibrate-margin',
		type=float,
		default=1.10,
		help='Headroom over the worst measured spend when recommending a budget '
		'(default: 1.10, i.e. 10%% clear of the cliff).',
	)
	parser.add_argument('--workers', type=int, default=0)
	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
	args = parse_args(argv)
	if not args.config.exists():
		raise SystemExit(f'no such config: {args.config}')

	config = load_config(args.config)
	if args.seeds:
		config['seeds'] = args.seeds
	if args.entrants:
		config['entrants'] = args.entrants
	if args.days is not None or args.budget is not None:
		config['arenas'] = [
			Arena(
				capacity=a.capacity,
				unit=a.unit,
				days=args.days if args.days is not None else a.days,
				timeout=a.timeout,
				budget=args.budget if args.budget is not None else a.budget,
			)
			for a in config['arenas']
		]

	entrants = entrants_for(config)
	matches, skipped = build_matches(config, entrants)
	for note in skipped:
		print(f'warning: skipping {note}', file=sys.stderr)
	if not matches:
		raise SystemExit('no legal matches: check capacity against unit * n + 10')

	jobs = build_jobs(matches, config['seeds'])
	workers = args.workers or min(len(jobs), __import__('multiprocessing').cpu_count())

	if args.calibrate:
		print(
			f'calibrating {config["name"]}: {len(matches)} matches x '
			f'{len(config["seeds"])} seeds, unlimited budget',
			file=sys.stderr,
		)
		report = calibrate(matches, config['seeds'], workers, args.calibrate_margin)
		print_calibration(report)
		return

	print(
		f'{config["name"]}: {len(entrants)} entrants, {len(matches)} matches x '
		f'{len(config["seeds"])} seeds = {len(jobs)} runs on {workers} worker(s)',
		file=sys.stderr,
	)

	board = None
	if args.gui:
		from ui.leaderboard import Leaderboard

		board = Leaderboard(
			title=config['name'],
			rank_by=args.rank_by,
			total=len(jobs),
			entrants=entrants,
		)

	partial: list[dict] = []

	def apply_result(_result: dict, n: int, total: int) -> None:
		partial.append(_result)
		standing = rank(matches, partial, entrants, args.rank_by)
		pending = [c for c in entrants if c not in {row['code'] for row in standing['standings']}]
		last = '+'.join(_result['roster']) + f'  seed {_result["seed"]}'
		if board is not None:
			board.update(standing['standings'], n, pending, last_match=last)
		elif args.live:
			print_live_board(
				config['name'],
				matches,
				entrants,
				partial,
				args.rank_by,
				n,
				total,
			)

	if board is not None:
		import pygame

		pace = 0.0 if pygame.display.get_driver() == 'dummy' else 0.12
		runs = execute_live(
			jobs,
			workers,
			worker=_run_match,
			on_progress=apply_result,
			idle=lambda: board.tick(),
			pace=pace,
		)
	else:
		runs = execute(
			jobs,
			workers,
			worker=_run_match,
			on_progress=apply_result if args.live else None,
		)
	report = rank(matches, runs, entrants, args.rank_by)
	report = {
		'tournament': config['name'],
		'description': config['description'],
		'config': config['source'],
		'entrants': entrants,
		'seeds': config['seeds'],
		'arenas': [a.label for a in config['arenas']],
		'roommates': config['roommates'],
		**report,
		'runs': runs,
	}
	written = write_outputs(report, args.out_dir)

	print_standings(report)
	print('\nwrote:')
	for path in written:
		print(f'  {path}')

	if board is not None:
		board.update(report['standings'], len(jobs), [])
		board.wait_to_close()


if __name__ == '__main__':
	main()
