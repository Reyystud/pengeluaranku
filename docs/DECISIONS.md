# Decisions log

One line per small decision. Design-level decisions get a full ADR in `docs/adr/` instead (link it here too).

Add new entries at the bottom. Never edit an old entry's meaning; supersede it with a new line.

Format: `| date | task | decision | reason | ADR/PRD ref |`

| Date | Task | Decision | Reason | Ref |
|---|---|---|---|---|
| 2026-11-19 | — | Project docs (CLAUDE.md, ADRs, PROGRESS, this log) are written in English | Matches the PRD; portfolio readers are English-speaking | PRD §23 |
| 2026-11-19 | T-19 (planned) | UI style: flat + bento-grid cards as the base; light glassmorphism (`backdrop-blur`) only as an accent on navbar, drawers, and landing hero, always over a solid fallback background. No neumorphism or claymorphism. Dark mode via color tokens from the start | Dashboard is data-dense and PRD §8.2 requires WCAG 2.1 AA contrast; heavy blur/shadow effects hurt contrast and perform worse on 360 px mobile | PRD §8.2, §8.3 |
| 2026-11-19 | T-01 | ML service import package is `services/ml_service/ml_service/` instead of `services/ml_service/app/` | Backend and ML service would both expose a top-level `app` package; they collide in the single shared uv workspace venv. Backend keeps `app` as in PRD §22 | PRD §22 (updated) |
| 2026-11-19 | T-01 | Workspace members are built with setuptools; `ml`, `data_generator`, `pipelines` map the package name to the member dir via `package-dir`, so the PRD layout (`ml/preprocessing`, not `ml/src/ml/...`) is kept | Keeps `import ml.preprocessing` working with the PRD folder structure | PRD §6.5, §22 |
| 2026-11-19 | T-01 | Workspace sync uses `uv sync --all-packages` (Makefile + CI); root `pyproject.toml` has `package = false` | Plain `uv sync` installs only the root, so member packages were not importable | PRD §6.5 |
| 2026-11-19 | T-01 | No runtime dependencies yet; each later task adds the libraries it needs (all from PRD §6.5). Dev tools: pytest, pytest-cov, hypothesis, ruff, mypy, pre-commit | Keeps T-01 a pure scaffold; lockfile pins resolved versions | PRD §6.5 |
| 2026-11-19 | T-01 | Coverage gates (backend 80%, ml 70%) and frontend checks are enabled when real code lands (T-11 / T-19), not on empty packages | Gates on empty packages are meaningless | PRD §5.3 |
| 2026-11-19 | T-01 | `docker-compose.yml` is deferred to T-29 as planned; `make up/down/demo` are stubs that fail with the owning task ID | PRD §20.3 assigns compose to T-29 | PRD §19.1 |
