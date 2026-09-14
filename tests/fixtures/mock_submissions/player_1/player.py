from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player1(BasePlayer):
	"""A plausible good submission: nearest pair, budget-gated discard."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		order = sorted(range(len(offered)), key=lambda i: offered[i])
		best = min(
			zip(order, order[1:]),
			key=lambda p: abs(offered[p[0]] - offered[p[1]]),
		)
		worn = set(best)
		drop = ()
		if turn.budget_remaining > 200:
			drop = tuple(i for i in range(len(offered)) if i not in worn and offered[i] in (127, 64))
		return Selection(wear=(best[0], best[1]), discard=drop)
