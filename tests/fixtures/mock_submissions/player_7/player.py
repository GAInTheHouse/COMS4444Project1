import this_module_does_not_exist  # noqa: F401

from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player7(BasePlayer):
	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		return Selection(wear=(0, 1))
