# Contributing to EBTTO

Thank you for your interest in contributing to EBTTO.

## How to Contribute

### Reporting Bugs
- Open an issue with: environment, steps to reproduce, expected vs actual behavior.
- For security issues, see `SECURITY.md` and report privately.

### Development
1. Fork the repository.
2. Create a branch: `git checkout -b feature/my-feature`
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Make your change. Add tests for new behavior.
5. Run the test suite: `python -m pytest -q`
6. Format: `ruff check --fix .`
7. Commit using conventional commits:
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation
   - `tests:` test only
   - `chore:` maintenance
8. Push and open a pull request.

### Pull Request Requirements
- [ ] Tests added for new behavior
- [ ] `pytest -q` passes
- [ ] No new secrets or author-specific paths
- [ ] `codegraph` index is up to date (if source changed)
- [ ] `git log` shows clear, real commits (no fake history)

### Code Style
- Type annotations where practical
- `ruff` for linting/formatting
- No chain-of-thought storage
- Secrets must never reach persistent storage

## Versioning

We follow [Semantic Versioning](https://semver.org/).

- Major: breaking changes to the plugin API
- Minor: new hooks, tools, or strategies
- Patch: bug fixes, docs, CI

## License

By contributing, you agree that your contributions will be licensed under the
Apache License, Version 2.0.
