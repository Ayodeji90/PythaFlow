# Eval Baseline

Recorded: 2026-07-28 10:45

baseline: 0.0%

## Notes

Run `uv run python -m evals.runner --baseline` to verify against this baseline.
Regenerate with `uv run python -m evals.runner --live && uv run python -m evals.runner`.

## Baseline Maintenance

When intentional changes affect scores (new features, prompt updates):
1. Run `uv run python -m evals.runner --live` to record new responses
2. Run `uv run python -m evals.runner` to verify replay
3. Run `uv run python -m evals.runner --baseline` to update baseline
4. Commit both the updated recordings and BASELINE.md