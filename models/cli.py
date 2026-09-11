import argparse
from dataclasses import dataclass


@dataclass
class Settings:
	players: list[tuple[str, int]]
	capacity: int
	selection_unit: int
	days: int
	seed: int
	budget: float | None
	timeout: float
	summary_only: bool
	gui: bool
	log: str | None


def settings(argv: list[str] | None = None) -> Settings:
	parser = argparse.ArgumentParser(description='Run a sock drawer simulation.')
	parser.add_argument(
		'--player',
		action='append',
		nargs=2,
		metavar=('CODE', 'COUNT'),
		help='Add COUNT roommates running player CODE (e.g. --player g 3). Repeatable.',
	)
	parser.add_argument('-C', '--capacity', type=int, default=40, help='Drawer capacity C.')
	parser.add_argument(
		'--unit',
		type=int,
		choices=(4, 5),
		default=4,
		dest='selection_unit',
		help='Socks drawn per roommate per day.',
	)
	parser.add_argument('--days', type=int, default=360, help='Days to simulate.')
	parser.add_argument('--seed', type=int, default=4444, help='Random seed.')
	parser.add_argument(
		'--budget',
		type=float,
		default=None,
		help='Total dollars available for the whole run. Unlimited by default. Once what is '
		'left cannot cover a $10 six-pack the drawer only shrinks, and roommates start '
		'going sockless.',
	)
	parser.add_argument(
		'--timeout',
		type=float,
		default=1.0,
		help='Per-call wall-clock budget for player code, in seconds. 0 disables.',
	)
	parser.add_argument(
		'--summary-only',
		action='store_true',
		help="Discard each day's DayRecord once it has been scored. The results JSON is "
		'unchanged; a long run just stops holding one record per day in memory.',
	)
	parser.add_argument('--gui', action='store_true', help='Launch the visualizer.')
	parser.add_argument(
		'--log',
		default='',
		metavar='PATH',
		help='Write a per-day debug log (default: logs/socks-*.log). Pass a path to choose '
		'the file. Sweeps and the tournament do not write one.',
	)
	parser.add_argument(
		'--no-log',
		action='store_true',
		help='Do not write a debug log.',
	)

	args = parser.parse_args(argv)

	pairs: list[tuple[str, int]] = []
	for code, count in args.player or [('r', '4')]:
		pairs.append((code, int(count)))

	return Settings(
		players=pairs,
		capacity=args.capacity,
		selection_unit=args.selection_unit,
		days=args.days,
		seed=args.seed,
		budget=args.budget,
		timeout=args.timeout,
		summary_only=args.summary_only,
		gui=args.gui,
		log=None if args.no_log else args.log,
	)
