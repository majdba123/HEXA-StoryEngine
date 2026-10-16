# Local test record

Worktree: `E:\HEXA-Admin`, branch `feature/admin-dashboard`, created from `origin/bayer` at `58c3074c6a095c23cee6a6691271ca7241146393`.

Initial `python -m pytest tests/web -q` could not run because the system Python lacked pytest. A dedicated `.venv` was installed with `pip install -e '.[dev]'`.

New focused account and export tests: `3 passed` at the first completed run. `ruff check app/web app/final/bundle.py`, Python compileall, and Node syntax checks passed at that point.

The first full `tests/web` run failed because existing test fixtures did not supply bootstrap credentials and still expected the removed shared-token login. Those tests are being migrated to authenticated test clients. Full regression, browser, and real-media certification are pending. This branch is not ready for release.
