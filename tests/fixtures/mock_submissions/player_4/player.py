from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player4(BasePlayer):
	"""Misreads the API and returns a scalar where a pair belongs."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		return Selection(wear=7)
