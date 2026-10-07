# Contributing

Thanks for helping. Keep changes small and focused.

## Before pushing

```bash
python -m pip install '.[test]'
python -m pytest -q
ruff check .
bash -n install.sh && bash -n uninstall.sh
```

## Conventions

- One logical change per commit, conventional message: `type: concise subject`
  (`fix:`, `feat:`, `chore:`, `perf:` …).
- Python 3.10+; no new runtime dependency without a reason — `lxml` and
  `trafilatura` are the only HTML-facing ones.
- Extraction changes: add a deterministic test in `tests/test_extraction.py`.
  The link-preserving fallback and the title extraction are tested by
  monkeypatching `trafilatura.extract` / using `TestClient`, so they stay
  offline and fast.
- Do not weaken the URL safety controls (`public_target`, per-redirect checks,
  the byte cap, the pinned-address connection) without a test that proves the
  guarantee still holds.
- Keep the loopback-only bind by default; the API has no authentication.
