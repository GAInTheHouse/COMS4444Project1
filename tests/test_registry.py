"""Discovery must survive whatever the groups commit.

The 2025 main.py imported all thirteen student modules at the top of the file,
so one syntax error stopped the whole class. These tests pin the behaviour that
replaced it: every group is imported independently, a broken one is reported
and skipped, and everyone else still runs.

The tests write real directories under players/ rather than monkeypatching,
because the thing being tested is the actual pkgutil/importlib path - a mock
would not have caught that a directory without __init__.py is invisible.
"""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from core.registry import discover
from models.player import Player

PLAYERS = Path(__file__).resolve().parent.parent / 'players'

VALID = """
from models.player import Player as BasePlayer, Selection


class Player{code}(BasePlayer):
	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=())
"""

SYNTAX_ERROR = """
from models.player import Player as BasePlayer


class Player{code}(BasePlayer)      # missing colon, and no body
	def select_socks(self, offered, turn)
"""

NOT_A_PLAYER = '''
class Player{code}:
	"""Forgot to subclass Player."""

	def select_socks(self, offered, turn):
		return None
'''

WRONG_CLASS_NAME = """
from models.player import Player as BasePlayer, Selection


class MyGreatSockStrategy(BasePlayer):
	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=())
"""


@pytest.fixture
def group(request):
	"""Create throwaway group directories, and always clean them up.

	Codes in the 90s so a real players/player_<k> checkout is never touched.
	"""
	created: list[Path] = []

	def make(code: str, source: str | None, package: bool = True) -> Path:
		directory = PLAYERS / f'player_{code}'
		directory.mkdir(parents=True, exist_ok=True)
		created.append(directory)
		if package:
			(directory / '__init__.py').write_text('')
		if source is not None:
			(directory / 'player.py').write_text(source.format(code=code))
		importlib.invalidate_caches()
		return directory

	yield make

	for directory in created:
		code = directory.name.removeprefix('player_')
		mod = f'players.player_{code}'
		for name in [m for m in sys.modules if m == mod or m.startswith(mod + '.')]:
			del sys.modules[name]
		shutil.rmtree(directory, ignore_errors=True)
	importlib.invalidate_caches()


def codes(loaded: dict) -> set[str]:
	return set(loaded)


# ---------------------------------------------------------------- baseline


def test_builtin_baselines_always_load():
	loaded, _ = discover()
	assert loaded['r'].__name__ == 'RandomPlayer'
	assert loaded['g'].__name__ == 'GreedyPlayer'


def test_the_template_is_not_discovered():
	"""players/player_template exists for groups to copy. It must never turn
	up in a run as a competitor."""
	loaded, errors = discover()
	assert 'template' not in loaded
	assert all(err.code != 'template' for err in errors)


# ---------------------------------------------------------------- valid groups


def test_valid_group_loads_under_its_numeric_code(group):
	group('91', VALID)
	loaded, errors = discover()

	assert '91' in loaded, [(e.code, e.message) for e in errors]
	assert loaded['91'].__name__ == 'Player91'
	assert issubclass(loaded['91'], Player)


def test_group_numbers_are_not_capped_at_ten(group):
	"""Folders are discovered by name, not from a 1-10 list. Two-digit and
	three-digit group numbers are ordinary competitors."""
	group('94', VALID)
	group('100', VALID)
	loaded, errors = discover()
	assert {'94', '100'} <= codes(loaded), [(e.code, e.message) for e in errors]
	assert loaded['100'].__name__ == 'Player100'


def test_several_groups_load_side_by_side(group):
	for code in ('91', '92', '93'):
		group(code, VALID)
	loaded, _ = discover()
	assert {'91', '92', '93'} <= codes(loaded)


def test_a_discovered_group_actually_runs(group):
	"""Loading is not enough; the class has to survive being constructed and
	stepped by the engine."""
	from core.engine import Engine

	group('91', VALID)
	loaded, _ = discover()
	engine = Engine(players=[loaded['91']] * 2, capacity=40, selection_unit=4, days=5, seed=1)
	results = engine.run()
	assert not results['faults']


# ---------------------------------------------------------------- broken groups


def test_syntax_error_is_reported_and_skipped(group):
	group('91', SYNTAX_ERROR)
	loaded, errors = discover()

	assert '91' not in loaded
	reported = {err.code: err.message for err in errors}
	assert '91' in reported
	assert 'SyntaxError' in reported['91']


def test_one_broken_group_does_not_stop_the_others(group):
	"""The whole reason discovery is lazy and per-module. A bad commit from one
	group must not cost the class its demo."""
	group('91', SYNTAX_ERROR)
	group('92', VALID)
	group('93', VALID)

	loaded, errors = discover()
	assert {'92', '93'} <= codes(loaded)
	assert '91' not in loaded
	assert {'r', 'g'} <= codes(loaded)
	assert [err.code for err in errors if err.code.startswith('9')] == ['91']


def test_class_not_subclassing_player_is_rejected(group):
	group('91', NOT_A_PLAYER)
	loaded, errors = discover()

	assert '91' not in loaded
	reported = {err.code: err.message for err in errors}
	assert 'does not subclass Player' in reported['91']


def test_wrong_class_name_is_reported(group):
	"""The registry looks for Player<k> exactly. Naming the class anything else
	is the most common way a group's code fails to appear."""
	group('91', WRONG_CLASS_NAME)
	loaded, errors = discover()

	assert '91' not in loaded
	reported = {err.code: err.message for err in errors}
	assert 'AttributeError' in reported['91']


def test_missing_player_module_is_reported(group):
	"""A directory with an __init__.py but no player.py."""
	group('91', None)
	loaded, errors = discover()

	assert '91' not in loaded
	reported = {err.code: err.message for err in errors}
	assert 'ModuleNotFoundError' in reported['91']


def test_group_dir_without_init_is_reported(group):
	"""pkgutil.iter_modules only reports directories containing __init__.py, so
	a group that omits it is still not discovered. What it must not be is
	silent: without a warning the group is told "unknown player" and goes
	looking for a problem in code that is perfectly fine."""
	group('91', VALID, package=False)
	loaded, errors = discover()

	assert '91' not in loaded
	reported = {err.code: err.message for err in errors}
	assert '__init__.py' in reported['91']


def test_a_group_with_its_init_is_not_warned_about(group):
	"""The warning must fire on the omission, not on every group."""
	group('91', VALID)
	_, errors = discover()

	assert all('__init__.py' not in err.message for err in errors)
