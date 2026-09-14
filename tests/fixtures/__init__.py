"""Mock student players for the adversarial suite.

These live under tests/ rather than players/ on purpose. The registry only
matches directories named ``player_<digits>`` inside ``players/``, so nothing
here can ever be picked up as a real group - see
``test_adversarial.py::test_fixtures_are_not_discovered_as_a_group``.
"""
