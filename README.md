# GHA Retry Failed Jobs

Sandbox repository to validate GitHub Actions smart retry mechanism for spot instances.

## What this tests

When running CI on spot instances, AWS can terminate the instance at any time, causing the job to fail. This repo tests an automatic retry mechanism that distinguishes spot interruptions from code bugs:

1. CI workflow runs unit tests + 2 e2e shards
2. Shard 1 fails on first attempt (simulates spot termination using `GITHUB_RUN_ATTEMPT` env var)
3. GitHub fires a `workflow_run` event when CI completes
4. `retry-failed-jobs.yml` picks up the event, inspects step-level conclusions to determine if the failure is retryable
5. Only retries if steps were **cancelled** (spot kill) — skips retry if steps **failed** (code bug)
6. Only the failed shard is re-run on attempt 2 — passed jobs are skipped

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
    ├── Fetches jobs via API
    ├── Checks step conclusions:
    │     step "cancelled" → spot termination → retryable
    │     step "failure"   → code bug        → not retryable
    └── Calls reRunWorkflowFailedJobs (if retryable)

Attempt 2:
  CI workflow re-runs ONLY failed jobs
    ├── unit-tests (skipped — already passed)
    ├── e2e-shards (0) (skipped — already passed)
    └── e2e-shards (1) ✅  (GITHUB_RUN_ATTEMPT=2, test passes)
  CI workflow completes (conclusion: success)

  GitHub fires workflow_run event → retry-failed-jobs.yml
    └── Skipped (conclusion == success)
```

Retries are capped at 3 attempts (`run_attempt < 3`).

## How spot vs code bug detection works

When a spot instance is terminated, the runner dies mid-step. GitHub marks that step as `cancelled` and the job as `failure`. When a test or lint step fails due to a code bug, the step completes with `conclusion: "failure"`.

| Scenario | Job conclusion | Failing step conclusion |
|----------|---------------|------------------------|
| Spot termination | `failure` | `cancelled` |
| Code bug | `failure` | `failure` |

The retry workflow fetches jobs via `listJobsForWorkflowRun` API and inspects step-level conclusions. If any failed job has a cancelled step, it retries. If any failed job has a step that explicitly failed, it skips retry entirely.

## How it works

The CI workflow (`ci.yml`) has no retry logic — it only runs tests. A separate workflow (`retry-failed-jobs.yml`) listens for CI completions via the `workflow_run` event:

```yaml
on:
  workflow_run:
    workflows: ['CI']
    types: [completed]
```

When CI finishes with a non-success conclusion and `run_attempt < 3`, the retry workflow:
1. Fetches all jobs for the run via the GitHub API
2. Checks step-level conclusions to determine if the failure is infrastructure-related
3. Only calls `reRunWorkflowFailedJobs` if the failure is retryable

No polling, no dispatch — GitHub's event system connects the two workflows automatically.

The only connection between the workflows is the **name string** `'CI'` matching `name: CI` in `ci.yml`.

## Key concepts

- **`workflow_run`** — GitHub Actions event that fires when a referenced workflow completes. The triggered workflow always runs from the default branch. No polling or dispatch needed.
- **`reRunWorkflowFailedJobs`** — GitHub REST API that creates a new attempt on an existing workflow run, re-running only the jobs that failed. Passed jobs keep their results.
- **`listJobsForWorkflowRun`** — GitHub REST API that returns all jobs and their steps for a workflow run. Used to inspect step-level conclusions.
- **`fail-fast: false`** — Prevents GitHub from cancelling remaining matrix shards when one fails. Essential for the retry pattern — all shards must finish so we know exactly which ones failed.
- **`permissions: actions: write`** — Required on the retry workflow for the `reRunWorkflowFailedJobs` API call.

## Step conclusion values

| Value | Meaning |
|-------|---------|
| `success` | Step completed successfully |
| `failure` | Step exited with non-zero code (code bug) |
| `cancelled` | Step was killed mid-run (spot termination, manual cancel) |
| `skipped` | Step was skipped |
| `null` | Step never completed (runner died) |

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
