"""Pygame leaderboard for the tournament.

No socks, no drawer, no game rules. It only paints the standings dict that
``tournament.rank`` already computed. The engine still runs headlessly; this
is what you put on a projector while matches finish.
"""

import math

import pygame

WIDTH, HEIGHT = 1100, 820
HEADER_H = 88
FOOTER_H = 48
PAD = 22

FELT = (34, 102, 54)
FELT_DARK = (26, 80, 42)
PANEL = (28, 88, 46)
PANEL_EDGE = (96, 158, 112)
INK = (238, 246, 238)
INK_DIM = (170, 202, 178)
GOOD = (140, 220, 150)
WARN = (224, 158, 46)
ROW_EVEN = (30, 92, 48)
ROW_ODD = (26, 80, 42)
GOLD = (232, 196, 86)


class Leaderboard:
	"""A ranking table that can be redrawn after every finished run."""

	def __init__(self, title: str, rank_by: str, total: int, entrants: list[str]) -> None:
		pygame.init()
		pygame.display.set_caption('COMS W4444 - Tournament')
		self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
		self.clock = pygame.time.Clock()
		self.title = title
		self.rank_by = rank_by
		self.total = total
		self.entrants = list(entrants)
		self.done = 0
		self.standings: list[dict] = []
		self.pending = list(entrants)
		self.finished = False
		self.open = True
		self.last_match = ''
		self.fonts = {
			'big': pygame.font.Font(None, 40),
			'mid': pygame.font.Font(None, 28),
			'small': pygame.font.Font(None, 22),
		}
		self.draw()
		pygame.display.flip()

	def pump(self) -> bool:
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				self.open = False
			if event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_ESCAPE):
				self.open = False
		return self.open

	def update(
		self,
		standings: list[dict],
		done: int,
		pending: list[str] | None = None,
		last_match: str = '',
	) -> None:
		self.standings = standings
		self.done = done
		if pending is not None:
			self.pending = pending
		if last_match:
			self.last_match = last_match
		self.tick()

	def tick(self) -> bool:
		"""Pump events and repaint one frame. Call this while waiting on matches."""
		if not self.open:
			return False
		self.pump()
		if not self.open:
			return False
		self.draw()
		pygame.display.flip()
		self.clock.tick(30)
		return True

	def wait_to_close(self) -> None:
		self.finished = True
		if self.open:
			self.draw()
			pygame.display.flip()
		# Tests use SDL's dummy driver; there is no window to sit on.
		if pygame.display.get_driver() == 'dummy':
			pygame.quit()
			self.open = False
			return
		while self.open:
			self.pump()
			self.clock.tick(30)
		pygame.quit()

	def text(
		self,
		value: str,
		pos: tuple[int, int],
		name: str = 'small',
		color: tuple[int, int, int] = INK,
		right: bool = False,
	) -> None:
		image = self.fonts[name].render(value, True, color)
		rect = image.get_rect()
		setattr(rect, 'topright' if right else 'topleft', pos)
		self.screen.blit(image, rect)

	def draw(self) -> None:
		screen = self.screen
		screen.fill(FELT)
		pygame.draw.rect(screen, FELT_DARK, pygame.Rect(0, 0, WIDTH, HEADER_H))
		self.text(self.title, (PAD, 16), 'big')
		if self.finished:
			state = 'complete  -  Q to close'
			color = GOOD
		else:
			state = f'running  {self.done} / {self.total} matches'
			color = WARN
		self.text(state, (PAD, 56), 'small', color)
		if self.last_match and not self.finished:
			self.text(self.last_match, (WIDTH - PAD, 56), 'small', INK_DIM, right=True)
		self.text(
			f'ranked by {self.rank_by.replace("_", " ")}',
			(WIDTH - PAD, 22),
			'small',
			INK_DIM,
			right=True,
		)
		if self.total:
			frac = min(1.0, self.done / self.total)
			pygame.draw.rect(screen, PANEL_EDGE, pygame.Rect(0, HEADER_H - 6, WIDTH, 6))
			pygame.draw.rect(screen, GOOD, pygame.Rect(0, HEADER_H - 6, int(WIDTH * frac), 6))

		body = pygame.Rect(
			PAD, HEADER_H + PAD, WIDTH - 2 * PAD, HEIGHT - HEADER_H - FOOTER_H - 2 * PAD
		)
		pygame.draw.rect(screen, PANEL, body, border_radius=10)
		pygame.draw.rect(screen, PANEL_EDGE, body, width=2, border_radius=10)

		headers = [
			(body.x + 18, '#'),
			(body.x + 70, 'group'),
			(body.x + 280, 'embarr / day'),
			(body.x + 560, '$ / year'),
			(body.x + 760, 'sockless'),
		]
		for x, label in headers:
			self.text(label, (x, body.y + 14), 'small', INK_DIM)

		rows = list(self.standings)
		for code in self.pending:
			rows.append({'code': code, 'rank': None})
		n = max(len(rows), 1)
		row_h = min(56, (body.h - 50) / n)
		worst = max(
			(r['mean_daily_embarrassment']['mean'] for r in self.standings),
			default=1.0,
		)
		worst = max(worst, 1.0)

		for i, row in enumerate(rows):
			y = body.y + 48 + int(i * row_h)
			band = pygame.Rect(body.x + 8, y, body.w - 16, int(row_h) - 6)
			pygame.draw.rect(screen, ROW_EVEN if i % 2 == 0 else ROW_ODD, band, border_radius=8)
			rank = row.get('rank')
			if rank == 1:
				pygame.draw.rect(screen, GOLD, band, width=2, border_radius=8)
			if rank is None:
				self.text('—', (body.x + 22, y + 12), 'mid', INK_DIM)
				self.text(str(row['code']), (body.x + 70, y + 12), 'mid', INK_DIM)
				self.text('waiting', (body.x + 280, y + 14), 'small', INK_DIM)
				continue
			rank_color = GOLD if rank == 1 else INK
			self.text(str(rank), (body.x + 22, y + 10), 'mid', rank_color)
			self.text(str(row['code']), (body.x + 70, y + 10), 'mid')
			emb = row['mean_daily_embarrassment']['mean']
			spend = row['spend_per_year']['mean']
			sockless = row['sockless_days']['mean']
			self.text(f'{emb:,.1f}', (body.x + 280, y + 10), 'mid')
			self.text(f'${spend:,.0f}', (body.x + 560, y + 10), 'mid')
			self.text(f'{sockless:,.1f}', (body.x + 760, y + 10), 'mid')
			bar = pygame.Rect(body.x + 280, y + int(row_h) - 18, 240, 6)
			pygame.draw.rect(screen, FELT_DARK, bar, border_radius=3)
			# Log so a matching group and a forfeiting group can share a bar.
			frac = min(1.0, math.log1p(emb) / math.log1p(worst))
			fill = pygame.Rect(bar.x, bar.y, max(2, int(bar.w * frac)), bar.h)
			pygame.draw.rect(screen, GOOD if rank == 1 else WARN, fill, border_radius=3)

		pygame.draw.rect(screen, FELT_DARK, pygame.Rect(0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H))
		self.text(
			'each finished match updates this table  -  Q quits when complete',
			(PAD, HEIGHT - FOOTER_H + 16),
			'small',
			INK_DIM,
		)
