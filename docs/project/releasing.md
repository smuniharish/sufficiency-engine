# Releasing

Releases are manual and performed by the maintainer; there is no publishing
workflow. The distribution is published to PyPI as `sufficiency-engine`, and the
documentation is built by Read the Docs from `.readthedocs.yaml`.

## Checklist

1. Confirm that the `main` branch passes continuous integration, including the
   PostgreSQL recovery job and, when its secrets are configured, the live model
   job. Locally, run `uv run python scripts/run_postgres_recovery.py` and
   `uv run python scripts/run_live_evaluation.py --repeats 3`.
2. Set the version in `pyproject.toml`, and `metadata.version` in both
   `SKILL.md` files, to the release version.
3. Move the `Unreleased` entries in `CHANGELOG.md` under the new version and
   state any change to the public API or stored session versions; see
   [Compatibility](compatibility.md).
4. Run the full local checks:

    ```bash
    uv lock --check
    uv run ruff check .
    uv run ruff format --check .
    uv run pyrefly check
    uv run pytest
    uv run zensical build --strict
    node scripts/render-diagrams.mjs --check
    ```

5. Build the distributions and verify them against `pyproject.toml`:

    ```bash
    uv build
    uv run python scripts/check_distribution.py
    ```

6. Install the wheel into a fresh environment and run the quickstart example.
7. Publish the files in `dist/` to PyPI with `uv publish`, using a credential
   that is never stored in the repository.
8. Tag the release commit with the version, for example `v0.1.0`, and push the
   tag.