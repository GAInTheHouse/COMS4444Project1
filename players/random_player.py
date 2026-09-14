import random

from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class RandomPlayer(BasePlayer):
	"""Wears two arbitrary socks and never discards. The do-nothing baseline:
	any real strategy should beat it on embarrassment, and nothing should beat
	it on cost, since it only ever spends on holes."""

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		a, b = random.sample(range(len(offered)), 2)
		return Selection(wear=(a, b))
