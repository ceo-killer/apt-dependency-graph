PYTHON ?= python3
CONFIG ?= examples/demo.json

.PHONY: run test check

run:
	PYTHONPATH=src $(PYTHON) -m apt_graph --config $(CONFIG)

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) tools/check_rules.py
