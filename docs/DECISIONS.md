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
| 2026-11-19 | T-02 | Taxonomy lives in code (`ml/taxonomy.py`, `taxonomy-1`), not YAML | One importable source for backend seed (T-12), generator, classifier labels, and FR-03.10; avoids a second file to keep in sync | PRD 4.6 |
| 2026-11-19 | T-02 | Added `config/cities_id.yaml` for the bundled city list of normalization step 5; loaders in `ml/config.py` (dir overridable with `SEI_CONFIG_DIR`) | PRD says "small bundled list" without a path; kept as data, not code | PRD 7.3.2, 22 |
| 2026-11-19 | T-02 | `config/generator/merchants.yaml`: >= 15 merchants for every expense and transfer category; income categories hold >= 5 counterparty/description templates instead | Brands are not meaningful for income (allowance, salary...) | PRD 10.1 |
| 2026-11-19 | T-02 | `ambiguous_with` field on a few merchants (Indomaret, Alfamart, Shopee, ShopeeFood, Watsons) marks the intentional ~5% label ambiguity for the generator | Implements the PRD ambiguity requirement as data | PRD 10.1 |
| 2026-11-19 | T-02 | Holidays 2025-2027 verified against official SKB 3 Menteri pages (Setneg for 2026/2027, detik for 2025) and checked by counts in a test. 2025 includes the 2025-08-18 cuti bersama added by the 2025-08-07 amendment. Both `national` and `collective_leave` are stored; which count as `is_holiday` is decided in T-08 | The 2027 SKB is already published (signed 2026-09-15). Source pages were read through a summarizing fetch tool, so spot-check against the SKB PDF if exactness matters | PRD 11.2.3 |
| 2026-11-19 | T-02 | Added runtime dependency `pyyaml` to `ml` and dev dependency `types-pyyaml` | Needed to load config files; not listed in PRD 6.5 | PRD 6.5 |
| 2026-11-19 | T-02 | Ramadan windows are not included in `holidays_id.yaml` | PRD marks Ramadan/holiday generator factors optional (`calendar_effects`); add with T-03 if wanted | PRD 10.1 |
