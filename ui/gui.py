"""Pygame visualiser for the sock simulator.

The brief: the drawer as sock-shaped icons in each sock's actual greyscale
shade on a green background, with discarded-and-not-yet-replaced socks in a
virtual trash can. The point is that the white-to-grey and black-to-grey drift
is visible across the room, without anybody reading a number.

This module contains no game rules. It calls ``engine.step()`` once per
simulated day and renders the returned ``DayRecord`` plus whatever is already
on the engine. If something here needs a value the engine does not expose, the
fix is to expose it on the engine, not to recompute it up here - a visualiser
that does its own arithmetic is how the projector ends up disagreeing with the
JSON.
"""

from collections.abc import Callable

import pygame

from core.engine import SOCKLESS_PENALTY, DayRecord, Engine
from models.sock import Color

WIDTH, HEIGHT = 1360, 880
HEADER_H = 76
JUMP_BAR_H = 50
FOOTER_H = 46
BANNER_H = 42
PAD = 18

FELT = (34, 102, 54)
FELT_DARK = (26, 80, 42)
PANEL = (28, 88, 46)
PANEL_EDGE = (96, 158, 112)
INK = (238, 246, 238)
INK_DIM = (170, 202, 178)
OUTLINE = (206, 224, 208)
ALERT = (198, 48, 48)
ALERT_TEXT = (255, 226, 226)
GOOD = (140, 220, 150)
CAN_BODY = (128, 138, 132)
CAN_DARK = (98, 108, 102)

# Icon sizing. Without an upper bound the grid solver fills whatever space it
# is given, so a can holding three socks would draw them the size of a hand.
MAX_CELL = 96.0
TRASH_CELL = 74.0
# Just translucent enough to read as "a count, not a tracked sock", without
# tinting a white sock green.
PENDING_ALPHA = 230

WARN = (224, 158, 46)
BARE = (150, 30, 30)

SPEEDS = (1, 2, 4, 8, 16, 32, 64)
DEFAULT_SPEED_INDEX = 2
FAULT_LOG_LIMIT = 6
FAULT_FLASH_DAYS = 3

# Below this, roommate rows stop being readable on a projector, so the
# panel scrolls instead of shrinking every row to a sliver.
MIN_ROW_H = 120
SCROLL_STEP = 56

# Pending discards are drawn slightly translucent, to read as "on the way out"
# rather than "in the drawer". Their shades come from the engine
# (``pending_shades``); the UI does not get to decide what a thrown-out sock
# looked like.


def sock_polygon(rect: pygame.Rect) -> list[tuple[float, float]]:
	"""A sock outline inscribed in ``rect``: cuff at the top, toe to the right."""
	x, y, w, h = rect
	return [
		(x + 0.20 * w, y + 0.00 * h),
		(x + 0.64 * w, y + 0.00 * h),
		(x + 0.64 * w, y + 0.54 * h),
		(x + 0.90 * w, y + 0.62 * h),
		(x + 1.00 * w, y + 0.78 * h),
		(x + 0.94 * w, y + 0.93 * h),
		(x + 0.74 * w, y + 1.00 * h),
		(x + 0.30 * w, y + 1.00 * h),
		(x + 0.13 * w, y + 0.90 * h),
		(x + 0.20 * w, y + 0.58 * h),
	]


def draw_sock(surface: pygame.Surface, rect: pygame.Rect, shade: int, alpha: int = 255) -> None:
	"""Render one sock at its true greyscale shade.

	The light outline is what keeps a shade-0 sock legible against the green;
	without it black socks read as holes in the background.
	"""
	shade = max(0, min(255, int(shade)))
	body = (shade, shade, shade)

	if alpha >= 255:
		target, points = surface, sock_polygon(rect)
	else:
		target = pygame.Surface(rect.size, pygame.SRCALPHA)
		points = sock_polygon(pygame.Rect(0, 0, rect.w, rect.h))

	pygame.draw.polygon(target, body, points)
	pygame.draw.aalines(target, OUTLINE, True, points)

	# A cuff band, one step off the body, so the sock reads as a sock rather
	# than a grey blob at small sizes.
	cuff = 18 if shade < 128 else -18
	band = pygame.Rect(rect.x, rect.y, rect.w, max(2, int(rect.h * 0.13)))
	if target is not surface:
		band = pygame.Rect(0, 0, rect.w, band.h)
	clip = target.get_clip()
	target.set_clip(band)
	pygame.draw.polygon(target, tuple(max(0, min(255, c + cuff)) for c in body), points)
	pygame.draw.aalines(target, OUTLINE, True, points)
	target.set_clip(clip)

	if target is not surface:
		target.set_alpha(alpha)
		surface.blit(target, rect.topleft)


class Visualizer:
	"""Simulation state plus drawing. Kept separate from the event loop so a
	test can advance and render a full year headlessly."""

	def __init__(
		self,
		engine: Engine,
		on_day: Callable[[DayRecord], None] | None = None,
	) -> None:
		self.engine = engine
		self.on_day = on_day
		self.record: DayRecord | None = None
		self.playing = False
		self.speed_index = DEFAULT_SPEED_INDEX
		self.finished = False
		# How many of today's turn order are shown as dressed. Play and
		# ``advance()`` reveal everyone; RIGHT walks them one roommate at a
		# time so a class can see each handful.
		self.revealed = 0
		self.fault_log: list[tuple[int, str]] = []
		self.last_fault_day = -FAULT_FLASH_DAYS - 1
		self.fonts: dict[str, pygame.font.Font] = {}
		self.mates_scroll = 0.0
		# Always-visible skip box. Digits land here; Enter jumps forward.
		# Cannot rewind: the engine has already consumed the RNG.
		self.goto_buffer = ''
		self.goto_error: str | None = None
		self.goto_focused = True

	# ------------------------------------------------------------------ state

	@property
	def speed(self) -> int:
		return SPEEDS[self.speed_index]

	def advance(self) -> None:
		"""Simulate one day. The engine owns every rule; this only records
		what came back so the next frame can draw it."""
		record = self.engine.step()
		if record is None:
			self.finished = True
			self.playing = False
			return

		self.record = record
		self.revealed = self.engine.roommates
		for fault in record.faults:
			self.fault_log.append((record.day, fault))
			self.last_fault_day = record.day
		del self.fault_log[:-FAULT_LOG_LIMIT]
		if self.on_day is not None:
			self.on_day(record)

	def reveal_next(self) -> None:
		"""Show the next roommate, or step the day if everyone is already up."""
		if self.finished:
			return
		n = self.engine.roommates
		if self.record is not None and self.revealed < n:
			self.revealed += 1
			self._follow_revealed()
			return
		self.advance()
		# Past the last day, ``advance`` sets finished and leaves the last
		# day's record in place. Do not hide the other roommates.
		if self.finished:
			return
		if self.record is not None:
			self.revealed = 1
			self._follow_revealed()

	def reveal_previous(self) -> None:
		"""Hide the last-shown roommate. Does not rewind the engine."""
		if self.record is not None and self.revealed > 1:
			self.revealed -= 1
			self._follow_revealed()

	def toggle(self) -> None:
		if not self.finished:
			self.playing = not self.playing

	def faster(self) -> None:
		self.speed_index = min(self.speed_index + 1, len(SPEEDS) - 1)

	def slower(self) -> None:
		self.speed_index = max(self.speed_index - 1, 0)

	def jump_to(self, day: int) -> None:
		"""Fast-forward to ``day`` (inclusive) and pause, everyone revealed.

		Does not rewind. The engine has already consumed the RNG for every
		morning behind us; going back would be a different simulation.
		"""
		if self.finished:
			return
		self.playing = False
		target = min(max(day, 1), self.engine.days)
		if target <= self.engine.day:
			return
		while not self.finished and self.engine.day < target:
			self.advance()
		if self.record is not None:
			self.revealed = self.engine.roommates

	def _commit_goto(self) -> None:
		if not self.goto_buffer:
			return
		target = int(self.goto_buffer)
		if target <= self.engine.day:
			self.goto_error = f'already on day {self.engine.day} - cannot rewind'
			return
		self.goto_buffer = ''
		self.goto_error = None
		self.jump_to(target)

	def _clear_goto(self) -> None:
		self.goto_buffer = ''
		self.goto_error = None

	@property
	def flashing_fault(self) -> bool:
		return self.engine.day - self.last_fault_day < FAULT_FLASH_DAYS

	def handle_event(self, event: pygame.event.Event) -> bool:
		"""Return False when the user asks to quit."""
		if event.type == pygame.QUIT:
			return False
		if event.type == pygame.MOUSEWHEEL:
			self.mates_scroll -= event.y * SCROLL_STEP
			self._clamp_scroll()
			return True
		if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
			pos = event.dict.get('pos') or (0, 0)
			self.goto_focused = self._skip_bar_rect().collidepoint(pos)
			return True
		if event.type != pygame.KEYDOWN:
			return True

		ch = event.dict.get('unicode') or ''
		if ch.isdigit() and not self.finished:
			if len(self.goto_buffer) < 6:
				self.goto_buffer += ch
				self.goto_error = None
			self.goto_focused = True
			return True
		if event.key == pygame.K_BACKSPACE and self.goto_buffer:
			self.goto_buffer = self.goto_buffer[:-1]
			self.goto_error = None
			return True
		if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.goto_buffer:
			self._commit_goto()
			return True

		if event.key == pygame.K_ESCAPE:
			if self.goto_buffer or self.goto_error:
				self._clear_goto()
				return True
			return False
		if event.key == pygame.K_q:
			return False
		if event.key == pygame.K_SPACE:
			self.toggle()
		elif event.key in (pygame.K_RIGHT, pygame.K_s):
			self.playing = False
			self.reveal_next()
		elif event.key in (pygame.K_LEFT, pygame.K_a):
			self.playing = False
			self.reveal_previous()
		elif event.key in (pygame.K_UP, pygame.K_EQUALS, pygame.K_PLUS):
			self.faster()
		elif event.key in (pygame.K_DOWN, pygame.K_MINUS):
			self.slower()
		elif event.key == pygame.K_PAGEUP:
			self.mates_scroll -= self._mates_scroll_state()[1]
			self._clamp_scroll()
		elif event.key == pygame.K_PAGEDOWN:
			self.mates_scroll += self._mates_scroll_state()[1]
			self._clamp_scroll()
		elif event.key == pygame.K_HOME:
			self.mates_scroll = 0.0
		elif event.key == pygame.K_END:
			self.mates_scroll = self._mates_scroll_state()[2]
		return True

	def _chrome_top(self) -> int:
		top = HEADER_H + JUMP_BAR_H
		if self.fault_log:
			top += BANNER_H
		return top

	def _skip_bar_rect(self) -> pygame.Rect:
		return pygame.Rect(0, HEADER_H, WIDTH, JUMP_BAR_H)

	def _skip_input_rect(self) -> pygame.Rect:
		bar = self._skip_bar_rect()
		return pygame.Rect(bar.x + 148, bar.y + 10, 120, bar.h - 20)

	def _panels(self) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
		"""Drawer, trash, and roommate panel boxes. Shared by draw and scroll."""
		top = self._chrome_top()
		body_h = HEIGHT - top - FOOTER_H - PAD
		left_w = int(WIDTH * 0.54)
		drawer_rect = pygame.Rect(PAD, top + PAD // 2, left_w - PAD, int(body_h * 0.62))
		trash_rect = pygame.Rect(
			PAD,
			drawer_rect.bottom + PAD // 2,
			left_w - PAD,
			body_h - drawer_rect.h - PAD // 2,
		)
		mates_rect = pygame.Rect(
			left_w + PAD // 2, top + PAD // 2, WIDTH - left_w - PAD - PAD // 2, body_h
		)
		return drawer_rect, trash_rect, mates_rect

	@staticmethod
	def _inner(rect: pygame.Rect) -> pygame.Rect:
		return pygame.Rect(rect.x + 14, rect.y + 44, rect.w - 28, rect.h - 58)

	def _mates_scroll_state(self) -> tuple[float, int, float]:
		"""Row height, visible height, and how far the list can scroll."""
		inner = self._inner(self._panels()[2])
		n = self.engine.roommates
		if n <= 0:
			return float(inner.h), inner.h, 0.0
		natural = inner.h / n
		row_h = natural if natural >= MIN_ROW_H else float(MIN_ROW_H)
		max_scroll = max(0.0, n * row_h - inner.h)
		return row_h, inner.h, max_scroll

	def _clamp_scroll(self) -> None:
		max_scroll = self._mates_scroll_state()[2]
		if self.mates_scroll < 0:
			self.mates_scroll = 0.0
		elif self.mates_scroll > max_scroll:
			self.mates_scroll = max_scroll

	def _follow_revealed(self) -> None:
		"""Keep the roommate RIGHT/LEFT just landed on inside the panel."""
		if self.record is None or not self.revealed:
			return
		self._scroll_row_into_view(self.record.order[self.revealed - 1])

	def _scroll_row_into_view(self, index: int) -> None:
		row_h, view_h, _ = self._mates_scroll_state()
		top = index * row_h
		bottom = top + row_h
		if top < self.mates_scroll:
			self.mates_scroll = top
		elif bottom > self.mates_scroll + view_h:
			self.mates_scroll = bottom - view_h
		self._clamp_scroll()

	# ------------------------------------------------------------------ fonts

	def font(self, name: str) -> pygame.font.Font:
		if name not in self.fonts:
			sizes = {'big': 34, 'mid': 24, 'small': 19, 'tiny': 16}
			self.fonts[name] = pygame.font.Font(None, sizes[name])
		return self.fonts[name]

	def text(
		self,
		surface: pygame.Surface,
		value: str,
		pos: tuple[int, int],
		name: str = 'small',
		color: tuple[int, int, int] = INK,
		right: bool = False,
	) -> pygame.Rect:
		image = self.font(name).render(value, True, color)
		rect = image.get_rect()
		setattr(rect, 'topright' if right else 'topleft', pos)
		surface.blit(image, rect)
		return rect

	def panel(self, surface: pygame.Surface, rect: pygame.Rect, title: str) -> pygame.Rect:
		pygame.draw.rect(surface, PANEL, rect, border_radius=10)
		pygame.draw.rect(surface, PANEL_EDGE, rect, width=2, border_radius=10)
		self.text(surface, title, (rect.x + 14, rect.y + 10), 'mid')
		return self._inner(rect)

	# ------------------------------------------------------------------ drawing

	def draw(self, surface: pygame.Surface) -> None:
		surface.fill(FELT)
		self.draw_header(surface)
		self.draw_skip_bar(surface)

		if self.fault_log:
			self.draw_fault_banner(surface, pygame.Rect(0, HEADER_H + JUMP_BAR_H, WIDTH, BANNER_H))

		drawer_rect, trash_rect, mates_rect = self._panels()
		self.draw_drawer(surface, drawer_rect)
		self.draw_trash(surface, trash_rect)
		self.draw_roommates(surface, mates_rect)
		self.draw_footer(surface)

	def draw_header(self, surface: pygame.Surface) -> None:
		engine = self.engine
		pygame.draw.rect(surface, FELT_DARK, pygame.Rect(0, 0, WIDTH, HEADER_H))

		self.text(surface, f'Day {engine.day} / {engine.days}', (PAD, 14), 'big')

		if self.finished:
			state = 'complete'
		elif self.playing:
			state = f'playing  {self.speed}x'
		elif self.record is not None:
			state = f'paused  -  roommate {self.revealed} of {self.engine.roommates}'
		else:
			state = 'paused'
		self.text(surface, state, (PAD, 50), 'small', INK_DIM)

		self.text(
			surface, f'${engine.total_spent:,.0f} spent', (WIDTH - PAD, 14), 'big', right=True
		)
		self.draw_budget(surface)

		# A progress rule along the very bottom of the header.
		if engine.days:
			fraction = engine.day / engine.days
			pygame.draw.rect(surface, PANEL_EDGE, pygame.Rect(0, HEADER_H - 4, WIDTH, 4))
			pygame.draw.rect(surface, GOOD, pygame.Rect(0, HEADER_H - 4, int(WIDTH * fraction), 4))

	def draw_budget(self, surface: pygame.Surface) -> None:
		"""Money left, next to money spent.

		Once this hits zero nothing is ever replaced again, so it is the single
		number that predicts the rest of the run. It gets a gauge rather than
		just a figure, because a bar draining towards empty reads from the back
		of a lecture theatre and a number does not.
		"""
		engine = self.engine
		if engine.budget is None:
			self.text(surface, 'no budget', (WIDTH - PAD, 52), 'small', INK_DIM, right=True)
			return

		remaining = max(0.0, engine.budget_remaining)
		fraction = remaining / engine.budget if engine.budget else 0.0

		if engine.exhausted_on is not None:
			label = f'BUDGET GONE  day {engine.exhausted_on}'
			color = ALERT
		else:
			label = f'${remaining:,.0f} of ${engine.budget:,.0f} left'
			color = GOOD if fraction > 0.33 else WARN
		self.text(surface, label, (WIDTH - PAD, 46), 'small', color, right=True)

		gauge = pygame.Rect(WIDTH - PAD - 240, 64, 240, 7)
		pygame.draw.rect(surface, FELT, gauge, border_radius=3)
		if fraction > 0:
			filled = pygame.Rect(gauge.x, gauge.y, max(2, int(gauge.w * fraction)), gauge.h)
			pygame.draw.rect(surface, color, filled, border_radius=3)
		pygame.draw.rect(surface, PANEL_EDGE, gauge, width=1, border_radius=3)

	def draw_skip_bar(self, surface: pygame.Surface) -> None:
		"""Always-on skip control. The instructions live here, not on hidden keys."""
		bar = self._skip_bar_rect()
		pygame.draw.rect(surface, PANEL, bar)
		pygame.draw.line(surface, PANEL_EDGE, (0, bar.bottom - 1), (WIDTH, bar.bottom - 1))

		self.text(surface, 'Skip to day', (PAD, bar.y + 15), 'mid')

		box = self._skip_input_rect()
		pygame.draw.rect(surface, FELT_DARK, box, border_radius=6)
		ring = GOOD if self.goto_focused or self.goto_buffer else PANEL_EDGE
		pygame.draw.rect(surface, ring, box, width=2, border_radius=6)

		if self.goto_buffer:
			shown = self.goto_buffer + ('_' if self.goto_focused else '')
			color = INK
		else:
			shown = '_' if self.goto_focused else 'day'
			color = INK if self.goto_focused else INK_DIM
		self.text(surface, shown, (box.x + 10, box.y + 6), 'mid', color)

		if self.goto_error:
			hint, hint_color = self.goto_error, ALERT
		else:
			hint, hint_color = 'type a day number, press Enter    cannot rewind', INK_DIM
		self.text(surface, hint, (box.right + 16, bar.y + 16), 'small', hint_color)

	def draw_fault_banner(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
		"""A player fault must be impossible to miss from the back of the room."""
		active = self.flashing_fault
		pygame.draw.rect(surface, ALERT if active else FELT_DARK, rect)

		day, message = self.fault_log[-1]
		label = f'FAULT  day {day}  {message}'
		if len(self.fault_log) > 1:
			label += f'   (+{len(self.fault_log) - 1} more)'
		self.text(
			surface,
			label,
			(PAD, rect.y + 11),
			'mid',
			ALERT_TEXT if active else INK_DIM,
		)

	def draw_drawer(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
		engine = self.engine
		held = len(engine.drawer)
		inner = self.panel(surface, rect, f'Drawer  -  {held} of {engine.capacity} socks')

		# Once the budget is gone the drawer only shrinks, and a grid that
		# quietly reflows would hide that. The gauge keeps the starting
		# capacity on screen as the thing being measured against.
		gauge = pygame.Rect(inner.x, inner.y, inner.w, 6)
		pygame.draw.rect(surface, FELT_DARK, gauge, border_radius=3)
		fraction = min(1.0, held / engine.capacity) if engine.capacity else 0.0
		if fraction > 0:
			color = GOOD if fraction > 0.5 else (WARN if fraction > 0.2 else ALERT)
			pygame.draw.rect(
				surface,
				color,
				pygame.Rect(gauge.x, gauge.y, max(2, int(gauge.w * fraction)), gauge.h),
				border_radius=3,
			)
		pygame.draw.rect(surface, PANEL_EDGE, gauge, width=1, border_radius=3)

		area = pygame.Rect(inner.x, gauge.bottom + 10, inner.w, inner.h - gauge.h - 10)
		if not engine.drawer:
			self.text(surface, 'the drawer is empty', (area.x, area.centery - 10), 'mid', ALERT)
			return

		# sorted() copies. Sorting engine.drawer in place would change which
		# indices rng.sample picks and silently alter the simulation.
		socks = sorted(engine.drawer, key=lambda s: (s.color is Color.BLACK, -s.shade))
		self.draw_sock_grid(surface, area, [s.shade for s in socks])

	def draw_sock_grid(
		self,
		surface: pygame.Surface,
		area: pygame.Rect,
		shades: list[int],
		alpha: int = 255,
		max_cell: float = MAX_CELL,
	) -> None:
		"""Lay out however many socks there are inside ``area``.

		The drawer grows as six-packs arrive, so the icon size is solved for
		rather than fixed: the grid always fits. ``max_cell`` stops the other
		extreme, where a nearly-empty trash can renders three socks the size of
		the panel.
		"""
		if not shades or area.w <= 0 or area.h <= 0:
			return

		best = (0.0, 1)
		for cols in range(1, len(shades) + 1):
			rows = -(-len(shades) // cols)
			size = min(area.w / cols, area.h / rows)
			if size > best[0]:
				best = (size, cols)

		size, cols = best
		size = min(size, max_cell)
		rows = -(-len(shades) // cols)
		cell = size * 0.86
		sock_w, sock_h = cell * 0.72, cell
		x0 = area.x + (area.w - cols * size) / 2
		y0 = area.y + max(0.0, (area.h - rows * size) / 2)

		for i, shade in enumerate(shades):
			col, row = i % cols, i // cols
			icon = pygame.Rect(
				int(x0 + col * size + (size - sock_w) / 2),
				int(y0 + row * size + (size - sock_h) / 2),
				max(4, int(sock_w)),
				max(6, int(sock_h)),
			)
			draw_sock(surface, icon, shade, alpha)

	def draw_trash(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
		counts = self.engine.pending_discards
		white, black = counts[Color.WHITE], counts[Color.BLACK]
		inner = self.panel(
			surface,
			rect,
			f'Trash  -  {white} white, {black} black awaiting a six-pack',
		)

		can = pygame.Rect(inner.x, inner.y, min(150, inner.w // 4), inner.h)
		self.draw_can(surface, can)

		area = pygame.Rect(can.right + PAD, inner.y, inner.w - can.w - PAD, inner.h)
		pending = self.engine.pending_shades
		shades = list(pending[Color.WHITE]) + list(pending[Color.BLACK])
		if shades:
			self.draw_sock_grid(surface, area, shades, alpha=PENDING_ALPHA, max_cell=TRASH_CELL)
		else:
			self.text(surface, 'empty', (area.x, area.centery - 10), 'small', INK_DIM)

	def draw_can(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
		lid = pygame.Rect(rect.x, rect.y, rect.w, max(8, int(rect.h * 0.12)))
		body = [
			(rect.x + rect.w * 0.08, lid.bottom),
			(rect.x + rect.w * 0.92, lid.bottom),
			(rect.x + rect.w * 0.80, rect.bottom),
			(rect.x + rect.w * 0.20, rect.bottom),
		]
		pygame.draw.polygon(surface, CAN_BODY, body)
		pygame.draw.aalines(surface, CAN_DARK, True, body)
		pygame.draw.rect(surface, CAN_DARK, lid, border_radius=4)
		for k in (0.35, 0.5, 0.65):
			top = (rect.x + rect.w * (0.10 + k * 0.06), lid.bottom + 6)
			bottom = (rect.x + rect.w * (0.18 + k * 0.06), rect.bottom - 6)
			pygame.draw.line(surface, CAN_DARK, top, bottom, 2)

	def draw_roommates(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
		engine = self.engine
		n = engine.roommates
		row_h, view_h, max_scroll = self._mates_scroll_state()
		self._clamp_scroll()

		if max_scroll > 0:
			first = int(self.mates_scroll / row_h) + 1
			last = min(n, int((self.mates_scroll + view_h - 1) / row_h) + 1)
			title = f'Roommates  -  {first}-{last} of {n}'
		else:
			title = 'Roommates  -  offered vs picked'
		inner = self.panel(surface, rect, title)

		record = self.record
		visible = set(record.order[: self.revealed]) if record else set()
		current = record.order[self.revealed - 1] if record and self.revealed else None

		prev_clip = surface.get_clip()
		surface.set_clip(inner)
		for i in range(n):
			y = inner.y + i * row_h - self.mates_scroll
			if y + row_h < inner.y or y > inner.bottom:
				continue
			row = pygame.Rect(inner.x, int(y), inner.w, int(row_h) - 6)
			shown = bool(record and i in visible)
			sockless = bool(shown and i in record.sockless)

			# A sockless roommate is not a big number in a column - it is a
			# different kind of day. The whole row changes colour so it is the
			# first thing seen, not something read off a total.
			pygame.draw.rect(surface, BARE if sockless else FELT_DARK, row, border_radius=8)
			if sockless:
				pygame.draw.rect(surface, ALERT_TEXT, row, width=2, border_radius=8)
			elif i == current:
				pygame.draw.rect(surface, GOOD, row, width=2, border_radius=8)

			name = engine.player_names[i]
			order = ''
			if record and i in record.order:
				order = f'  #{record.order.index(i) + 1}'
			self.text(surface, f'{name}{order}', (row.x + 12, row.y + 8), 'small')

			total = engine.total_embarrassment(i)
			today = record.embarrassment.get(i, 0.0) if shown else 0.0

			if sockless:
				today_color = ALERT_TEXT
			elif shown and today > 0:
				today_color = ALERT
			elif shown:
				today_color = GOOD
			else:
				today_color = INK_DIM
			self.text(
				surface,
				f'embarr today {today:,.0f}' if shown else 'embarr today  -',
				(row.right - 12, row.y + 6),
				'mid',
				today_color,
				right=True,
			)
			self.text(
				surface,
				f'embarr total {total:,.0f}',
				(row.right - 12, row.y + 32),
				'small',
				ALERT_TEXT if sockless else INK_DIM,
				right=True,
			)

			base_y = row.y + int(row.h * 0.32)
			if not shown:
				self.text(surface, 'waiting to dress', (row.x + 14, base_y), 'small', INK_DIM)
			elif sockless:
				self.text(surface, 'NO SOCKS TODAY', (row.x + 14, base_y), 'mid', ALERT_TEXT)
				offered = record.offered.get(i, ())
				detail = (
					f'drew {len(offered)}  -  penalty {SOCKLESS_PENALTY:,.0f}'
					if offered
					else f'went without - penalty {SOCKLESS_PENALTY:,.0f}'
				)
				self.text(surface, detail, (row.x + 14, base_y + 26), 'small', ALERT_TEXT)
			else:
				self.draw_hand(surface, row, record, i, base_y)
		surface.set_clip(prev_clip)

		if max_scroll > 0:
			track = pygame.Rect(rect.right - 16, inner.y, 6, inner.h)
			pygame.draw.rect(surface, FELT_DARK, track, border_radius=3)
			thumb_h = max(24, int(inner.h * inner.h / (inner.h + max_scroll)))
			frac = self.mates_scroll / max_scroll
			thumb = pygame.Rect(
				track.x,
				inner.y + int((inner.h - thumb_h) * frac),
				track.w,
				thumb_h,
			)
			pygame.draw.rect(surface, INK_DIM, thumb, border_radius=3)

	def draw_hand(
		self,
		surface: pygame.Surface,
		row: pygame.Rect,
		record: DayRecord,
		index: int,
		base_y: int,
	) -> None:
		"""The handful this roommate saw, tagged wear / back / toss."""
		offered = record.offered.get(index, ())
		wear = set(record.wear_idx.get(index, ()))
		toss = set(record.discard_idx.get(index, ()))
		worn = record.worn.get(index)

		icon_h = max(20, min(40, int(row.h * 0.28)))
		icon_w = int(icon_h * 0.72)
		gap = 8
		for k, shade in enumerate(offered):
			icon = pygame.Rect(row.x + 14 + k * (icon_w + gap), base_y, icon_w, icon_h)
			draw_sock(surface, icon, shade, PENDING_ALPHA if k in toss else 255)
			if k in wear:
				ring, tag, color = GOOD, 'wear', GOOD
			elif k in toss:
				ring, tag, color = ALERT, 'toss', ALERT
			else:
				ring, tag, color = PANEL_EDGE, 'back', INK_DIM
			pygame.draw.rect(surface, ring, icon.inflate(4, 4), width=2, border_radius=4)
			label = self.font('tiny').render(tag, True, color)
			surface.blit(label, label.get_rect(midtop=(icon.centerx, icon.bottom + 2)))

		if worn:
			gap_n = abs(worn[0] - worn[1])
			score = record.embarrassment.get(index, 0.0)
			self.text(
				surface,
				f'wore {worn[0]} / {worn[1]}   diff {gap_n}   embarr {score:,.0f}',
				(row.x + 14, base_y + icon_h + 18),
				'small',
				INK_DIM if score == 0 else ALERT,
			)

	def draw_footer(self, surface: pygame.Surface) -> None:
		rect = pygame.Rect(0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H)
		pygame.draw.rect(surface, FELT_DARK, rect)
		if self._mates_scroll_state()[2] > 0:
			keys = (
				'SPACE play    RIGHT/LEFT roommate    '
				'WHEEL or PGUP/PGDN scroll    UP/DOWN speed    Q quit'
			)
		else:
			keys = (
				'SPACE play/pause    RIGHT next roommate / next day    '
				'LEFT previous roommate    UP/DOWN speed    Q quit'
			)
		self.text(surface, keys, (PAD, rect.y + 14), 'small', INK_DIM)

		if self.finished:
			self.text(
				surface,
				f'year complete  -  ${self.engine.total_spent:,.0f} spent',
				(WIDTH - PAD, rect.y + 14),
				'small',
				GOOD,
				right=True,
			)


def run_gui(
	engine: Engine,
	fps: int = 60,
	on_day: Callable[[DayRecord], None] | None = None,
) -> None:
	"""Open the visualiser and drive ``engine`` one day at a time."""
	pygame.init()
	pygame.display.set_caption('COMS W4444 - Socks')
	screen = pygame.display.set_mode((WIDTH, HEIGHT))
	clock = pygame.time.Clock()

	view = Visualizer(engine, on_day=on_day)
	pending = 0.0
	running = True

	try:
		while running:
			dt = clock.tick(fps) / 1000.0

			for event in pygame.event.get():
				if not view.handle_event(event):
					running = False

			if view.playing:
				pending += dt * view.speed
				# Cap the days simulated per frame so a high speed setting
				# cannot stall the event loop and make the window unresponsive.
				for _ in range(min(int(pending), view.speed)):
					view.advance()
					pending -= 1
					if view.finished:
						break
				pending = min(pending, 1.0)
			else:
				pending = 0.0

			view.draw(screen)
			pygame.display.flip()
	except KeyboardInterrupt:
		# Ctrl+C at the projector should close the window, not print a stack
		# trace over the top of the demo.
		pass
	finally:
		pygame.quit()
