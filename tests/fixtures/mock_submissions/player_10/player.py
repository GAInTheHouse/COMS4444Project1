from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player10(BasePlayer):
	"""Constructor raises - currently kills the whole run."""

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)
		raise ValueError("bad config file")

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		return Selection(wear=(0, 1))
