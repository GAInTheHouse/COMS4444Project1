from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player8(BasePlayer):
	"""Perfectly good code in a directory with no __init__.py."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		return Selection(wear=(0, 1))
