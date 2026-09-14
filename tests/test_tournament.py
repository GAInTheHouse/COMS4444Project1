"""Standings, and the arithmetic behind them.

The course ruling is that no scoring rule exists inside a single run: a group is
ranked by its averages across every run it appeared in. So the things worth
pinning are that the right runs happen (mixed rosters and all-one-group
rosters both), that a group's average covers exactly the runs it played, and
that the output is reproducible.
"""

import json
import os

import pytest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import tournament as tn
from sweep import summarise_exhaustion

ENTRANTS = ['g', 'r']


def config(tmp_path, **overrides):
	body = {
		'name': 'unit',
		'roommates': [2],
		'seeds': [1, 2],
		'defaults': {'capacity': 40, 'unit': 4, 'days': 20, 'timeout': 0},
	}
	body.update(overrides)
	path = tmp_path / 'unit.json'
	path.write_text(json.dumps(body))
	return tn.load_config(path)


# ---------------------------------------------------------------- calibration


def test_calibration_ignores_the_configured_budget(tmp_path):
	"""It measures what the field spends when nothing stops it, so a budget in
	the config must not cap the measurement - otherwise the recommendation is
	just the number you already had."""
	cfg = config(tmp_path, grid={'budget': [10]})
	matches, _ = tn.build_matches(cfg, ENTRANTS)
	report = tn.calibrate(matches, cfg['seeds'], workers=1)

	assert report['max_total_spent'] > 10


def test_calibration_recommends_above_the_worst_spend(tmp_path):
	"""The whole point: every entrant must clear the cliff, so the figure is
	driven by the worst spender in the field, not the average one."""
	cfg = config(tmp_path)
	matches, _ = tn.build_matches(cfg, ENTRANTS)
	report = tn.calibrate(matches, cfg['seeds'], workers=1, margin=1.10)

	assert report['recommended_budget'] >= report['max_total_spent']
	assert report['worst_roster']


def test_calibration_rounds_to_whole_packs(tmp_path):
	"""Money only ever leaves in $10 packs, so a recommendation of $1,447 would
	be quietly the same budget as $1,440."""
	cfg = config(tmp_path)
	matches, _ = tn.build_matches(cfg, ENTRANTS)
	report = tn.calibrate(matches, cfg['seeds'], workers=1)

	assert report['recommended_budget'] % 10 == 0


def test_calibration_tracks_the_field(tmp_path):
	"""A cheap field must not inherit an expensive field's budget. This is the
	reason the threshold has to be re-measured when the entrants change."""
	cfg = config(tmp_path)
	greedy, _ = tn.build_matches(cfg, ['g'])
	random_only, _ = tn.build_matches(cfg, ['r'])

	rich = tn.calibrate(greedy, cfg['seeds'], workers=1)
	poor = tn.calibrate(random_only, cfg['seeds'], workers=1)

	assert poor['max_total_spent'] < rich['max_total_spent']
	assert poor['recommended_budget'] < rich['recommended_budget']


def test_a_bigger_margin_recommends_more(tmp_path):
	cfg = config(tmp_path)
	matches, _ = tn.build_matches(cfg, ENTRANTS)

	tight = tn.calibrate(matches, cfg['seeds'], workers=1, margin=1.10)
	loose = tn.calibrate(matches, cfg['seeds'], workers=1, margin=2.00)

	assert loose['recommended_budget'] > tight['recommended_budget']
	assert loose['max_total_spent'] == tight['max_total_spent']


# ---------------------------------------------------------------- matchmaking


def test_rosters_include_mixed_and_all_one_group(tmp_path):
	matches, skipped = tn.build_matches(config(tmp_path), ENTRANTS)
	rosters = {m.roster for m in matches}

	assert ('g', 'g') in rosters, 'an all-one-group roster must be played'
	assert ('r', 'r') in rosters
	assert ('g', 'r') in rosters, 'a mixed roster must be played'
	assert not skipped


def test_seating_order_is_not_played_twice(tmp_path):
	"""The engine reshuffles the order daily, so g+r and r+g are the same
	match. Running both would double the tournament for nothing."""
	matches, _ = tn.build_matches(config(tmp_path), ENTRANTS)
	rosters = [m.roster for m in matches]
	assert ('r', 'g') not in rosters
	assert len(rosters) == len(set(rosters))
	assert len(rosters) == 3  # gg, gr, rr


def test_every_arena_is_played_by_every_roster(tmp_path):
	cfg = config(tmp_path, grid={'budget': [None, 400]})
	matches, _ = tn.build_matches(cfg, ENTRANTS)
	assert len(matches) == 3 * 2
	assert len({m.arena for m in matches}) == 2


def test_illegal_arenas_are_skipped_not_crashed(tmp_path):
	"""C must be a multiple of 4 and exceed unit * n + 10. A roommate count
	the capacity cannot support is reported and dropped, not raised."""
	cfg = config(tmp_path, roommates=[2, 40], defaults={'capacity': 40, 'unit': 4, 'days': 10})
	matches, skipped = tn.build_matches(cfg, ENTRANTS)
	assert matches
	assert len(skipped) == 1
	assert 'n=40' in skipped[0]


# ---------------------------------------------------------------- ranking


def fake_run(cell, seed, roster, seat_scores, spend, exhausted=None):
	return {
		'cell': cell,
		'seed': seed,
		'roster': list(roster),
		'spend_per_year': spend,
		'total_spent': spend,
		'budget_exhausted_on_day': exhausted,
		'total_sockless_days': 0,
		'faults': 0,
		'seats': [
			{
				'code': roster[i],
				'index': i,
				'mean_daily_embarrassment': score,
				'total_embarrassment': score * 10,
				'sockless_days': 0,
			}
			for i, score in enumerate(seat_scores)
		],
	}


def test_a_group_is_averaged_over_every_seat_it_occupied(tmp_path):
	matches, _ = tn.build_matches(config(tmp_path), ENTRANTS)
	runs = [
		fake_run(0, 1, ('g', 'g'), [2.0, 4.0], 100.0),
		fake_run(1, 1, ('g', 'r'), [6.0, 50.0], 100.0),
	]
	report = tn.rank(matches, runs, ENTRANTS, 'mean_daily_embarrassment')
	standings = {row['code']: row for row in report['standings']}

	# g took three seats across two runs: 2, 4 and 6.
	assert standings['g']['seats'] == 3
	assert standings['g']['runs'] == 2
	assert standings['g']['mean_daily_embarrassment']['mean'] == pytest.approx(4.0)

	assert standings['r']['seats'] == 1
	assert standings['r']['runs'] == 1
	assert standings['r']['mean_daily_embarrassment']['mean'] == pytest.approx(50.0)


def test_spend_is_charged_to_everyone_at_the_table(tmp_path):
	"""One drawer, one bill. A group is implicated in the spend of every run it
	appeared in - that is the intended mechanism for punishing an overspender."""
	matches, _ = tn.build_matches(config(tmp_path), ENTRANTS)
	runs = [
		fake_run(0, 1, ('g', 'g'), [1.0, 1.0], 500.0),
		fake_run(1, 1, ('g', 'r'), [1.0, 1.0], 100.0),
	]
	report = tn.rank(matches, runs, ENTRANTS, 'mean_daily_embarrassment')
	standings = {row['code']: row for row in report['standings']}

	assert standings['g']['spend_per_year']['mean'] == pytest.approx(300.0)
	assert standings['r']['spend_per_year']['mean'] == pytest.approx(100.0)


def test_ranking_key_changes_the_order(tmp_path):
	"""There is deliberately no combined score, so the sort key is a choice the
	TA makes rather than a formula baked in."""
	matches, _ = tn.build_matches(config(tmp_path), ENTRANTS)
	runs = [
		fake_run(0, 1, ('g', 'g'), [1.0, 1.0], 900.0),
		fake_run(2, 1, ('r', 'r'), [99.0, 99.0], 10.0),
	]

	by_emb = tn.rank(matches, runs, ENTRANTS, 'mean_daily_embarrassment')
	by_spend = tn.rank(matches, runs, ENTRANTS, 'spend_per_year')

	assert [r['code'] for r in by_emb['standings']] == ['g', 'r']
	assert [r['code'] for r in by_spend['standings']] == ['r', 'g']
	assert by_emb['standings'][0]['rank'] == 1


def test_exhaustion_summary_separates_survivors_from_casualties():
	stats = summarise_exhaustion([None, 100, 200, None])
	assert stats['runs_exhausted'] == 2
	assert stats['runs_survived'] == 2
	assert stats['mean_day'] == pytest.approx(150.0)
	assert stats['earliest_day'] == 100

	nothing = summarise_exhaustion([None, None])
	assert nothing['runs_exhausted'] == 0
	assert nothing['mean_day'] is None


# ---------------------------------------------------------------- end to end


def test_a_small_tournament_runs_and_is_reproducible(tmp_path):
	cfg = tmp_path / 'small.json'
	cfg.write_text(
		json.dumps(
			{
				'name': 'small',
				'roommates': [2],
				'seeds': [1, 2],
				'defaults': {'capacity': 40, 'unit': 4, 'days': 30, 'timeout': 0},
			}
		)
	)

	first, second = tmp_path / 'a', tmp_path / 'b'
	tn.main([str(cfg), '--out-dir', str(first), '--entrants', 'g', 'r', '--workers', '1'])
	tn.main([str(cfg), '--out-dir', str(second), '--entrants', 'g', 'r', '--workers', '1'])

	assert (first / 'small.json').read_text() == (second / 'small.json').read_text()
	assert (first / 'small_standings.csv').exists()
	assert (first / 'small_runs.csv').exists()

	report = json.loads((first / 'small.json').read_text())
	assert {row['code'] for row in report['standings']} == {'g', 'r'}
	assert report['standings'][0]['rank'] == 1
	assert len(report['runs']) == 3 * 2  # three rosters, two seeds


def test_live_leaderboard_does_not_change_final_standings(tmp_path):
	"""--live only redraws a text table. The CSV/JSON must match a silent run."""
	cfg = tmp_path / 'live.json'
	cfg.write_text(
		json.dumps(
			{
				'name': 'live',
				'roommates': [2],
				'seeds': [1],
				'defaults': {'capacity': 40, 'unit': 4, 'days': 20, 'timeout': 0},
			}
		)
	)
	quiet, live = tmp_path / 'quiet', tmp_path / 'live'
	tn.main([str(cfg), '--out-dir', str(quiet), '--entrants', 'g', 'r', '--workers', '1'])
	tn.main([str(cfg), '--out-dir', str(live), '--entrants', 'g', 'r', '--workers', '1', '--live'])
	assert (quiet / 'live.json').read_text() == (live / 'live.json').read_text()


def test_gui_leaderboard_does_not_change_final_standings(tmp_path, monkeypatch):
	monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
	cfg = tmp_path / 'board.json'
	cfg.write_text(
		json.dumps(
			{
				'name': 'board',
				'roommates': [2],
				'seeds': [1],
				'defaults': {'capacity': 40, 'unit': 4, 'days': 20, 'timeout': 0},
			}
		)
	)
	quiet, gui = tmp_path / 'quiet', tmp_path / 'gui'
	tn.main([str(cfg), '--out-dir', str(quiet), '--entrants', 'g', 'r', '--workers', '1'])
	tn.main([str(cfg), '--out-dir', str(gui), '--entrants', 'g', 'r', '--workers', '1', '--gui'])
	assert (quiet / 'board.json').read_text() == (gui / 'board.json').read_text()
