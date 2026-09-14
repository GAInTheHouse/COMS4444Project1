import json
import sys

from models.cli import settings


def test_defaults_write_an_auto_log():
	args = settings([])
	assert args.log == ''
	assert not args.gui


def test_log_path():
	args = settings(['--log', 'out.log', '--days', '360'])
	assert args.log == 'out.log'
	assert args.days == 360


def test_no_log_disables_the_default():
	assert settings(['--no-log']).log is None


def test_main_writes_log_and_json(tmp_path, monkeypatch, capsys):
	from main import main

	log_path = tmp_path / 'run.log'
	monkeypatch.setattr(
		sys,
		'argv',
		[
			'main.py',
			'--player',
			'g',
			'1',
			'--days',
			'3',
			'--log',
			str(log_path),
			'--timeout',
			'0',
			'--seed',
			'1',
		],
	)
	main()
	captured = capsys.readouterr()
	data = json.loads(captured.out)
	assert data['parameters']['days'] == 3
	assert str(log_path) in captured.err
	text = log_path.read_text(encoding='utf-8')
	assert 'day 3  ' in text
	assert 'snapshot after day 3 / 3' in text


def test_no_log_writes_nothing(tmp_path, monkeypatch, capsys):
	from main import main

	monkeypatch.chdir(tmp_path)
	monkeypatch.setattr(
		sys,
		'argv',
		['main.py', '--player', 'g', '1', '--days', '2', '--no-log', '--timeout', '0'],
	)
	main()
	json.loads(capsys.readouterr().out)
	assert not (tmp_path / 'logs').exists()
