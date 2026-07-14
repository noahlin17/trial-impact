.PHONY: test lint validate

# Run the unit test suite (dev .venv).
test:
	pytest -q

# Lint the app + tooling scripts.
lint:
	ruff check app/ validation/ regen_artifacts.py demo_e2e.py compare_estimators.py tests/

# Regenerate the scoring-validation stats + head-to-head figure from the committed,
# self-contained validation/results/scores.json (needs numpy + matplotlib; both are in
# requirements-dev.txt). Re-running the docking + MM-GBSA from scratch is the expensive
# path documented in validation/README.md and needs the trialsim + mmgbsa conda envs.
validate:
	python validation/analyze.py
	python validation/figure.py
