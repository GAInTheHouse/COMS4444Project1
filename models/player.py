import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlayerSnapshot:
	"""Private, per-roommate information handed over at construction."""

	id: uuid.UUID
	index: int


@dataclass(frozen=True)
class GameContext:
	"""Public simulation parameters. Every player sees the same values.

	Per the spec, players know C and n. They do NOT know the shade
	distribution in the drawer, nor the current discard counts.
	"""

	capacity: int
	roommates: int
	selection_unit: int
	days: int


@dataclass(frozen=True)
class TurnContext:
	"""What a roommate is allowed to know on the morning of a given day.

	Spec: "You do know the day number, your full embarrassment history, and
	the total amount spent in socks since the start of the simulation."

	``embarrassment_history`` is built on demand rather than handed over
	ready-made. Materialising it eagerly copied a list that grows by one entry
	per day, for every roommate, on every turn - quadratic in the length of the
	run, and paid even by the majority of players that never read it. The
	tuple is cached once built, so a player that reads it repeatedly within a
	turn pays for it once.

	``_history`` is a callable rather than the engine's list, so the ordinary
	route hands back a fresh tuple that a player cannot mutate. It is not a
	sandbox: the callable closes over the engine's list, and a player willing
	to walk ``__closure__`` can reach it. That is deliberate rather than
	overlooked - closing the gap entirely and keeping the snapshot lazy are not
	both possible here, and laziness is what keeps a long run from going
	quadratic. The engine therefore scores on counters of its own and never
	reads that list back, so the worst a player achieves by tampering is
	lying to itself. See ``Engine.total_embarrassment``.

	``total_embarrassment`` and ``_history`` are keyword-only. They were added
	after the field they replaced, and accepting them positionally let the old
	three-argument call succeed with the history landing in the total.
	"""

	day: int
	total_spent: float
	total_embarrassment: float = field(kw_only=True)
	# What the household has left to spend. ``inf`` when no budget was set,
	# so a player can always compare against it without a None check.
	budget_remaining: float = field(default=float('inf'), kw_only=True)
	_history: Callable[[], tuple[float, ...]] = field(
		repr=False, compare=False, default=tuple, kw_only=True
	)

	@property
	def embarrassment_history(self) -> tuple[float, ...]:
		cached = self.__dict__.get('_cached_history')
		if cached is None:
			cached = self._history()
			object.__setattr__(self, '_cached_history', cached)
		return cached


@dataclass(frozen=True)
class Selection:
	"""A roommate's decision for the day.

	Indices refer to positions in the ``offered`` tuple for THIS turn only.
	They carry no meaning across turns: the same index tomorrow is a
	different sock.
	"""

	wear: tuple[int, int]
	discard: tuple[int, ...] = field(default_factory=tuple)


class Player(ABC):
	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		self.id = snapshot.id
		self.index = snapshot.index
		self.name = type(self).__name__
		self.capacity = ctx.capacity
		self.roommates = ctx.roommates
		self.selection_unit = ctx.selection_unit
		self.days = ctx.days

	def __repr__(self) -> str:
		return f'{self.name}(index={self.index})'

	@abstractmethod
	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		"""Choose two socks to wear and decide the fate of the rest.

		``offered`` holds ``selection_unit`` shade values in the range 0-255.
		Return a Selection whose ``wear`` names two distinct indices, and
		whose ``discard`` names any subset of the remaining indices. Anything
		not worn and not discarded goes back in the drawer unworn.
		"""
