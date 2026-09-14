from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player6(BasePlayer):
	"""Off-by-more-than-one: names a sock that was never offered."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		return Selection(wear=(0, len(offered) + 5))
