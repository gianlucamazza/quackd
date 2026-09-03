## What

<!-- One or two sentences. Link the issue if there is one. -->

## Kind of change

- [ ] New or changed **verb** (core in `quackd/verbs/core.py`, or an extension in `quackd/adapters/<name>/verbs.py`) — it has a `VerbSpec` in the owning manifest (without one it does not exist), I updated `docs/architecture.md`, and `quackd list-verbs --robot <adapter>:<backend>` shows it
- [ ] New or changed **`.duck` file** (`ducks/`) — `quackd validate` passes and I ran it with `--provider fake --robot microduck:sim2d`
- [ ] Adapter / upstream API — every upstream name is in that adapter's `upstream_api.py` (the Microduck's is `quackd/transport/upstream_api.py`) marked `VERIFIED` (with a pinned link) or `UNVERIFIED`, and `docs/adapter-status.md` or the adapter's page under `docs/adapters/` is updated
- [ ] Docs only
- [ ] Other

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` pass locally
- [ ] No network calls in tests; no API keys needed
- [ ] No upstream assets, from Pollen Robotics or the Open Duck Mini project (logos, meshes, videos) added
- [ ] CHANGELOG.md updated under *Unreleased*
- [ ] `uv run quackd validate ducks/*.duck` passes (CI runs it)
