import json

import pytest

from core.engine import Engine
from players.greedy_player import GreedyPlayer
from sweep import (
	METRICS,
	Cell,
	aggregate,
	build_jobs,
	load_config,
	summarise,
	summarise_exhaustion,
)

CONFIGS = ('configs/goal2_unit_comparison.json', 'configs/goal3_pooling.json')


def build(**kwargs) -> Engine:
	defaults = dict(players=[GreedyPlayer] * 4, capacity=44, selection_unit=4, days=120, seed=7)
	defaults.update(kwargs)
	return Engine(**defaults)


# ---------------------------------------------------------------- summary mode


def test_summary_mode_matches_full_mode_exactly():
	"""Dropping DayRecords is a memory optimisation, not a rule change."""
	assert build(keep_records=True).run() == build(keep_records=False).run()


def test_summary_mode_retains_no_records():
	engine = build(keep_records=False)
	engine.run()
	assert engine.records == []


def test_default_still_keeps_records_for_the_gui():
	engine = build(days=30)
	engine.run()
	assert len(engine.records) == 30


def test_faults_survive_summary_mode():
	"""faults() used to be derived from self.records. In summary mode there are
	no records, and a fault that vanishes from the report is a fault the TA
	cannot see on the projector."""

	class Broken(GreedyPlayer):
		def select_socks(self, offered, turn):
			raise RuntimeError('boom')

	engine = Engine(
		players=[Broken] * 2, capacity=40, selection_unit=4, days=5, seed=3, keep_records=False
	)
	results = engine.run()
	assert len(results['faults']) == 10
	assert 'boom' in results['faults'][0]


# ---------------------------------------------------------------- aggregation


def test_summarise_handles_a_single_seed():
	stats = summarise([4.0])
	assert stats['mean'] == stats['median'] == 4.0
	assert stats['stddev'] == 0.0


def test_summarise_reports_spread():
	stats = summarise([1.0, 2.0, 3.0])
	assert stats['mean'] == 2.0
	assert stats['median'] == 2.0
	assert stats['stddev'] == pytest.approx(1.0)


# ---------------------------------------------------------------- configs


@pytest.mark.parametrize('path', CONFIGS)
def test_shipped_configs_describe_legal_cells(path):
	"""Every cell must satisfy C % 4 == 0 and C > unit * n + 10, or the sweep
	dies partway through with half the grid already run."""
	config = load_config(path)
	assert config.cells
	for cell in config.cells:
		assert cell.capacity % 4 == 0, cell.label
		assert cell.capacity > cell.unit * cell.roommates + 10, cell.label


def test_goal2_holds_capacity_and_seeds_constant_across_units():
	"""The comparison is meaningless if anything but the unit varies."""
	config = load_config('configs/goal2_unit_comparison.json')
	assert {c.unit for c in config.cells} == {4, 5}
	assert len({c.capacity for c in config.cells}) == 1
	assert len({c.days for c in config.cells}) == 1


def test_goal3_matches_each_pooled_cell_to_a_solo_cell_of_equal_share():
	"""Pooled and separate cells must offer the same socks per person, or the
	result measures drawer size rather than pooling."""
	config = load_config('configs/goal3_pooling.json')
	shares = {c.capacity // c.roommates for c in config.cells}
	pooled = [c for c in config.cells if c.roommates > 1]
	solo = [c for c in config.cells if c.roommates == 1]
	assert pooled and solo
	for cell in pooled:
		assert cell.capacity // cell.roommates in shares


def test_grid_expands_as_a_cross_product(tmp_path):
	path = tmp_path / 'grid.json'
	path.write_text(
		json.dumps(
			{
				'name': 'g',
				'defaults': {'capacity': 44},
				'seeds': [1, 2],
				'grid': {'unit': [4, 5], 'players': [[['g', 4]], [['r', 4]]]},
			}
		)
	)
	config = load_config(path)
	assert len(config.cells) == 4
	assert len(build_jobs(config, keep_records=False)) == 8


def test_aggregate_keeps_cells_in_config_order():
	"""Workers finish out of order. The report must not."""
	config = load_config('configs/goal2_unit_comparison.json')
	config.seeds = [1]
	runs = [
		{
			'cell': i,
			'seed': 1,
			'spend_per_year': float(i),
			'total_spent': 0.0,
			'total_embarrassment': float(i),
			'mean_daily_embarrassment': float(i),
			'sockless_days': 0.0,
			'total_sockless_days': 0,
			'budget_exhausted_on_day': None,
			'budget_remaining': None,
			'faults': 0,
		}
		for i in reversed(range(len(config.cells)))
	]
	report = aggregate(config, runs)
	labels = [c['label'] for c in report['cells']]
	assert labels == [c.label for c in config.cells]


def test_cell_reports_roommates_from_the_player_spec():
	cell = Cell(label='x', players=(('g', 3), ('r', 1)), capacity=44, unit=4, days=10, timeout=1.0)
	assert cell.roommates == 4


# ---------------------------------------------------------------- budget


def test_budget_is_a_grid_axis(tmp_path):
	path = tmp_path / 'b.json'
	path.write_text(
		json.dumps(
			{
				'name': 'b',
				'defaults': {'capacity': 44, 'players': [['g', 4]]},
				'seeds': [1],
				'grid': {'budget': [None, 500, 1000]},
			}
		)
	)
	config = load_config(path)
	assert [c.budget for c in config.cells] == [None, 500.0, 1000.0]
	assert [c.budget_text for c in config.cells] == ['unlimited', '500', '1000']


def test_budget_defaults_to_unlimited():
	config = load_config('configs/goal3_pooling.json')
	assert all(cell.budget is None for cell in config.cells)


def test_shipped_budget_config_straddles_the_cliff():
	"""A sweep whose budgets are all on one side of the cliff shows nothing.
	The config has to contain both survivors and casualties."""
	config = load_config('configs/goal1_budget_sweep.json')
	budgets = [c.budget for c in config.cells]

	assert None in budgets, 'needs an unlimited control'
	assert any(b is not None and b >= 22500 for b in budgets), 'needs budgets above the cliff'
	assert any(b is not None and b <= 20000 for b in budgets), 'needs budgets below the cliff'
	assert len({c.days for c in config.cells}) == 1
	assert len({c.capacity for c in config.cells}) == 1
	assert len({c.players for c in config.cells}) == 1


def test_exhaustion_is_summarised_not_averaged():
	stats = summarise_exhaustion([None, 10, 20])
	assert stats['runs_exhausted'] == 2
	assert stats['runs_survived'] == 1
	assert stats['mean_day'] == pytest.approx(15.0)


def test_sockless_metrics_are_reported():
	assert 'sockless_days' in METRICS
	assert 'total_sockless_days' in METRICS


def test_aggregate_omits_cells_with_no_runs_yet():
	"""Live --gui feeds partial results. Empty cells must not crash summarise."""
	config = load_config('configs/goal3_pooling.json')
	config.seeds = [1]
	run = {
		'cell': 0,
		'seed': 1,
		'spend_per_year': 1.0,
		'total_spent': 1.0,
		'total_embarrassment': 0.0,
		'mean_daily_embarrassment': 0.0,
		'sockless_days': 0.0,
		'total_sockless_days': 0,
		'budget_exhausted_on_day': None,
		'budget_remaining': None,
		'faults': 0,
	}
	report = aggregate(config, [run])
	assert [c['label'] for c in report['cells']] == [config.cells[0].label]


def test_gui_sweep_does_not_change_final_json(tmp_path, monkeypatch):
	import sweep as sw

	monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
	cfg = tmp_path / 'board.json'
	cfg.write_text(
		json.dumps(
			{
				'name': 'board',
				'seeds': [1],
				'defaults': {'capacity': 40, 'unit': 4, 'days': 20, 'timeout': 0},
				'cells': [
					{'label': 'g4', 'players': [['g', 4]]},
					{'label': 'r4', 'players': [['r', 4]]},
				],
			}
		)
	)
	quiet, gui = tmp_path / 'quiet', tmp_path / 'gui'
	sw.main([str(cfg), '--out-dir', str(quiet), '--workers', '1'])
	sw.main([str(cfg), '--out-dir', str(gui), '--workers', '1', '--gui'])
	assert (quiet / 'board.json').read_text() == (gui / 'board.json').read_text()


def test_goal1_demo_straddles_a_one_year_cliff():
	config = load_config('configs/goal1_budget_demo.json')
	budgets = [c.budget for c in config.cells]
	assert None in budgets
	assert any(b is not None and b >= 2500 for b in budgets)
	assert any(b is not None and b <= 800 for b in budgets)
	assert config.cells[0].days == 360
