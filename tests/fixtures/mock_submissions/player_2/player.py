from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player2(BasePlayer):
	"""Runs fine for three days, then raises like a real off-by-one would."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		if turn.day > 3:
			raise IndexError('list index out of range')
		return Selection(wear=(0, 1))
