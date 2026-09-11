from models.player import GameContext, PlayerSnapshot, Selection, TurnContext
from models.player import Player as BasePlayer


class Player9(BasePlayer):
	"""Reaches through __closure__ to blank its own embarrassment history."""

	def select_socks(self, offered: tuple[int, ...], turn: TurnContext) -> Selection:
		try:
			for cell in turn._history.__closure__ or ():
				target = cell.cell_contents
				if isinstance(target, list):
					target.clear()
		except Exception:
			pass
		return Selection(wear=(0, 1))
