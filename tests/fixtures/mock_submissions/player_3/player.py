from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player3(BasePlayer):
	"""Infinite loop in the hot path - the classic projector-killer."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		while True:
			pass
