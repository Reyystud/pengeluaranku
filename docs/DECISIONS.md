# Decisions log

One line per small decision. Design-level decisions get a full ADR in `docs/adr/` instead (link it here too).

Add new entries at the bottom. Never edit an old entry's meaning; supersede it with a new line.

Format: `| date | task | decision | reason | ADR/PRD ref |`

| Date | Task | Decision | Reason | Ref |
|---|---|---|---|---|
| 2026-11-19 | — | Project docs (CLAUDE.md, ADRs, PROGRESS, this log) are written in English | Matches the PRD; portfolio readers are English-speaking | PRD §23 |
| 2026-11-19 | T-19 (planned) | UI style: flat + bento-grid cards as the base; light glassmorphism (`backdrop-blur`) only as an accent on navbar, drawers, and landing hero, always over a solid fallback background. No neumorphism or claymorphism. Dark mode via color tokens from the start | Dashboard is data-dense and PRD §8.2 requires WCAG 2.1 AA contrast; heavy blur/shadow effects hurt contrast and perform worse on 360 px mobile | PRD §8.2, §8.3 |
