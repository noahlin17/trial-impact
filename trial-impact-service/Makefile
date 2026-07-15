.PHONY: test lint validate validate-posefidelity validate-congeneric

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

# Regenerate the pose-fidelity (Experiment C) stats + figure from the committed,
# self-contained validation/pose_fidelity/results/selfdock.json (numpy + matplotlib).
# Re-running the docking from scratch needs the trialsim conda env (see that README).
validate-posefidelity:
	python validation/pose_fidelity/analyze.py
	python validation/pose_fidelity/figure.py

# Regenerate the congeneric within-target ranking (Experiment A) stats + figure from the
# committed validation/congeneric/results/<target>_scores.json (numpy + matplotlib).
# Re-running docking + MM-GBSA from scratch needs the trialsim + mmgbsa conda envs.
validate-congeneric:
	python validation/congeneric/analyze.py tyk2
	python validation/congeneric/figure.py tyk2
