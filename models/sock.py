import uuid
from dataclasses import dataclass
from enum import StrEnum

WHITE_START = 255
WHITE_FLOOR = 127
WHITE_FADE = 2

BLACK_START = 0
BLACK_CEILING = 64
BLACK_FADE = 1


class Color(StrEnum):
	WHITE = 'white'
	BLACK = 'black'


@dataclass(frozen=True)
class Sock:
	"""Engine-internal sock.

	The stable ``id`` exists so the engine can track individual socks for
	debugging, the visualizer and pooled-vs-separate analysis. It is NEVER
	exposed to players: they see shade values only, per the spec.
	"""

	id: uuid.UUID
	color: Color
	shade: int

	@property
	def worn_out(self) -> bool:
		"""True once the sock has faded as far as it can go."""
		if self.color is Color.WHITE:
			return self.shade <= WHITE_FLOOR
		return self.shade >= BLACK_CEILING

	def washed(self) -> 'Sock':
		"""Return a new Sock aged by one wear/wash cycle, clamped at the limit.

		Constructed directly rather than through ``dataclasses.replace``, which
		re-derives the field list and builds a kwargs dict on every call. This
		runs twice per roommate per day, so it is worth the explicitness.
		"""
		if self.color is Color.WHITE:
			shade = self.shade - WHITE_FADE
			return Sock(self.id, self.color, WHITE_FLOOR if shade < WHITE_FLOOR else shade)
		shade = self.shade + BLACK_FADE
		return Sock(self.id, self.color, BLACK_CEILING if shade > BLACK_CEILING else shade)


def pristine(color: Color) -> Sock:
	shade = WHITE_START if color is Color.WHITE else BLACK_START
	return Sock(id=uuid.uuid4(), color=color, shade=shade)
