import json
import sys

from core.engine import Engine
from core.registry import discover
from models.cli import settings
from models.player import Player


def build_roster(requested: list[tuple[str, int]]) -> list[type[Player]]:
	available, errors = discover()

	for err in errors:
		print(f"warning: player '{err.code}' failed to load - {err.message}", file=sys.stderr)

	roster: list[type[Player]] = []
	for code, count in requested:
		if code not in available:
			print(f"warning: unknown or unloadable player '{code}', skipping", file=sys.stderr)
			continue
		roster.extend([available[code]] * count)

	if not roster:
		codes = ', '.join(sorted(available)) or 'none'
		raise SystemExit(f'No usable players selected. Available codes: {codes}')

	return roster


def _open_log(args, engine):
	"""Best-effort. A missing logs/ directory must not take down a live demo."""
	if args.log is None:
		return None
	from core.runlog import RunLog

	try:
		log = RunLog.create(
			args.log,
			engine,
			seed=args.seed,
			budget=args.budget,
		)
	except OSError as exc:
		print(f'warning: could not write log - {exc}', file=sys.stderr)
		return None
	print(f'log: {log.path}', file=sys.stderr)
	return log


def main() -> None:
	args = settings()
	roster = build_roster(args.players)

	engine = Engine(
		players=roster,
		capacity=args.capacity,
		selection_unit=args.selection_unit,
		days=args.days,
		seed=args.seed,
		timeout=args.timeout,
		budget=args.budget,
		keep_records=not args.summary_only,
	)

	log = _open_log(args, engine)
	on_day = None
	if log is not None:
		from core.runlog import bind

		on_day = bind(log, engine)

	try:
		if args.gui:
			from ui.gui import run_gui

			run_gui(engine, on_day=on_day)
		else:
			print(json.dumps(engine.run(on_day=on_day), indent=2))
	finally:
		if log is not None:
			log.finish(engine)


if __name__ == '__main__':
	main()
