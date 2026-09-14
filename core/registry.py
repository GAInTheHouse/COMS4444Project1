"""Dynamic player discovery.

The 2025 ``main.py`` imported all thirteen student modules at the top of the
file. One group committing a syntax error meant nobody could start the
simulator. Here each player module is imported lazily and independently, so a
broken group is reported and skipped.

Convention:
    players/random_player.py      -> code 'r'
    players/greedy_player.py      -> code 'g'
    players/player_<k>/player.py  -> code '<k>', class Player<k>

There is no cap on ``k``. A group drops ``players/player_12/`` in and it is
discovered the same way as ``player_1``. Tournament default entrants are
whatever ``discover()`` loaded that day.
"""

import importlib
import pkgutil
import re
from dataclasses import dataclass
from pathlib import Path

from models.player import Player

BUILTIN = {
	'r': ('players.random_player', 'RandomPlayer'),
	'g': ('players.greedy_player', 'GreedyPlayer'),
}

_GROUP_DIR = re.compile(r'^player_(\d+)$')

# Resolved from this file rather than the working directory, so discovery finds
# the same groups no matter where the simulator is launched from.
_PLAYERS_DIR = Path(__file__).resolve().parent.parent / 'players'


@dataclass
class LoadError:
	code: str
	message: str


def _missing_init_errors(found: dict[str, tuple[str, str]]) -> list[LoadError]:
	"""Report ``player_<k>`` directories that have no ``__init__.py``.

	``pkgutil.iter_modules`` only reports directories containing one, so such a
	group is not discovered at all - it is not reported as broken, it simply
	never turns up, and the group sees "unknown player" instead of the real
	problem. Matching on the directory name would be the wrong fix, because it
	would start importing things that are not packages; naming the omission is
	the right one.
	"""
	errors: list[LoadError] = []
	if not _PLAYERS_DIR.is_dir():
		return errors

	for entry in sorted(_PLAYERS_DIR.iterdir()):
		match = _GROUP_DIR.match(entry.name)
		if not match or not entry.is_dir():
			continue
		if match.group(1) in found or (entry / '__init__.py').exists():
			continue
		errors.append(
			LoadError(
				code=match.group(1),
				message=f'players/{entry.name}/ has no __init__.py, so it is invisible to '
				'discovery - add an empty one',
			)
		)
	return errors


def discover() -> tuple[dict[str, type[Player]], list[LoadError]]:
	"""Return the loadable players keyed by CLI code, plus whatever failed."""
	loaded: dict[str, type[Player]] = {}
	errors: list[LoadError] = []

	targets = dict(BUILTIN)
	for module in pkgutil.iter_modules([str(_PLAYERS_DIR)]):
		match = _GROUP_DIR.match(module.name)
		if module.ispkg and match:
			group = match.group(1)
			targets[group] = (f'players.{module.name}.player', f'Player{group}')

	errors.extend(_missing_init_errors(targets))

	for code, (module_path, class_name) in sorted(targets.items()):
		try:
			module = importlib.import_module(module_path)
			cls = getattr(module, class_name)
			if not issubclass(cls, Player):
				raise TypeError(f'{class_name} does not subclass Player')
			loaded[code] = cls
		except Exception as exc:
			errors.append(LoadError(code=code, message=f'{type(exc).__name__}: {exc}'))

	return loaded, errors
