"""What happens when a group commits something broken.

The live-demo rule is the whole point of this file: the TA runs everyone's
code, from whatever they pushed that morning, in front of the class.
No single group may be able to crash the run, hang it, corrupt the drawer, or
disturb anybody else's results.

Each scenario asserts the same four things:

  1. the simulation runs to completion
  2. the misbehaviour is recorded in DayRecord.faults, on the days it happened
  3. the other roommates finish bit-identical to a control run
  4. the drawer invariant holds on every single day, not just at the end

Point 3 is exact rather than approximate because of ``Forfeiter``: it does what
the engine substitutes on a fault, so a control run consumes the RNG exactly as
an always-faulting run does. If a fault ever perturbed the shared drawer, the
honest roommates' numbers would move and these tests would say so.
"""

import signal

import pytest

from core.engine import Engine
from models.player import Player, Selection
from players.greedy_player import GreedyPlayer
from tests.fixtures import adversarial as adv

DAYS = 40
SEED = 17
CAPACITY = 40
UNIT = 4

HAS_ALARM = hasattr(signal, 'SIGALRM')


def play(rogue: type[Player], *, days: int = DAYS, timeout: float = 0.0) -> Engine:
	"""Run `rogue` alongside two honest roommates, checking the drawer daily."""
	engine = Engine(
		players=[rogue, GreedyPlayer, GreedyPlayer],
		capacity=CAPACITY,
		selection_unit=UNIT,
		days=days,
		seed=SEED,
		timeout=timeout,
	)
	floor = engine.selection_unit * engine.roommates
	while engine.step() is not None:
		assert len(engine.drawer) >= floor, f'drawer starved on day {engine.day}'
	return engine


def control(*, days: int = DAYS, timeout: float = 0.0) -> dict:
	return play(adv.Forfeiter, days=days, timeout=timeout).results()


def faulting_days(engine: Engine) -> list[int]:
	return [record.day for record in engine.records if record.faults]


def assert_contained(engine: Engine, reference: dict, *, expect_fault_days: int) -> None:
	"""The four guarantees, in one place."""
	results = engine.results()

	assert engine.day == engine.days, 'simulation did not run to completion'
	assert len(faulting_days(engine)) == expect_fault_days

	# Faults are attributed to the culprit and nobody else.
	rogue_name = engine.player_names[0]
	assert all(f.startswith(f'{rogue_name}: ') for f in results['faults'])

	# The honest roommates are untouched, to the last float.
	for i in (1, 2):
		assert results['players'][i] == reference['players'][i], f'roommate {i} was disturbed'

	assert results['total_spent'] == reference['total_spent']
	assert len(engine.drawer) >= engine.selection_unit * engine.roommates


# ---------------------------------------------------------------- the control


def test_the_control_itself_is_clean():
	"""If Forfeiter faulted, every comparison below would be meaningless."""
	engine = play(adv.Forfeiter)
	assert engine.results()['faults'] == []
	assert faulting_days(engine) == []


def test_fixtures_are_not_discovered_as_a_group():
	"""These live under tests/ so the registry cannot mistake them for a real
	group. Nothing here may ever appear in a run."""
	from core.registry import discover

	loaded, errors = discover()

	# Not "the registry contains exactly the baselines" - real group
	# directories come and go all term, and this test is not about them. What
	# must hold is that nothing in tests/fixtures is reachable as a player.
	fixture_names = {name for name in vars(adv) if isinstance(getattr(adv, name), type)}
	loaded_names = {cls.__name__ for cls in loaded.values()}
	assert not (fixture_names & loaded_names)
	assert all(not cls.__module__.startswith('tests.') for cls in loaded.values())
	assert not any('adversarial' in err.message for err in errors)
	assert {'g', 'r'} <= set(loaded)


# ---------------------------------------------------------------- crashes


def test_raises_on_some_turns_but_not_others():
	"""The intermittent case: a fault on even days, a real move on odd ones."""
	engine = play(adv.SometimesRaises)
	expected = [d for d in range(1, DAYS + 1) if d % 2 == 0]

	assert faulting_days(engine) == expected
	assert all('ZeroDivisionError' in f for f in engine.results()['faults'])
	# On its good days it really did play: the engine still scored it.
	assert len(engine.embarrassment[0]) == DAYS


def test_returns_none():
	engine = play(adv.ReturnsNone)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert "'NoneType' object has no attribute 'wear'" in engine.results()['faults'][0]


def test_returns_a_non_selection_object():
	engine = play(adv.ReturnsJunk)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert 'AttributeError' in engine.results()['faults'][0]


# ---------------------------------------------------------------- wrong types


def test_numpy_integers_are_rejected():
	"""np.int64 is not a Python int, so numpy indices forfeit the turn even
	when the numbers themselves are in range. Pinned because it is the most
	likely way a working strategy stops working."""
	pytest.importorskip('numpy')

	engine = play(adv.NumpyIndices)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert engine.results()['faults'][0].endswith(
		'wear indices must be plain ints, not numpy.int64'
	)


def test_float_indices_are_rejected():
	engine = play(adv.FloatIndices)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert engine.results()['faults'][0].endswith('wear indices must be plain ints, not float')


def test_the_type_error_does_not_masquerade_as_a_range_error():
	"""0 and 1 are in range whatever their type. Reporting np.int64 indices as
	'must lie in [0, 4)' sent groups looking for an off-by-one that was not
	there, so the two verdicts are deliberately different sentences."""
	pytest.importorskip('numpy')

	numpy_fault = play(adv.NumpyIndices).results()['faults'][0]
	range_fault = play(adv.OutOfRangeIndices).results()['faults'][0]

	assert 'must lie in' not in numpy_fault
	assert 'must be plain ints' not in range_fault
	assert range_fault.endswith('wear indices must lie in [0, 4)')


# ------------------------------------------------------- broken constructors


def test_a_constructor_that_raises_does_not_end_the_run():
	"""The engine builds players before day 1, outside the per-turn guard. A
	group whose __init__ raised used to end the whole run with a traceback and
	no results for anybody."""
	engine = play(adv.RaisesInConstructor)
	assert_contained(engine, control(), expect_fault_days=DAYS)

	faults = engine.results()['faults']
	assert 'could not be constructed' in faults[0]
	assert 'bad config file' in faults[0]


@pytest.mark.skipif(not HAS_ALARM, reason='timeout enforcement needs SIGALRM')
def test_a_constructor_that_hangs_does_not_freeze_the_run():
	"""The one that cannot be recovered from by hand at the front of a class."""
	engine = play(adv.HangsInConstructor, days=5, timeout=0.05)

	assert engine.day == engine.days
	assert 'could not be constructed' in engine.results()['faults'][0]


def test_an_unbuildable_group_leaves_the_others_bit_identical():
	"""Replacing it with a stand-in keeps the roster length, so the drawer
	arithmetic and the RNG draw exactly as they would have."""
	engine = play(adv.RaisesInConstructor)
	reference = control()

	for i in (1, 2):
		assert engine.results()['players'][i] == reference['players'][i]


# ---------------------------------------------------------------- mutation


def test_mutating_the_offered_socks_is_contained():
	"""``offered`` is a tuple, so the attempt raises rather than succeeding."""
	engine = play(adv.MutatesOffered)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert 'TypeError' in engine.results()['faults'][0]


def test_mutating_the_turn_context_is_contained():
	"""TurnContext is frozen: a player cannot rewrite its own turn."""
	engine = play(adv.MutatesTurnContext)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert 'FrozenInstanceError' in engine.results()['faults'][0]


def test_mutating_the_history_snapshot_is_contained():
	engine = play(adv.MutatesHistory)
	assert_contained(engine, control(), expect_fault_days=DAYS)
	assert 'AttributeError' in engine.results()['faults'][0]


# ---------------------------------------------------------------- timeouts


@pytest.mark.skipif(not HAS_ALARM, reason='timeouts need SIGALRM')
def test_sleeping_just_under_the_budget_does_not_fault():
	engine = play(adv.SleepsUnderBudget, days=4, timeout=1.0)
	assert engine.results()['faults'] == []
	assert faulting_days(engine) == []
	assert len(engine.embarrassment[0]) == 4


@pytest.mark.skipif(not HAS_ALARM, reason='timeouts need SIGALRM')
def test_sleeping_over_the_budget_forfeits_every_turn():
	engine = play(adv.SleepsOverBudget, days=3, timeout=0.05)
	assert_contained(engine, control(days=3, timeout=0.05), expect_fault_days=3)
	assert all('time budget' in f for f in engine.results()['faults'])


@pytest.mark.skipif(not HAS_ALARM, reason='timeouts need SIGALRM')
def test_a_hanging_player_cannot_stall_the_run():
	"""The clock is wall-clock, so the run finishes in roughly days * timeout
	rather than never."""
	import time

	start = time.perf_counter()
	engine = play(adv.SleepsOverBudget, days=3, timeout=0.05)
	elapsed = time.perf_counter() - start

	assert engine.day == 3
	assert elapsed < 5.0, f'run took {elapsed:.1f}s despite a 0.05s budget'


# ---------------------------------------------------------------- class state


def test_class_state_does_not_expose_another_roommates_data():
	"""Two roommates running the same class share class attributes - that is
	Python, not a leak. What must not happen is either of them seeing anything
	belonging to the third roommate, who runs somebody else's code."""
	adv.ClassStateStasher.reset()

	engine = Engine(
		players=[adv.ClassStateStasher, adv.ClassStateStasher, GreedyPlayer],
		capacity=CAPACITY,
		selection_unit=UNIT,
		days=10,
		seed=SEED,
		timeout=0,
	)
	engine.run()
	seen = adv.ClassStateStasher.SEEN

	# The shared attribute really is shared: both instances wrote to it.
	assert {index for _, index, _ in seen} == {0, 1}
	assert len(seen) == 20

	# But nothing belonging to roommate 2 is in there, and every observation is
	# plain shade integers rather than anything the engine owns.
	assert all(index != 2 for _, index, _ in seen)
	assert all(isinstance(shade, int) for _, _, shades in seen for shade in shades)

	assert all(len(shades) == UNIT for _, _, shades in seen)

	# Nor is there a route to roommate 2: nothing reachable from a stasher
	# instance refers to the engine or to another player. Comparing shade
	# values would prove nothing, since two roommates can be dealt the same
	# shades by chance - the question is whether a reference exists at all.
	def reachable(obj, depth=0, seen_ids=None):
		if seen_ids is None:
			seen_ids = set()
		if id(obj) in seen_ids or depth > 3:
			return
		seen_ids.add(id(obj))
		yield obj
		for value in getattr(obj, '__dict__', {}).values():
			yield from reachable(value, depth + 1, seen_ids)

	others = [p for p in engine.players if p.index == 2]
	for player in engine.players[:2]:
		refs = list(reachable(player))
		assert engine not in refs
		assert not any(other in refs for other in others)


def test_instances_get_their_own_identity():
	"""Class state is shared; PlayerSnapshot is not."""
	adv.ClassStateStasher.reset()
	engine = Engine(
		players=[adv.ClassStateStasher] * 3,
		capacity=CAPACITY,
		selection_unit=UNIT,
		days=2,
		seed=SEED,
		timeout=0,
	)
	engine.run()
	assert len({p.index for p in engine.players}) == 3
	assert len({p.id for p in engine.players}) == 3


# ---------------------------------------------------------------- accepted, not faulted


def test_repeated_discard_indices_are_deduplicated_not_faulted():
	"""Documented behaviour, and deliberately not a fault: __validate runs the
	discard list through dict.fromkeys, so naming index 2 three times is the
	same request as naming it once. Nothing is discarded twice and the drawer
	stays consistent."""
	engine = play(adv.RepeatedDiscard)

	assert engine.results()['faults'] == []
	assert faulting_days(engine) == []
	assert engine.day == DAYS
	assert len(engine.drawer) >= engine.selection_unit * engine.roommates

	# Naming index 2 three times must be indistinguishable from naming it once,
	# down to the last float - if it were not, the extra names would be
	# discarding socks that are no longer there.
	once = play(adv.SingleDiscard).results()
	repeated = engine.results()

	def scores(r):
		return [{k: v for k, v in p.items() if k != 'name'} for p in r['players']]

	assert scores(repeated) == scores(once)
	assert repeated['total_spent'] == once['total_spent']
	assert repeated['drawer_composition'] == once['drawer_composition']
	assert repeated['pending_discards'] == once['pending_discards']


def test_validated_selection_is_deduplicated():
	engine = Engine(players=[GreedyPlayer], capacity=40, selection_unit=4, days=1, seed=1)
	cleaned = engine._Engine__validate(Selection(wear=(0, 1), discard=(2, 3, 2, 3)), 4)
	assert cleaned.discard == (2, 3)
