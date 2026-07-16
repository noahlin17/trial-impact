.PHONY: test lint validate validate-posefidelity validate-congeneric architecture

# Run the unit test suite (dev .venv).
test:
	pytest -q

# Lint the app + tooling scripts.
lint:
	ruff check app/ validation/ tools/ regen_artifacts.py demo_e2e.py compare_estimators.py tests/

# Regenerate the scoring-validation stats + head-to-head figure from the committed,
# self-contained validation/results/scores.json (needs numpy + matplotlib; both are in
# requirements-dev.txt). Re-running the docking + MM-GBSA from scratch is the expensive
# path documented in validation/README.md and needs the trialsim + mmgbsa conda envs.
validate:
	python validation/analyze.py
	python validation/figure.py

# Regenerate the pose-fidelity (Experiment C) stats + figure from the committed,
# self-contained validation/pose_fidelity/results/selfdock.json (numpy + matplotlib).
# Re-running the docking from scratch needs the trialsim conda env (see that README).
validate-posefidelity:
	python validation/pose_fidelity/analyze.py
	python validation/pose_fidelity/figure.py

# Regenerate the congeneric-ranking (Experiment A) stats + figure from the committed,
# self-contained validation/congeneric/results/tyk2_scores.json (numpy + matplotlib).
# Re-running the docking + MM-GBSA from scratch needs the trialsim + mmgbsa conda envs.
validate-congeneric:
	python validation/congeneric/analyze.py
	python validation/congeneric/figure.py

# Regenerate the tracked README architecture diagram (requires matplotlib from
# requirements-dev.txt).
architecture:
	python tools/make_architecture.py
