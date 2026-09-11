from itertools import combinations

from core.engine import PACK_COST
from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer

THRESHOLD = 6


class GreedyPlayer(BasePlayer):
	"""Wears the closest-matching pair on offer, and discards a leftover sock
	only while the household can still afford to replace it.

	This is deliberately shallow: it is a sanity baseline for the simulator and
	a starting point for discussion, not a serious strategy. It ignores the two
	interesting questions entirely - it never reasons about how a discard
	reshapes the drawer for future turns, and it treats white and black socks
	as one undifferentiated shade axis.
	"""

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		i, j = min(
			combinations(range(len(offered)), 2), key=lambda p: abs(offered[p[0]] - offered[p[1]])
		)
		worn = (offered[i] + offered[j]) / 2

		discard: list[int] = []
		# ``budget_remaining`` is inf when no --budget was set, so this is
		# always true on an unlimited run and false once leftover cannot
		# cover a $10 pack.
		if turn.budget_remaining >= PACK_COST:
			# Throw out the leftover that sits furthest from what we just wore,
			# on the theory that it is the one most likely to embarrass someone
			# tomorrow.
			leftovers = [k for k in range(len(offered)) if k not in (i, j)]
			if leftovers:
				worst = max(leftovers, key=lambda k: abs(offered[k] - worn))
				if abs(offered[worst] - worn) > THRESHOLD:
					discard.append(worst)

		return Selection(wear=(i, j), discard=tuple(discard))
