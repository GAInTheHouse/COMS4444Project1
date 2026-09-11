from core.engine import Engine
from core.runlog import RunLog, bind
from core.sandbox import PlayerFault
from players.greedy_player import GreedyPlayer
from tests.test_engine import build


def test_log_records_every_day_and_a_results_snapshot(tmp_path):
	engine = build(days=5, seed=7)
	path = tmp_path / 'run.log'
	log = RunLog.create(str(path), engine, seed=7, budget=None)
	engine.run(on_day=bind(log, engine))
	log.finish(engine)

	text = path.read_text(encoding='utf-8')
	assert 'seed=7' in text
	assert 'days=5' in text
	assert 'GreedyPlayer' in text
	for day in range(1, 6):
		assert f'day {day}  ' in text
	assert 'drawer_shades' in text
	assert '======== snapshot after day 5 / 5 ========' in text
	assert '"total_spent"' in text
	assert '"parameters"' in text


def test_log_names_a_fault(tmp_path):
	class Broken(GreedyPlayer):
		def select_socks(self, offered, turn):
			raise PlayerFault('nope')

	engine = Engine(
		players=[Broken],
		capacity=40,
		selection_unit=4,
		days=1,
		seed=1,
		timeout=0,
	)
	path = tmp_path / 'fault.log'
	log = RunLog.create(str(path), engine, seed=1, budget=100.0)
	engine.run(on_day=bind(log, engine))
	log.finish(engine)
	text = path.read_text(encoding='utf-8')
	assert 'FAULT' in text
	assert 'nope' in text
	assert 'budget=$100' in text


def test_log_survives_summary_only(tmp_path):
	engine = build(days=4, seed=2, keep_records=False)
	path = tmp_path / 'thin.log'
	log = RunLog.create(str(path), engine, seed=2, budget=None)
	engine.run(on_day=bind(log, engine))
	log.finish(engine)
	text = path.read_text(encoding='utf-8')
	assert 'day 4  ' in text
	assert engine.records == []
