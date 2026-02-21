import os


def test_e2e_flaky_spot_simulation():
    """Simulates a spot instance termination failure.

    Fails on first attempt, succeeds on retry.
    GITHUB_RUN_ATTEMPT is set automatically by GitHub Actions
    and increments when reRunWorkflowFailedJobs is called.
    """
    run_attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    if run_attempt < 2:
        raise RuntimeError(
            f"Simulated spot termination (attempt {run_attempt}). "
            "This should succeed on retry."
        )


def test_e2e_always_passes():
    assert True
