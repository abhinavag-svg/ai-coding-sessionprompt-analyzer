# Contributing

Thanks for contributing to AI Coding Prompt Optimizer.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
```

## Run Tests

```bash
python -m unittest discover -s tests
```

## Typical Workflow

1. Fork the repository and create a feature branch.
2. Make focused changes with tests when behavior changes.
3. Run the unit tests locally.
4. Open a pull request with a clear description.

## Pull Request Guidelines

- Keep PRs small and scoped.
- Include context for behavior changes and user impact.
- Update docs when CLI flags or report structure changes.
- Avoid unrelated refactors in the same PR.

## Code Style

- Follow existing project style and naming conventions.
- Prefer deterministic logic for scoring and rules.
- Keep recommendation prompts constrained and evidence-based.
