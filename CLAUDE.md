# img2schem

Photo/description → Claude-designed build (ops) → deterministic engine → WorldEdit `.schem` (Minecraft Java),
using the owner's real installed palette including mods. Python 3.11+ core, CLI-first; local web UI from Phase 3.

## Read first
- docs/SOW.md — full spec and phased plan. Follow §0 rules and §7 phase gates.
- docs/DSL.md — the ops language (also Claude's system-prompt reference). Change ops only via engine/ops.py.
- docs/DECISIONS.md — log every deviation from the SOW (context → decision → consequences).
- docs/archive/SOW_v1.0.md — earlier plan; referenced for kept requirements (R-IDs) and tiers.

## Conventions
- Arrays are [X, Y, Z], Y up; front facade at z=0 facing −Z (north). SOW §4.3.
- Every stage writes an artifact to the run dir and can be re-run from the previous artifact. The UI calls the same stages.
- Block states are modern strings. Never numeric IDs. Never legacy `.schematic`.
- Block IDs come only from the extracted palette (active instance) or palette/data/tiers.yaml. Never hard-code others.
- Claude writes ops, not blocks (`set` capped). Tool schemas are generated from engine/ops.py.
- Model IDs and prices live in config.yaml / pricing.yaml only.
- Secrets only via env vars. Never commit .env, extracted textures, atlases, or owner photos > 1 MB.

## Commands
- `pip install -e ".[dev,vlm,server]"`; `pytest -q`; `pytest -m replay`; `ruff check .`; `mypy img2schem`
- `img2schem instance list` · `img2schem palette build` · `img2schem palette report`
- `img2schem convert tests/fixtures/photos/example.jpg --designer template --out out/dev`
- `img2schem serve --open` (Phase 3+) · web: `cd web && npm i && npm run dev`
- External tests: `IMG2SCHEM_RUN_EXTERNAL=1 pytest -m external`

## Definition of done for any task
1. Tests added/updated and green (including replay).
2. Previews regenerated and visually checked (out/**/preview_*.png, debug_ops.png).
3. report.json shows no new warnings; usage/cost within budget for Claude stages.
4. DECISIONS.md updated if the SOW was deviated from.

---

# Working guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
