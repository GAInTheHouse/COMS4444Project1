import numpy as np

from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player5(BasePlayer):
	"""Uses numpy, so its indices are np.int64 rather than int."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		idx = np.argsort(np.array(offered))
		return Selection(wear=(idx[0], idx[1]))
