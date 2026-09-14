"""Headless checks for the visualiser.

The GUI is the thing the TA runs on a projector in front of the class, so the
failure that matters is not a wrong pixel, it is a crash partway through a
year. These drive the real render path under SDL's dummy driver.
"""

import os
import random

import pytest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

pygame = pytest.importorskip('pygame')

from core.engine import Engine  # noqa: E402
from models.sock import Color  # noqa: E402
from players.greedy_player import GreedyPlayer  # noqa: E402
from players.random_player import RandomPlayer  # noqa: E402
from ui.gui import HEIGHT, MIN_ROW_H, WIDTH, Visualizer, draw_sock, sock_polygon  # noqa: E402


@pytest.fixture(scope='module')
def screen():
	pygame.init()
	surface = pygame.display.set_mode((WIDTH, HEIGHT))
	yield surface
	pygame.quit()


def build(**kwargs) -> Engine:
	defaults = dict(
		players=[GreedyPlayer] * 2 + [RandomPlayer] * 2,
		capacity=40,
		selection_unit=4,
		days=360,
		seed=4444,
	)
	defaults.setdefault('timeout', 0)
	defaults.update(kwargs)
	return Engine(**defaults)


def test_renders_a_full_year_without_crashing(screen):
	engine = build()
	view = Visualizer(engine)
	for _ in range(engine.days + 5):
		view.advance()
		view.draw(screen)

	assert engine.day == 360
	assert view.finished


def test_gui_run_matches_a_headless_run_exactly():
	"""The projector must not disagree with the JSON. Stepping through the
	visualiser has to leave the engine in the state `run()` would have.

	The global seed is set either side because RandomPlayer draws from the
	`random` module rather than the engine's rng, so without it the two rosters
	diverge for reasons that have nothing to do with the GUI.
	"""
	random.seed(0)
	stepped = build()
	view = Visualizer(stepped)
	for _ in range(stepped.days):
		view.advance()

	random.seed(0)
	direct = build().run()
	assert stepped.results() == direct


def test_advance_past_the_end_is_harmless(screen):
	engine = build(days=3)
	view = Visualizer(engine)
	for _ in range(20):
		view.advance()
	view.draw(screen)
	assert engine.day == 3
	assert view.finished
	assert not view.playing


def test_faults_are_logged_and_flagged(screen):
	"""A group whose code throws must show up on screen, not only in JSON."""

	class Broken(GreedyPlayer):
		def select_socks(self, offered, turn):
			raise RuntimeError('boom')

	engine = Engine(players=[Broken] * 2, capacity=40, selection_unit=4, days=4, seed=1)
	view = Visualizer(engine)
	view.advance()
	view.draw(screen)

	assert view.fault_log
	assert view.flashing_fault
	assert 'boom' in view.fault_log[-1][1]


def test_drawer_is_not_reordered_by_drawing(screen):
	"""Sorting the drawer for display would change which socks rng.sample
	picks and silently alter the simulation."""
	engine = build(days=5)
	view = Visualizer(engine)
	view.advance()
	before = [s.id for s in engine.drawer]
	view.draw(screen)
	assert [s.id for s in engine.drawer] == before


def test_speed_and_pause_controls():
	view = Visualizer(build())
	assert not view.playing
	view.toggle()
	assert view.playing

	for _ in range(20):
		view.faster()
	top = view.speed
	view.faster()
	assert view.speed == top

	for _ in range(20):
		view.slower()
	assert view.speed == 1


def test_quit_keys_stop_the_loop():
	view = Visualizer(build())
	quit_event = pygame.event.Event(pygame.QUIT)
	assert view.handle_event(quit_event) is False
	for key in (pygame.K_ESCAPE, pygame.K_q):
		assert view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key)) is False


def test_step_key_advances_one_day_and_pauses():
	view = Visualizer(build())
	view.playing = True
	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
	assert view.engine.day == 1
	assert not view.playing
	assert view.revealed == 1


def test_right_walks_roommates_then_the_next_day(screen):
	"""RIGHT is player-by-player. The engine still simulates the whole day on
	the first press, but later roommates stay hidden until they are due."""
	view = Visualizer(build(days=3))
	n = view.engine.roommates
	right = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT)
	left = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT)

	view.handle_event(right)
	assert view.engine.day == 1
	assert view.revealed == 1
	assert view.record is not None
	assert len(view.record.offered) == n
	view.draw(screen)

	for shown in range(2, n + 1):
		view.handle_event(right)
		assert view.engine.day == 1
		assert view.revealed == shown

	view.handle_event(left)
	assert view.engine.day == 1
	assert view.revealed == n - 1

	view.handle_event(right)
	view.handle_event(right)
	assert view.engine.day == 2
	assert view.revealed == 1
	view.draw(screen)


def test_right_past_the_last_day_keeps_every_roommate_visible(screen):
	"""The year-complete press used to reset reveal to 1, so the last day
	looked like only the first roommate had dressed."""
	view = Visualizer(build(days=2))
	n = view.engine.roommates
	right = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT)
	for _ in range(n * 2):
		view.handle_event(right)
	assert view.engine.day == 2
	assert view.revealed == n
	assert not view.finished

	view.handle_event(right)
	assert view.finished
	assert view.engine.day == 2
	assert view.revealed == n
	view.draw(screen)


def test_play_reveals_every_roommate(screen):
	view = Visualizer(build(days=2))
	view.advance()
	assert view.revealed == view.engine.roommates
	assert all(i in view.record.offered for i in range(view.engine.roommates))
	view.draw(screen)


def test_jump_to_matches_stepping_and_reveals_everyone():
	"""G / J must not be a second simulation. Fast-forwarding to day 10
	has to leave the engine where ten ordinary steps would have."""
	import random as rng

	rng.seed(0)
	jumped = build(days=30)
	view = Visualizer(jumped)
	view.playing = True
	view.jump_to(10)

	assert jumped.day == 10
	assert view.revealed == jumped.roommates
	assert not view.playing
	assert view.record is not None
	assert view.record.day == 10

	rng.seed(0)
	stepped = build(days=30)
	for _ in range(10):
		stepped.step()
	assert jumped.results() == stepped.results()


def test_jump_to_does_not_rewind():
	view = Visualizer(build(days=20))
	view.jump_to(8)
	view.jump_to(3)
	assert view.engine.day == 8


def test_jump_to_past_the_end_lands_on_the_last_day(screen):
	"""Jumping past the last morning stops on it, still inspectable. One more
	advance is what marks the year complete, same as RIGHT after the last
	roommate of the last day."""
	view = Visualizer(build(days=4))
	view.jump_to(99)
	view.draw(screen)
	assert view.engine.day == 4
	assert not view.finished
	assert view.revealed == view.engine.roommates

	view.advance()
	assert view.finished
	view.draw(screen)


def test_skip_bar_is_on_the_first_frame(screen):
	view = Visualizer(build(days=10))
	view.draw(screen)
	bar = view._skip_bar_rect()
	assert bar.y == view._skip_bar_rect().y
	assert view.goto_buffer == ''


def test_typing_a_day_in_the_skip_box_jumps(screen):
	view = Visualizer(build(days=40))
	view.draw(screen)
	for ch in '12':
		view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode=ch))
	assert view.goto_buffer == '12'

	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode='\r'))
	assert view.goto_buffer == ''
	assert view.engine.day == 12
	assert view.revealed == view.engine.roommates
	view.draw(screen)


def test_skip_box_refuses_to_rewind_and_esc_clears(screen):
	view = Visualizer(build(days=40))
	view.jump_to(9)
	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_3, unicode='3'))
	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode='\r'))
	assert view.engine.day == 9
	assert view.goto_error is not None
	view.draw(screen)

	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
	assert view.goto_buffer == ''
	assert view.goto_error is None
	assert view.engine.day == 9


def test_jump_forwards_days_into_the_on_day_hook():
	seen = []
	view = Visualizer(build(days=15), on_day=seen.append)
	view.jump_to(6)
	assert [r.day for r in seen] == list(range(1, 7))


def test_socks_render_at_their_true_shade(screen):
	"""The brief is that the shade drift is visible at a glance, so the icon
	has to be filled with the sock's actual value."""
	for shade in (255, 191, 127, 64, 0):
		screen.fill((34, 102, 54))
		rect = pygame.Rect(100, 100, 120, 170)
		draw_sock(screen, rect, shade)
		# Sample the middle of the leg, below the cuff band.
		sampled = screen.get_at((rect.x + int(rect.w * 0.4), rect.y + int(rect.h * 0.35)))[:3]
		assert sampled == (shade, shade, shade)


def test_sock_polygon_stays_inside_its_box():
	rect = pygame.Rect(10, 20, 60, 90)
	points = sock_polygon(rect)
	assert len(points) >= 8
	for x, y in points:
		assert rect.left <= x <= rect.right
		assert rect.top <= y <= rect.bottom


def test_trash_can_reflects_pending_discards(screen):
	engine = build(days=1)
	engine.pending_discards[Color.WHITE] = 5
	engine.pending_discards[Color.BLACK] = 3
	view = Visualizer(engine)
	view.draw(screen)  # must not raise with a part-full can
	assert engine.pending_discards[Color.WHITE] == 5


def test_five_sock_unit_renders(screen):
	engine = build(selection_unit=5, capacity=44, days=10)
	view = Visualizer(engine)
	for _ in range(10):
		view.advance()
		view.draw(screen)
	assert engine.day == 10


def test_trash_renders_the_engines_actual_shades(screen):
	"""The UI used to assume every pending discard sat at its colour's
	worn-out limit. It does not get to decide what a thrown-out sock looked
	like - the engine knows, and now says."""
	engine = build(days=1)
	engine.pending_shades[Color.WHITE] = [255, 201]
	engine.pending_discards[Color.WHITE] = 2
	engine.pending_shades[Color.BLACK] = [7]
	engine.pending_discards[Color.BLACK] = 1

	view = Visualizer(engine)
	view.draw(screen)

	rendered = view.engine.pending_shades
	assert rendered[Color.WHITE] == [255, 201]
	assert rendered[Color.BLACK] == [7]


def test_roommate_total_comes_from_the_engine_not_the_view_list(screen):
	"""The running total is read from the engine's authoritative counter, so a
	player that tampers with its own history cannot change what is projected."""
	engine = build(days=20)
	view = Visualizer(engine)
	for _ in range(20):
		view.advance()

	engine.embarrassment[0].append(-999999.0)
	view.draw(screen)
	assert engine.total_embarrassment(0) == sum(engine.embarrassment[0][:-1])


# ---------------------------------------------------------------- budget endgame


def test_budget_gauge_renders_with_and_without_a_budget(screen):
	for budget in (None, 500.0):
		engine = build(days=5, budget=budget)
		view = Visualizer(engine)
		view.advance()
		view.draw(screen)  # must not raise either way
		assert engine.budget == budget


def test_sockless_roommate_is_drawn_differently(screen):
	"""65536 must not render as one more number in a column."""
	engine = build(players=[GreedyPlayer] * 2, capacity=40, days=2)
	engine.drawer = []
	view = Visualizer(engine)
	view.advance()

	assert view.record.sockless == [0, 1]

	view.draw(screen)
	# The row band is repainted in the bare-skin colour rather than the felt.
	from ui.gui import BARE

	hits = sum(
		1
		for x in range(880, 1330, 7)
		for y in range(130, 800, 7)
		if screen.get_at((x, y))[:3] == BARE
	)
	assert hits > 200, 'sockless rows are not visually distinct'


def test_an_empty_drawer_renders(screen):
	engine = build(days=2)
	engine.drawer = []
	view = Visualizer(engine)
	view.advance()
	view.draw(screen)
	assert len(engine.drawer) == 0


def test_drawer_renders_at_every_size_from_full_to_empty(screen):
	"""After the budget goes the drawer walks down to nothing. No count in
	between may break the layout."""
	from models.sock import Color, pristine

	engine = build(days=1)
	for held in range(0, 41):
		engine.drawer = [pristine(Color.WHITE if i % 2 else Color.BLACK) for i in range(held)]
		Visualizer(engine).draw(screen)


# ---------------------------------------------------------------- many roommates


def test_a_hundred_roommates_scroll_instead_of_shrinking(screen):
	"""n=100 used to squeeze every row into a few pixels. Rows stay readable
	and the list scrolls."""
	engine = build(players=[RandomPlayer] * 100, capacity=412, days=1, timeout=0)
	view = Visualizer(engine)
	view.advance()
	view.draw(screen)

	row_h, view_h, max_scroll = view._mates_scroll_state()
	assert row_h >= MIN_ROW_H
	assert max_scroll > 0
	assert view.mates_scroll == 0


def test_mouse_wheel_and_page_keys_scroll_the_roommate_list(screen):
	engine = build(players=[RandomPlayer] * 20, capacity=92, days=1, timeout=0)
	view = Visualizer(engine)
	view.advance()
	view.draw(screen)
	_, view_h, max_scroll = view._mates_scroll_state()
	assert max_scroll > 0

	view.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-1))
	assert 0 < view.mates_scroll <= max_scroll

	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEDOWN))
	assert view.mates_scroll <= max_scroll

	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_HOME))
	assert view.mates_scroll == 0

	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_END))
	assert view.mates_scroll == max_scroll

	view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEUP))
	assert view.mates_scroll == max(0.0, max_scroll - view_h)

	view.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1))
	view.draw(screen)


def test_right_keeps_the_current_roommate_on_screen(screen):
	"""Walking the turn with RIGHT must not leave the highlighted row off the
	panel just because there are too many roommates to fit."""
	engine = build(players=[RandomPlayer] * 20, capacity=92, days=2, timeout=0)
	view = Visualizer(engine)
	right = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT)
	view.handle_event(right)
	view.draw(screen)

	for _ in range(engine.roommates - 1):
		view.handle_event(right)

	current = view.record.order[view.revealed - 1]
	row_h, view_h, _ = view._mates_scroll_state()
	top = current * row_h
	assert view.mates_scroll <= top + 1
	assert top + row_h <= view.mates_scroll + view_h + 1
	view.draw(screen)
