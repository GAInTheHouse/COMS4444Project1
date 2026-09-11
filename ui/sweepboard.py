"""Pygame comparison table for a goal sweep.

No socks, no game rules. It paints the cells ``sweep.aggregate`` already
computed, in config order, so a budget ladder or a 4-vs-5 pairing stays
readable from the back of a lecture theatre.
"""

import math

import pygame

WIDTH, HEIGHT = 1280, 820
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
ALERT = (198, 48, 48)
ROW_EVEN = (30, 92, 48)
ROW_ODD = (26, 80, 42)
GOLD = (232, 196, 86)


class SweepBoard:
	"""A cell-by-cell table that redraws after every finished run."""

	def __init__(self, title: str, labels: list[str], total: int) -> None:
		pygame.init()
		pygame.display.set_caption('COMS W4444 - Goal comparison')
		self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
		self.clock = pygame.time.Clock()
		self.title = title
		self.labels = list(labels)
		self.total = total
		self.done = 0
		self.cells: dict[str, dict] = {}
		self.finished = False
		self.open = True
		self.last_run = ''
		self.fonts = {
			'big': pygame.font.Font(None, 40),
			'mid': pygame.font.Font(None, 26),
			'small': pygame.font.Font(None, 20),
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

	def update(self, cells: list[dict], done: int, last_run: str = '') -> None:
		self.cells = {c['label']: c for c in cells}
		self.done = done
		if last_run:
			self.last_run = last_run
		self.tick()

	def tick(self) -> bool:
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
		self.text(self.title.replace('_', ' '), (PAD, 16), 'big')
		if self.finished:
			state = 'complete  -  Q to close'
			color = GOOD
		else:
			state = f'running  {self.done} / {self.total} runs'
			color = WARN
		self.text(state, (PAD, 56), 'small', color)
		if self.last_run and not self.finished:
			self.text(self.last_run, (WIDTH - PAD, 56), 'small', INK_DIM, right=True)

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
			(body.x + 18, 'cell'),
			(body.x + 520, 'embarr / day'),
			(body.x + 760, '$ / year'),
			(body.x + 940, 'sockless'),
			(body.x + 1080, 'ran dry'),
		]
		for x, label in headers:
			self.text(label, (x, body.y + 14), 'small', INK_DIM)

		n = max(len(self.labels), 1)
		row_h = min(52, (body.h - 50) / n)
		ready = [
			c['aggregates']['mean_daily_embarrassment']['mean']
			for c in self.cells.values()
			if c.get('aggregates')
		]
		worst = max(ready, default=1.0)
		worst = max(worst, 1.0)
		best = min(ready) if ready else None

		for i, label in enumerate(self.labels):
			y = body.y + 48 + int(i * row_h)
			band = pygame.Rect(body.x + 8, y, body.w - 16, int(row_h) - 6)
			pygame.draw.rect(screen, ROW_EVEN if i % 2 == 0 else ROW_ODD, band, border_radius=8)
			cell = self.cells.get(label)
			if cell is None or not cell.get('aggregates'):
				self.text(label, (body.x + 18, y + 12), 'small', INK_DIM)
				self.text('waiting', (body.x + 520, y + 12), 'small', INK_DIM)
				continue

			emb = cell['aggregates']['mean_daily_embarrassment']['mean']
			spend = cell['aggregates']['spend_per_year']['mean']
			sockless = cell['aggregates']['sockless_days']['mean']
			dry = cell['budget_exhausted']
			winner = best is not None and emb == best
			if winner:
				pygame.draw.rect(screen, GOLD, band, width=2, border_radius=8)

			self.text(label, (body.x + 18, y + 8), 'small', GOLD if winner else INK)
			self.text(f'{emb:,.1f}', (body.x + 520, y + 8), 'mid')
			self.text(f'${spend:,.0f}', (body.x + 760, y + 8), 'mid')
			sock_color = ALERT if sockless > 0 else INK
			self.text(f'{sockless:,.1f}', (body.x + 940, y + 8), 'mid', sock_color)
			if dry['runs_exhausted']:
				dry_text = f'{dry["runs_exhausted"]}/{dry["runs_exhausted"] + dry["runs_survived"]}'
				self.text(dry_text, (body.x + 1080, y + 8), 'mid', ALERT)
			else:
				self.text('-', (body.x + 1080, y + 8), 'mid', INK_DIM)

			bar = pygame.Rect(body.x + 520, y + int(row_h) - 16, 200, 5)
			pygame.draw.rect(screen, FELT_DARK, bar, border_radius=3)
			frac = min(1.0, math.log1p(emb) / math.log1p(worst))
			fill = pygame.Rect(bar.x, bar.y, max(2, int(bar.w * frac)), bar.h)
			pygame.draw.rect(screen, GOOD if winner else WARN, fill, border_radius=3)

		pygame.draw.rect(screen, FELT_DARK, pygame.Rect(0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H))
		self.text(
			'config order, not a ranking  -  gold is lowest embarr/day so far  -  Q quits',
			(PAD, HEIGHT - FOOTER_H + 16),
			'small',
			INK_DIM,
		)
