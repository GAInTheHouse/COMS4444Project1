"""Players that misbehave the way real student code misbehaves.

Every class here is something a group has plausibly committed by accident: a
crash on an edge case, numpy leaking out of a vectorised strategy, a slow
search that overruns its budget, indices that are the right numbers of the
wrong type. The engine's job is to turn each of them into one forfeited turn
and carry on.

``Forfeiter`` is the control. It does exactly what the engine substitutes when
a player faults - wear the first two socks, discard nothing - so a run against
it consumes the RNG identically to a run against any always-faulting player.
That is what makes "the other roommates were unaffected" checkable as
bit-identical results rather than a vague smell test.
"""

import time

from models.player import GameContext, PlayerSnapshot, Selection
from models.player import Player as BasePlayer


class Forfeiter(BasePlayer):
	"""The engine's own fallback behaviour, as a player."""

	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=())


class RaisesInConstructor(BasePlayer):
	"""Blows up before day 1. A bad config read, a missing file, a typo in
	__init__ - none of it reachable by the per-turn guard, because the engine
	builds every player before the first day starts."""

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)
		raise ValueError('bad config file')

	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=())


class HangsInConstructor(BasePlayer):
	"""Precomputes something that never finishes. Worse than raising: there is
	no traceback, just a projector that stops."""

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)
		while True:
			pass

	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=())


class SometimesRaises(BasePlayer):
	"""Crashes on even days only. The intermittent case is the realistic one:
	a strategy that works until some condition it never tested for."""

	def select_socks(self, offered, turn):
		if turn.day % 2 == 0:
			raise ZeroDivisionError('division by zero')
		return Selection(wear=(0, 1), discard=())


class ReturnsNone(BasePlayer):
	"""Forgot the return statement."""

	def select_socks(self, offered, turn):
		Selection(wear=(0, 1), discard=())


class ReturnsJunk(BasePlayer):
	"""Returned something that is not a Selection at all."""

	def select_socks(self, offered, turn):
		return {'wear': [0, 1], 'discard': []}


class NumpyIndices(BasePlayer):
	"""Indices computed with numpy. ``np.int64`` is not a Python ``int``, so
	these are the right numbers of the wrong type."""

	def select_socks(self, offered, turn):
		import numpy as np

		pair = np.argsort(np.array(offered))[:2]
		return Selection(wear=(pair[0], pair[1]), discard=())


class FloatIndices(BasePlayer):
	"""Indices that came out of a division somewhere."""

	def select_socks(self, offered, turn):
		return Selection(wear=(0.0, 1.0), discard=())


class OutOfRangeIndices(BasePlayer):
	"""Right type, wrong numbers. The counterpart to NumpyIndices: these two
	are the reason the range verdict and the type verdict read differently."""

	def select_socks(self, offered, turn):
		return Selection(wear=(0, len(offered) + 5), discard=())


class MutatesOffered(BasePlayer):
	"""Tries to edit the socks it was handed."""

	def select_socks(self, offered, turn):
		offered[0] = 255
		return Selection(wear=(0, 1), discard=())


class MutatesTurnContext(BasePlayer):
	"""Tries to rewrite its own turn - a cheaper day number, a smaller spend."""

	def select_socks(self, offered, turn):
		turn.total_spent = 0.0
		return Selection(wear=(0, 1), discard=())


class MutatesHistory(BasePlayer):
	"""Tries to append to the history tuple it was handed."""

	def select_socks(self, offered, turn):
		turn.embarrassment_history.append(0.0)
		return Selection(wear=(0, 1), discard=())


class SleepsUnderBudget(BasePlayer):
	"""Slow, but inside the limit. Must NOT fault."""

	NAP = 0.02

	def select_socks(self, offered, turn):
		time.sleep(self.NAP)
		return Selection(wear=(0, 1), discard=())


class SleepsOverBudget(BasePlayer):
	"""Overruns the limit on every turn."""

	NAP = 5.0

	def select_socks(self, offered, turn):
		time.sleep(self.NAP)
		return Selection(wear=(0, 1), discard=())


class RepeatedDiscard(BasePlayer):
	"""Valid wear, but names the same discard index three times."""

	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=(2, 2, 2))


class SingleDiscard(BasePlayer):
	"""The same request as RepeatedDiscard, stated once. Dedup means the two
	must produce identical runs."""

	def select_socks(self, offered, turn):
		return Selection(wear=(0, 1), discard=(2,))


class ClassStateStasher(BasePlayer):
	"""Keeps its notes on the class rather than the instance.

	Two roommates running this class share ``SEEN``, because that is how Python
	attribute lookup works. What matters is that the engine never puts another
	group's data within reach: every entry is this class's own turn, tagged
	with its own index.
	"""

	SEEN: list[tuple[int, int, tuple[int, ...]]] = []

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)

	def select_socks(self, offered, turn):
		type(self).SEEN.append((turn.day, self.index, tuple(offered)))
		return Selection(wear=(0, 1), discard=())

	@classmethod
	def reset(cls) -> None:
		cls.SEEN = []
