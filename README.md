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

## Why two workflows

`reRunWorkflowFailedJobs` cannot be called on a workflow that is still running. Since the retry job is part of the CI workflow, it cannot re-run itself. Instead, it dispatches a separate workflow (`retry-failed-jobs.yml`) which waits for CI to complete and then triggers the re-run.

The `retry-failed-jobs.yml` must exist on the default branch (`main`) before it can be dispatched via `workflow_dispatch`.
