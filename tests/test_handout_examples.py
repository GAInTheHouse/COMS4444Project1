"""The handout's worked replenishment examples, verbatim.

THESE CAME FROM THE INSTRUCTOR. DO NOT EDIT THE NUMBERS.

They are the authoritative reading of the six-pack rule, and they are written
out longhand rather than derived from a loop so that any disagreement between
the simulator and the handout shows up as a failing assertion with the exact
figures in it. If one of these fails, the engine is wrong, not the test - fix
`Engine.__replenish` and leave these alone.

If the instructor ever revises a number, replace it wholesale and say so in the commit;
do not adjust one to fit an implementation.

    1. 12 discarded of a colour in one turn  -> 12 socks added that turn
    2. 11 discarded with a carryover of 1    -> 12 socks added
    3. 11 discarded with no carryover        ->  6 socks added, 5 carried forward
"""

from core.engine import PACK_COST, DayRecord, Engine
from models.sock import Color
from players.greedy_player import GreedyPlayer


def bench() -> Engine:
	"""An engine parked before day one, so replenishment can be exercised on
	its own without a day's wear muddying the counts."""
	return Engine(
		players=[GreedyPlayer] * 2,
		capacity=40,
		selection_unit=4,
		days=1,
		seed=1,
		timeout=0,
	)


def replenish(engine: Engine, color: Color, discarded: int, carryover: int = 0) -> dict:
	"""Put `carryover` already-pending discards on the books, add `discarded`
	more, then run one replenishment and report what changed."""
	engine.pending_discards[color] = carryover
	engine.pending_shades[color] = [200] * carryover

	for _ in range(discarded):
		engine.pending_discards[color] += 1
		engine.pending_shades[color].append(200)

	before_drawer = len(engine.drawer)
	before_spent = engine.total_spent
	record = DayRecord(day=engine.day, order=[])

	engine._Engine__replenish(record)

	return {
		'added': len(engine.drawer) - before_drawer,
		'carried': engine.pending_discards[color],
		'packs': record.packs_bought[color],
		'spent': engine.total_spent - before_spent,
	}


# -------------------------------------------------------- The handout's cases


def test_handout_case_1_twelve_discarded_adds_twelve():
	"""12 discarded of a colour in one turn -> 12 socks added that turn."""
	engine = bench()
	result = replenish(engine, Color.WHITE, discarded=12, carryover=0)

	assert result['added'] == 12
	assert result['packs'] == 2
	assert result['carried'] == 0
	assert result['spent'] == 2 * PACK_COST


def test_handout_case_2_eleven_discarded_with_carryover_of_one_adds_twelve():
	"""11 discarded with a carryover of 1 -> 12 socks added."""
	engine = bench()
	result = replenish(engine, Color.WHITE, discarded=11, carryover=1)

	assert result['added'] == 12
	assert result['packs'] == 2
	assert result['carried'] == 0
	assert result['spent'] == 2 * PACK_COST


def test_handout_case_3_eleven_discarded_with_no_carryover_adds_six_and_carries_five():
	"""11 discarded with no carryover -> 6 socks added, 5 carried forward."""
	engine = bench()
	result = replenish(engine, Color.BLACK, discarded=11, carryover=0)

	assert result['added'] == 6
	assert result['packs'] == 1
	assert result['carried'] == 5
	assert result['spent'] == PACK_COST


# ---------------------------------------------------------------- corollaries


def test_the_carried_five_buy_a_pack_on_the_next_discard():
	"""Case 3, continued one step: the 5 left over are still owed, so a single
	further discard completes the next six-pack."""
	engine = bench()
	replenish(engine, Color.BLACK, discarded=11, carryover=0)
	follow_up = replenish(engine, Color.BLACK, discarded=1, carryover=5)

	assert follow_up['added'] == 6
	assert follow_up['carried'] == 0


def test_the_socks_bought_back_are_the_right_colour_and_pristine():
	"""The handout's cases count socks; these are the socks. A six-pack of white is
	six new white socks at 255, not a mixed pack and not pre-worn."""
	engine = bench()
	before = {s.id for s in engine.drawer}

	replenish(engine, Color.WHITE, discarded=12, carryover=0)

	arrived = [s for s in engine.drawer if s.id not in before]
	assert len(arrived) == 12
	assert all(s.color is Color.WHITE for s in arrived)
	assert all(s.shade == 255 for s in arrived)


def test_five_pending_buys_nothing():
	"""The threshold is six. Five discards sit there."""
	engine = bench()
	result = replenish(engine, Color.WHITE, discarded=5, carryover=0)

	assert result['added'] == 0
	assert result['packs'] == 0
	assert result['carried'] == 5
	assert result['spent'] == 0
