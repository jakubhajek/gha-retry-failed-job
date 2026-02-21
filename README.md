# GHA Retry Failed Jobs

Sandbox repository to validate GitHub Actions retry mechanism.

## What this tests

When running CI on spot instances, AWS can terminate the instance at any time, causing the job to fail. This repo tests an automatic retry mechanism:

1. CI workflow runs unit tests + 2 e2e shards
2. Shard 1 fails on first attempt (simulates spot termination using `GITHUB_RUN_ATTEMPT` env var)
3. `retry-failed-jobs` job dispatches a separate `retry-failed-jobs.yml` workflow
4. That workflow polls until CI completes, then calls `reRunWorkflowFailedJobs` API
5. Only the failed shard is re-run on attempt 2 — passed jobs are skipped

## Expected results

| Job | Attempt 1 | Attempt 2 |
|-----|-----------|-----------|
| unit-tests | pass | skipped |
| e2e-shards (0) | pass | skipped |
| e2e-shards (1) | **FAIL** | pass |
| retry-failed-jobs | dispatches retry | skipped |

The overall workflow run should end as **success** after attempt 2.

## How retry logic works

```
Attempt 1:
  CI workflow starts
    ├── unit-tests ✅
    ├── e2e-shards (0) ✅
    ├── e2e-shards (1) ❌  (GITHUB_RUN_ATTEMPT=1, test fails)
    └── retry-failed-jobs → dispatches retry-failed-jobs.yml
  CI workflow completes (status: failure)

  retry-failed-jobs.yml starts
    └── Polls CI run status... completed → calls reRunWorkflowFailedJobs

Attempt 2:
  CI workflow re-runs ONLY failed jobs
    ├── unit-tests (skipped — already passed)
    ├── e2e-shards (0) (skipped — already passed)
    ├── e2e-shards (1) ✅  (GITHUB_RUN_ATTEMPT=2, test passes)
    └── retry-failed-jobs (skipped — no failure)
  CI workflow completes (status: success)
```

Retries are capped at 3 attempts (`github.run_attempt < 3`).

## Why two workflows

`reRunWorkflowFailedJobs` cannot be called on a workflow that is still running. Since the retry job is part of the CI workflow, it cannot re-run itself. Instead, it dispatches a separate workflow (`retry-failed-jobs.yml`) which waits for CI to complete and then triggers the re-run.

The `retry-failed-jobs.yml` must exist on the default branch (`main`) before it can be dispatched via `workflow_dispatch`.

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
