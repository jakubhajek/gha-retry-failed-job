# GHA Retry Failed Jobs

Sandbox repository to validate GitHub Actions retry mechanism.

## What this tests

When running CI on spot instances, AWS can terminate the instance at any time, causing the job to fail. This repo tests an automatic retry mechanism:

1. CI workflow runs unit tests + 2 e2e shards
2. Shard 1 fails on first attempt (simulates spot termination using `GITHUB_RUN_ATTEMPT` env var)
3. GitHub fires a `workflow_run` event when CI completes
4. `retry-failed-jobs.yml` picks up the event and calls `reRunWorkflowFailedJobs` API
5. Only the failed shard is re-run on attempt 2 — passed jobs are skipped

## Expected results

| Job | Attempt 1 | Attempt 2 |
|-----|-----------|-----------|
| unit-tests | pass | skipped |
| e2e-shards (0) | pass | skipped |
| e2e-shards (1) | **FAIL** | pass |

The overall workflow run should end as **success** after attempt 2.

## How retry logic works

```
Attempt 1:
  CI workflow starts
    ├── unit-tests ✅
    ├── e2e-shards (0) ✅
    └── e2e-shards (1) ❌  (GITHUB_RUN_ATTEMPT=1, test fails)
  CI workflow completes (conclusion: failure)

  GitHub fires workflow_run event → retry-failed-jobs.yml
    └── Calls reRunWorkflowFailedJobs

Attempt 2:
  CI workflow re-runs ONLY failed jobs
    ├── unit-tests (skipped — already passed)
    ├── e2e-shards (0) (skipped — already passed)
    └── e2e-shards (1) ✅  (GITHUB_RUN_ATTEMPT=2, test passes)
  CI workflow completes (conclusion: success)

  GitHub fires workflow_run event → retry-failed-jobs.yml
    └── Skipped (conclusion != failure)
```

Retries are capped at 3 attempts (`run_attempt < 3`).

## How it works

The CI workflow (`ci.yml`) has no retry logic — it only runs tests. A separate workflow (`retry-failed-jobs.yml`) listens for CI completions via the `workflow_run` event:

```yaml
on:
  workflow_run:
    workflows: ['CI']
    types: [completed]
```

When CI finishes with `conclusion: failure` and `run_attempt < 3`, the retry workflow calls `reRunWorkflowFailedJobs` to re-run only the failed jobs. No polling, no dispatch — GitHub's event system connects the two workflows automatically.

The only connection between the workflows is the **name string** `'CI'` matching `name: CI` in `ci.yml`.

## Key concepts

- **`workflow_run`** — GitHub Actions event that fires when a referenced workflow completes. The triggered workflow always runs from the default branch. No polling or dispatch needed.
- **`reRunWorkflowFailedJobs`** — GitHub REST API that creates a new attempt on an existing workflow run, re-running only the jobs that failed. Passed jobs keep their results.
- **`fail-fast: false`** — Prevents GitHub from cancelling remaining matrix shards when one fails. Essential for the retry pattern — all shards must finish so we know exactly which ones failed.
- **`permissions: actions: write`** — Required on the retry workflow for the `reRunWorkflowFailedJobs` API call.

## GITHUB_RUN_ATTEMPT

`GITHUB_RUN_ATTEMPT` is a built-in environment variable set automatically by GitHub Actions on every job. It starts at `1` and increments each time `reRunWorkflowFailedJobs` API (or manual "Re-run failed jobs" in the UI) creates a new attempt. We use it in `test_e2e_shard1.py` to simulate a spot failure: fail when `1`, pass when `2+`.

## Running tests locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# First attempt — shard 1 fails (simulates spot termination)
pytest tests/ -v

# Simulate retry (attempt 2) — all tests pass
GITHUB_RUN_ATTEMPT=2 pytest tests/ -v
```
