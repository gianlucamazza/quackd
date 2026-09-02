## What

<!-- One or two sentences. Link the issue if there is one. -->

## Kind of change

- [ ] New or changed **verb** (`quackd/verbs/`) — I updated `docs/architecture.md` and `quackd list-verbs` shows it
- [ ] New or changed **`.duck` file** (`ducks/`) — `quackd validate` passes and I ran it with `--provider fake --robot microduck:sim2d`
- [ ] Transport / upstream API — every upstream method name is in `quackd/transport/upstream_api.py` marked `VERIFIED` (with a link) or `UNVERIFIED`, and `docs/transport-status.md` is updated
- [ ] Docs only
- [ ] Other

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` pass locally
- [ ] No network calls in tests; no API keys needed
- [ ] No Pollen Robotics assets (logos, meshes, videos) added
- [ ] CHANGELOG.md updated under *Unreleased*
