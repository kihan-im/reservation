# CIP

Python/Playwright reservation automation. Use the `ponytail` skill: trace the shared path, then make the smallest safe change; use stdlib and existing code before dependencies.

- Keep 13/14/15-hour pipelines independent. Preserve per-slot `SUBMITTING` protection, server reread, and `NO_CHANGE` at the item limit.
- Never print, commit, or change `config.json`, `.reservation_state/`, `log/`, or screenshots. Do not commit or push unless asked.
- Start with local unit tests: `venv/bin/python -m unittest discover -s tests -v`. Use live browser/site checks only when a local mock cannot verify a site-specific change or the user explicitly requests it; use `--dry-run` unless an actual save is explicitly requested.
- Treat Windows scheduler and native-dialog behavior as Windows-only validation; do not claim macOS results prove them.
