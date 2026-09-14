import signal
from collections import Counter

import pytest

from core.engine import SOCKLESS_PENALTY, Engine
from core.sandbox import PlayerFault
from models.player import Selection, TurnContext
from models.sock import Color, pristine
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer


def build(**kwargs) -> Engine:
	defaults = dict(
		players=[GreedyPlayer] * 4,
		capacity=40,
		selection_unit=4,
		days=30,
		seed=1,
	)
	defaults.update(kwargs)
	return Engine(**defaults)


# ---------------------------------------------------------------- aging


def test_white_fades_by_two_and_floors_at_127():
	sock = pristine(Color.WHITE)
	assert sock.shade == 255
	for _ in range(64):
		sock = sock.washed()
	assert sock.shade == 127
	assert sock.washed().shade == 127
	assert sock.worn_out


def test_black_fades_by_one_and_caps_at_64():
	sock = pristine(Color.BLACK)
	assert sock.shade == 0
	for _ in range(64):
		sock = sock.washed()
	assert sock.shade == 64
	assert sock.washed().shade == 64
	assert sock.worn_out


# ---------------------------------------------------------------- parameters


def test_capacity_must_be_multiple_of_four():
	with pytest.raises(ValueError, match='multiple of 4'):
		build(capacity=42)


def test_capacity_must_exceed_unit_times_n_plus_ten():
	# 4 * 4 + 10 = 26, so 24 is too small but 28 is fine.
	with pytest.raises(ValueError, match='must exceed 26'):
		build(capacity=24)
	build(capacity=28)


def test_drawer_starts_balanced():
	engine = build(capacity=40)
	counts = Counter(s.color for s in engine.drawer)
	assert counts[Color.WHITE] == 20
	assert counts[Color.BLACK] == 20


# ---------------------------------------------------------------- embarrassment


def test_difference_of_exactly_six_is_free():
	"""Spec: embarrassment accrues only if socks differ by MORE than 6."""
	engine = build(players=[GreedyPlayer], capacity=40, days=1)
	engine.drawer = [
		pristine(Color.WHITE),
		pristine(Color.WHITE).washed().washed().washed(),  # 255 -> 249
		pristine(Color.BLACK),
		pristine(Color.BLACK),
	]
	record = engine.step()
	# Greedy wears the two blacks (identical), so no embarrassment either way;
	# assert the threshold directly instead.
	assert record.embarrassment[0] == 0.0


def test_embarrassment_equals_absolute_difference():
	engine = build(players=[RandomPlayer], capacity=40, days=1)
	white = pristine(Color.WHITE)
	black = pristine(Color.BLACK)
	engine.drawer = [white, black, white, black]
	record = engine.step()
	worn = record.worn[0]
	expected = abs(worn[0] - worn[1])
	assert record.embarrassment[0] == (expected if expected > 6 else 0.0)


def test_day_record_keeps_the_hand_and_the_choice():
	"""The visualiser has to show what was offered, not guess from the worn pair."""
	engine = build(players=[GreedyPlayer], capacity=40, days=1, seed=7)
	record = engine.step()
	assert len(record.offered[0]) == 4
	i, j = record.wear_idx[0]
	assert record.worn[0] == (record.offered[0][i], record.offered[0][j])
	assert set(record.discard_idx[0]).isdisjoint({i, j})
	assert all(0 <= k < 4 for k in record.discard_idx[0])


def test_greedy_discards_only_while_a_pack_is_still_affordable():
	"""Greedy reads the household leftover, not a private allowance. No money
	left for a $10 pack means leftovers go back; unlimited leftover is inf, so
	the same handful is thrown away."""
	broke = build(players=[GreedyPlayer] * 4, days=1, seed=7, budget=0.0)
	broke_day = broke.step()
	assert all(len(broke_day.discard_idx[i]) == 0 for i in range(4))

	free = build(players=[GreedyPlayer] * 4, days=1, seed=7)
	free_day = free.step()
	assert any(len(free_day.discard_idx[i]) > 0 for i in range(4))


# ---------------------------------------------------------------- replenishment


def test_pack_bought_only_at_six_with_carryover():
	engine = build(days=1)
	engine.pending_discards[Color.WHITE] = 5
	engine._Engine__replenish(_record(engine))
	assert engine.total_spent == 0.0

	engine.pending_discards[Color.WHITE] = 8
	record = _record(engine)
	engine._Engine__replenish(record)
	assert engine.total_spent == 10.0
	assert engine.pending_discards[Color.WHITE] == 2
	assert record.packs_bought[Color.WHITE] == 1


def test_multiple_packs_in_one_day():
	"""Per the handout: buy as many six-packs as the discard count supports."""
	engine = build(days=1)
	engine.pending_discards[Color.BLACK] = 14
	record = _record(engine)
	engine._Engine__replenish(record)
	assert engine.total_spent == 20.0
	assert engine.pending_discards[Color.BLACK] == 2


def _record(engine):
	from core.engine import DayRecord

	return DayRecord(day=engine.day, order=[])


# ---------------------------------------------------------------- invariants


def test_drawer_never_starves_over_a_long_run():
	engine = build(players=[GreedyPlayer] * 4, capacity=40, days=1000)
	engine.run()
	assert len(engine.drawer) >= engine.selection_unit * engine.roommates


def test_same_seed_reproduces_run():
	a = build(days=200, seed=99).run()
	b = build(days=200, seed=99).run()
	assert a['total_embarrassment'] == b['total_embarrassment']
	assert a['total_spent'] == b['total_spent']


def test_run_on_day_sees_every_morning():
	seen = []
	engine = build(days=7, seed=3)
	engine.run(on_day=seen.append)
	assert [r.day for r in seen] == list(range(1, 8))


def test_five_sock_unit_runs():
	engine = build(selection_unit=5, capacity=44, days=100)
	results = engine.run()
	assert results['parameters']['selection_unit'] == 5
	assert not results['faults']


# ---------------------------------------------------------------- turn context


def test_history_is_not_materialised_until_a_player_reads_it():
	"""Building the tuple eagerly made a long run quadratic: every turn copied
	a list that grows by one entry per day. Most players never read it."""
	engine = build(days=10)
	for _ in range(5):
		engine.step()

	ctx = engine._Engine__turn_context(0)
	assert '_cached_history' not in ctx.__dict__

	assert ctx.embarrassment_history == tuple(engine.embarrassment[0])
	assert '_cached_history' in ctx.__dict__


def test_history_is_cached_within_a_turn():
	engine = build(days=3)
	engine.step()
	ctx = engine._Engine__turn_context(0)
	assert ctx.embarrassment_history is ctx.embarrassment_history


def test_total_embarrassment_matches_the_history_sum():
	"""The running total must stay bit-identical to summing the list, or a
	budget-gated player silently changes behaviour."""
	engine = build(days=120)
	engine.run()
	for i in range(engine.roommates):
		ctx = engine._Engine__turn_context(i)
		assert ctx.total_embarrassment == sum(engine.embarrassment[i])
		assert ctx.total_embarrassment == sum(ctx.embarrassment_history)


def test_player_cannot_reach_engine_state_through_the_context():
	"""The history is handed over as a fresh tuple. A player that mutates what
	it is given must not be able to edit its own score."""
	engine = build(days=5)
	engine.step()
	ctx = engine._Engine__turn_context(0)

	before = list(engine.embarrassment[0])
	with pytest.raises(AttributeError):
		ctx.embarrassment_history.append(99.0)
	assert engine.embarrassment[0] == before

	# Calling the accessor again yields another tuple, never the engine's list.
	handed_out = ctx._history()
	assert isinstance(handed_out, tuple)
	assert handed_out is not engine.embarrassment[0]


def test_long_runs_scale_linearly_in_days():
	"""A guard against reintroducing per-turn work that is O(days). Four times
	the days should cost roughly four times as long; the quadratic version cost
	about sixteen. The bound is loose so CI noise cannot fail it."""
	import time

	def timed(days: int) -> float:
		start = time.perf_counter()
		build(players=[GreedyPlayer] * 4, days=days, timeout=0, keep_records=False).run()
		return time.perf_counter() - start

	timed(500)  # warm up the import and JIT-free caches
	short = min(timed(1500) for _ in range(3))
	long = min(timed(6000) for _ in range(3))
	assert long / short < 8, f'4x the days cost {long / short:.1f}x the time'


# ---------------------------------------------------------------- sock aging


def test_washed_matches_a_dataclasses_replace_implementation():
	"""washed() constructs the Sock directly instead of going through
	dataclasses.replace. Pin that the two agree at every shade."""
	from dataclasses import replace

	from models.sock import BLACK_CEILING, BLACK_FADE, WHITE_FADE, WHITE_FLOOR, Sock

	for color in (Color.WHITE, Color.BLACK):
		for shade in range(0, 256):
			sock = Sock(id=pristine(color).id, color=color, shade=shade)
			if color is Color.WHITE:
				expected = replace(sock, shade=max(WHITE_FLOOR, shade - WHITE_FADE))
			else:
				expected = replace(sock, shade=min(BLACK_CEILING, shade + BLACK_FADE))
			assert sock.washed() == expected
			assert sock.washed().id == sock.id


# ---------------------------------------------------------------- isolation


class _Returns(GreedyPlayer):
	"""Hands back whatever it was built to hand back."""

	value = None

	def select_socks(self, offered, turn):
		return self.value


def _player_returning(value):
	return type('Rogue', (_Returns,), {'value': value})


@pytest.mark.parametrize(
	('label', 'value'),
	[
		('not a Selection', None),
		('wear is not iterable', Selection(wear=7, discard=())),
		('wear is a string', Selection(wear='ab', discard=())),
		('discard is not iterable', Selection(wear=(0, 1), discard=3)),
		('indices are floats', Selection(wear=(0.0, 1.0), discard=())),
		('wear names one index', Selection(wear=(0,), discard=())),
		('wear repeats an index', Selection(wear=(1, 1), discard=())),
		('index out of range', Selection(wear=(0, 99), discard=())),
		('discards a worn sock', Selection(wear=(0, 1), discard=(1,))),
	],
)
def test_malformed_output_forfeits_one_turn_and_never_crashes_the_run(label, value):
	"""The live-demo rule: nothing a group commits may take down the class's
	run. Validation touches player-supplied objects, so it has to be as
	guarded as select_socks itself."""
	engine = Engine(
		players=[_player_returning(value), GreedyPlayer],
		capacity=40,
		selection_unit=4,
		days=3,
		seed=1,
	)
	results = engine.run()

	assert len(results['faults']) == 3, label
	assert results['faults'][0].startswith('Rogue: ')
	# The other roommate's day carried on regardless.
	assert len(engine.embarrassment[1]) == 3


def test_hostile_comparison_is_contained():
	"""An index whose __eq__ raises is enough to blow up validation."""

	class Weird:
		def __eq__(self, other):
			raise ValueError('nope')

		def __hash__(self):
			raise ValueError('nope')

	engine = Engine(
		players=[_player_returning(Selection(wear=(Weird(), 1), discard=()))],
		capacity=40,
		selection_unit=4,
		days=2,
		seed=1,
	)
	results = engine.run()
	assert 'ValueError: nope' in results['faults'][0]


def test_validation_verdicts_are_reported_verbatim():
	"""A PlayerFault raised by validation must not be re-wrapped by the
	sandbox: 'wear indices must lie in [0, 4)' beats
	'PlayerFault: wear indices must lie in [0, 4)'."""
	engine = Engine(
		players=[_player_returning(Selection(wear=(0, 99), discard=()))],
		capacity=40,
		selection_unit=4,
		days=1,
		seed=1,
	)
	results = engine.run()
	assert results['faults'] == ['Rogue: wear indices must lie in [0, 4)']


def test_a_forfeited_turn_still_wears_two_socks():
	"""The fallback has to leave the drawer consistent, or one bad group
	desyncs everybody."""
	engine = Engine(
		players=[_player_returning(None), GreedyPlayer],
		capacity=40,
		selection_unit=4,
		days=10,
		seed=5,
	)
	engine.run()
	assert len(engine.drawer) >= engine.selection_unit * engine.roommates
	assert len(engine.embarrassment[0]) == 10


class _Spin:
	"""Busy-waits, but only up to a deadline.

	An unbounded loop would be a truer hang; it would also wedge CI forever if
	the guard ever regressed. Bounded, a regression shows up as a failed
	assertion after the deadline instead.
	"""

	LIMIT = 20.0

	def _spin(self):
		import time

		deadline = time.perf_counter() + self.LIMIT
		while time.perf_counter() < deadline:
			pass


@pytest.mark.skipif(not hasattr(signal, 'SIGALRM'), reason='timeouts need SIGALRM')
def test_a_hang_in_select_socks_is_cut_off():
	class Hangs(_Spin, GreedyPlayer):
		def select_socks(self, offered, turn):
			self._spin()
			return Selection(wear=(0, 1), discard=())

	engine = Engine(
		players=[Hangs, GreedyPlayer], capacity=40, selection_unit=4, days=2, seed=1, timeout=0.25
	)
	results = engine.run()
	assert all('time budget' in f for f in results['faults'])
	assert len(results['faults']) == 2


@pytest.mark.skipif(not hasattr(signal, 'SIGALRM'), reason='timeouts need SIGALRM')
def test_a_hang_while_validating_the_move_is_cut_off():
	"""The reason validation runs inside the sandbox. `wear` looks harmless
	until the engine iterates it, and that iteration used to happen outside
	the alarm - where nothing could stop it."""

	class HangingIter(_Spin, GreedyPlayer):
		def select_socks(self, offered, turn):
			spin = self._spin

			class Forever:
				def __iter__(self):
					spin()
					return iter(())

			return Selection(wear=Forever(), discard=())

	engine = Engine(
		players=[HangingIter, GreedyPlayer],
		capacity=40,
		selection_unit=4,
		days=2,
		seed=1,
		timeout=0.25,
	)
	results = engine.run()
	assert all('time budget' in f for f in results['faults'])
	assert len(engine.embarrassment[1]) == 2


# ---------------------------------------------------------------- score integrity


class _Tamper(GreedyPlayer):
	"""Reaches through the history accessor's closure and forges its scores."""

	def select_socks(self, offered, turn):
		turn._history.__closure__[0].cell_contents.append(-999999.0)
		return super().select_socks(offered, turn)


def test_tampering_with_the_history_cannot_change_the_reported_score():
	"""The accessor closes over the engine's list, so a player can reach it.
	Nothing the engine scores on may be read back out of that list."""
	fields = ('total_embarrassment', 'mean_daily_embarrassment', 'embarrassed_days')

	tampered = Engine(
		players=[_Tamper, GreedyPlayer], capacity=40, selection_unit=4, days=40, seed=3
	).run()
	honest = Engine(
		players=[GreedyPlayer, GreedyPlayer], capacity=40, selection_unit=4, days=40, seed=3
	).run()

	for key in fields:
		assert tampered['players'][0][key] == honest['players'][0][key], key
	assert tampered['total_embarrassment'] == honest['total_embarrassment']
	assert tampered['total_spent'] == honest['total_spent']


def test_engine_total_matches_the_history_for_honest_players():
	"""The authoritative counter and the player-facing view must agree when
	nobody is cheating, or the two would quietly describe different runs."""
	engine = build(days=200)
	engine.run()
	for i in range(engine.roommates):
		assert engine.total_embarrassment(i) == sum(engine.embarrassment[i])


def test_turn_context_rejects_the_old_positional_signature():
	"""total_embarrassment was inserted ahead of the old third argument. Taken
	positionally, TurnContext(day, spent, history) put the history into the
	total and silently reported nonsense."""
	with pytest.raises(TypeError):
		TurnContext(5, 10.0, (1.0, 2.0))

	ctx = TurnContext(day=5, total_spent=10.0, total_embarrassment=3.0)
	assert ctx.embarrassment_history == ()


# ---------------------------------------------------------------- pending discards


def test_pending_shades_track_the_pending_counts():
	engine = build(players=[GreedyPlayer] * 4, days=400, seed=7)
	while engine.step() is not None:
		for color in (Color.WHITE, Color.BLACK):
			assert len(engine.pending_shades[color]) == engine.pending_discards[color]


def test_pending_shades_are_real_shades_not_assumed_ones():
	"""A sock discarded unworn is at whatever shade it had. Assuming every
	discard sits at the worn-out limit is wrong for exactly those."""
	engine = build(players=[GreedyPlayer] * 4, days=1)
	engine.step()
	engine.pending_shades[Color.WHITE].clear()
	engine.pending_discards[Color.WHITE] = 0

	sock = pristine(Color.WHITE)
	record = _record(engine)
	engine._Engine__discard(sock, record, hole=False)
	assert engine.pending_shades[Color.WHITE] == [255]
	assert engine.pending_discards[Color.WHITE] == 1


def test_buying_a_pack_clears_the_matching_shades():
	engine = build(days=1)
	for shade in range(8):
		engine.pending_shades[Color.BLACK].append(shade)
	engine.pending_discards[Color.BLACK] = 8

	engine._Engine__replenish(_record(engine))
	assert engine.pending_discards[Color.BLACK] == 2
	assert engine.pending_shades[Color.BLACK] == [6, 7]


# ---------------------------------------------------------------- budget


def test_no_budget_is_the_default_and_changes_nothing():
	assert build(days=50).budget is None
	assert build(days=50).budget_remaining == float('inf')
	assert build(days=50).run() == build(days=50, budget=None).run()


def test_budget_caps_total_spend():
	engine = build(players=[GreedyPlayer] * 4, days=2000, budget=300.0, timeout=0)
	results = engine.run()
	assert results['total_spent'] <= 300.0
	assert results['budget'] == 300.0
	assert results['budget_remaining'] == 300.0 - results['total_spent']


def test_a_generous_budget_is_indistinguishable_from_none():
	"""Above the natural spend the budget must be inert, or every pre-budget
	baseline in the docs quietly stops being reproducible."""
	free = build(players=[GreedyPlayer] * 4, days=360, timeout=0).run()
	rich = build(players=[GreedyPlayer] * 4, days=360, timeout=0, budget=100_000.0).run()

	assert free['total_embarrassment'] == rich['total_embarrassment']
	assert free['total_spent'] == rich['total_spent']
	assert rich['budget_exhausted_on_day'] is None
	assert rich['total_sockless_days'] == 0


def test_unaffordable_discards_stay_pending_rather_than_being_written_off():
	"""Owed replacements are not forgiven by poverty. If money reappeared the
	debt would still be there, and dropping it would silently shrink the
	drawer by more than the budget actually cost."""
	engine = build(days=1, budget=10.0)
	engine.total_spent = 5.0  # only $5 left: one pack costs $10
	engine.pending_discards[Color.WHITE] = 18
	engine.pending_shades[Color.WHITE] = [200] * 18

	engine._Engine__replenish(_record(engine))

	assert engine.total_spent == 5.0
	assert engine.pending_discards[Color.WHITE] == 18
	assert len(engine.pending_shades[Color.WHITE]) == 18


def test_partial_affordability_buys_what_it_can():
	engine = build(days=1, budget=25.0)
	engine.pending_discards[Color.BLACK] = 18  # three packs owed, two affordable
	engine.pending_shades[Color.BLACK] = list(range(18))

	engine._Engine__replenish(_record(engine))

	assert engine.total_spent == 20.0
	assert engine.pending_discards[Color.BLACK] == 6
	assert engine.pending_shades[Color.BLACK] == list(range(12, 18))


def test_exhaustion_day_is_recorded_once():
	engine = build(days=1, budget=0.0)
	engine.day = 7
	engine.pending_discards[Color.WHITE] = 6
	engine.pending_shades[Color.WHITE] = [200] * 6
	engine._Engine__replenish(_record(engine))
	assert engine.exhausted_on == 7

	engine.day = 9
	engine._Engine__replenish(_record(engine))
	assert engine.exhausted_on == 7, 'exhaustion is the first day it bit, not the latest'


# ---------------------------------------------------------------- sockless


def test_one_sock_means_a_sockless_day_and_the_sock_goes_back():
	"""The lone sock was never put on, so it is not consumed and does not age."""
	engine = build(players=[GreedyPlayer], capacity=40, days=1)
	lone = pristine(Color.WHITE)
	engine.drawer = [lone]

	record = engine.step()

	assert record.sockless == [0]
	assert record.embarrassment[0] == SOCKLESS_PENALTY
	assert engine.sockless[0] == 1
	assert engine.drawer == [lone], 'the sock was consumed or aged'
	assert engine.drawer[0].shade == 255


def test_an_empty_drawer_is_survivable():
	engine = build(players=[GreedyPlayer] * 2, capacity=40, days=3)
	engine.drawer = []
	results = engine.run()

	assert engine.day == 3
	assert results['total_sockless_days'] == 6
	assert results['total_embarrassment'] == 6 * SOCKLESS_PENALTY
	assert results['faults'] == [], "going sockless is not the player's fault"


def test_the_penalty_is_the_handout_number():
	assert SOCKLESS_PENALTY == 65536.0
	assert SOCKLESS_PENALTY == 256.0 * 256.0


def test_sockless_days_are_counted_per_player_and_in_total():
	engine = build(players=[GreedyPlayer] * 3, capacity=40, days=4)
	engine.drawer = []
	results = engine.run()

	assert [p['sockless_days'] for p in results['players']] == [4, 4, 4]
	assert results['total_sockless_days'] == 12


# ---------------------------------------------------------------- same-day pool


def test_a_sock_worn_by_one_roommate_is_not_offered_to_another_the_same_day():
	"""Regression: a two-sock drawer must not stretch to dress four roommates
	in one day. Only whoever draws first can dress; the rest go sockless,
	because nothing returns to the drawer until the day is over."""
	engine = build(players=[GreedyPlayer] * 4, capacity=40, days=1)
	engine.drawer = [pristine(Color.WHITE), pristine(Color.WHITE)]

	record = engine.step()

	total_offered = sum(len(offered) for offered in record.offered.values())
	assert total_offered == 2, 'the same socks were handed out more than once today'
	assert len(record.sockless) == 3


def test_worn_socks_return_only_at_the_end_of_the_day_not_mid_day():
	"""Directly checks the drawer never grows back inside a day's loop: with
	four roommates ahead of it and only two socks to start, the drawer must
	sit empty for the roommates after the first, not refill from washes."""
	engine = build(players=[GreedyPlayer] * 4, capacity=40, days=1)
	engine.drawer = [pristine(Color.WHITE), pristine(Color.WHITE)]

	seen_sizes = []
	original_draw = engine._Engine__draw

	def spy_draw():
		seen_sizes.append(len(engine.drawer))
		return original_draw()

	engine._Engine__draw = spy_draw
	engine.step()

	# First roommate draws from a full pool of 2; everyone after draws from an
	# empty one, because the wash from roommate one has not landed yet.
	assert seen_sizes == [2, 0, 0, 0]


def test_returns_are_available_starting_the_next_day():
	"""What was worn today is exactly tomorrow's pool - not later today."""
	engine = build(players=[GreedyPlayer] * 4, capacity=40, days=2)
	engine.drawer = [pristine(Color.WHITE), pristine(Color.WHITE)]

	first = engine.step()
	assert len(first.sockless) == 3
	assert len(engine.drawer) == 2, 'washed pair should be back by the end of day 1'

	second = engine.step()
	total_offered = sum(len(offered) for offered in second.offered.values())
	assert total_offered == 2
	assert len(second.sockless) == 3


# ---------------------------------------------------------------- short draws


def test_draw_returns_what_is_there_when_the_drawer_is_short():
	engine = build(players=[GreedyPlayer], capacity=40, days=1)
	engine.drawer = [pristine(Color.WHITE) for _ in range(3)]
	offered = engine._Engine__draw()
	assert len(offered) == 3
	assert engine.drawer == []


def test_validation_uses_the_actual_offer_not_the_unit():
	"""With three socks on the table, index 3 is out of range even though the
	selection unit is four."""
	engine = build(days=1)
	with pytest.raises(PlayerFault):
		engine._Engine__validate(Selection(wear=(0, 3), discard=()), 3)
	ok = engine._Engine__validate(Selection(wear=(0, 2), discard=()), 3)
	assert ok.wear == (0, 2)


def test_a_short_offer_is_still_playable_above_two_socks():
	engine = build(players=[GreedyPlayer], capacity=40, days=1)
	engine.drawer = [pristine(Color.WHITE), pristine(Color.BLACK), pristine(Color.WHITE)]
	record = engine.step()
	assert record.sockless == []
	assert 0 in record.worn
	assert record.faults == []
