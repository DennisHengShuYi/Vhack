# Search Strategy Regressions — Post-mortem

This document records changes made **after `bd81f2c9`** that broke the search
strategy working at that commit, and the reasoning so they are not reintroduced.

## TL;DR

The "drones don't cover city/hazard zones" bug was caused by a single revert to
the opportunistic-scan rule. The other tuning changes were downstream attempts
to compensate and did not, on their own, cause the coverage collapse.

## Regression 1 — Unrestricted opportunistic scan during transit

**File:** `backend/server.py`, tick loop (Loop A)

**What I changed:**
```python
# Broken revert:
if not sim.zone.scanned_cells[ny][nx] or drone.voice_override:
    sim.scan(d_id)
```

**What was working at `bd81f2c9` (and restored in `9a5138bb` after this
regression was noticed):**
```python
# Correct:
if not sim.zone.scanned_cells[ny][nx]:
    if drone.voice_override:
        sim.scan(d_id)
    elif drone.assigned_zone_id:
        z = sim.zone.zones.get(drone.assigned_zone_id)
        if z and z.sx <= nx <= z.ex and z.sy <= ny <= z.ey:
            sim.scan(d_id)
```

**Why the revert broke coverage:**
- Drones transit between base and their assigned zone via `compute_path` (BFS).
  The path crosses cells in neighbouring zones.
- With the broken version, every transit cell got marked scanned.
- `assign_scan_zone` has an auto-complete pre-check: if every cell in a zone is
  already scanned, the zone is marked `COMPLETE` without dispatch.
- Edge zones (cheap flat/forest terrain on the way from base) get auto-completed
  from transit marks. Dense center zones (city + hazard) are costlier to route
  through, so nobody transits through them — they remain unscanned and the
  fleet never gets assigned there (other zones look "done" first).
- Smoking gun in the log: `Zone Z4 already fully covered by opportunistic scan
  — auto-completed`, while center zones had 0% coverage.

**Rule going forward:**
Opportunistic scan must only fire inside the drone's `assigned_zone_id` (or on
`voice_override` for the 3×3 intel sweep). Transit cells stay unscanned. Every
zone must be explicitly assigned and swept. Do not revert this without replacing
auto-complete with a different guarantee that center zones get covered.

## Regression 2 — Probability map de-normalization without consistent rescale

**File:** `backend/simulation.py`, `_init_probability_map` + `update_probability_after_scan`

Removed the `weights[y][x] /= total` normalization so raw terrain weights
(hazard=7, city=5, forest=2, flat=1) flow into `zone_score`. The intent was
stronger LLM discrimination between zone types.

**Why it was risky on its own:**
- `zone_score` values jumped from ~0.01–0.15 (normalized) to ~20–140 (raw).
- `WeightedPlanner._score` had `opt["score"] * 6.0` tuned for the normalized
  range. Without retuning, a 140-raw hazard score = 840 planner points — 10×
  larger than all other signals combined, collapsing the scoring nuance
  (transit bonus, lead/find bonuses, partial-resume).
- `update_probability_after_scan` boosted neighbour cells by `0.02 / 0.01` —
  invisible in the raw range. I rescaled to `3.0 / 1.5` to compensate, but the
  ratio between survivor-found boost and base weight changed.

**Rule going forward:**
If the probability map scale is changed, every downstream consumer must be
retuned in the same commit:
1. `WeightedPlanner._score` score multiplier
2. `update_probability_after_scan` neighbour-boost constants
3. Commander prompt's expected priority-number range
4. Any test fixtures that hardcode score values

Prefer to keep the map normalized and feed the LLM a separate, per-zone
terrain breakdown (`terrain_counts`) for discrimination.

## Regression 3 — Commander state snapshot lacked `score` and `terrain_counts`

**File:** `backend/simulation.py::get_status`, consumed by `agent/agent.py::_format_state`

At `bd81f2c9`, `get_status()` returned `self.zone.model_dump()`. The `Zone`
Pydantic model has no `score` or `terrain_counts` fields, so the Commander's
`_format_state` always saw `score=0 terrain={}`. Commander could not
distinguish hazard zones from flat zones when writing the PRIORITY line.

**Why this was not caught earlier:**
- The Pilot agent sees per-option terrain via `get_idle_drones()` output, so
  rule-path assignment still works.
- Commander's LLM output sometimes hallucinates reasonable priorities from the
  zone IDs alone — partial correctness masks the gap.

**Fix (kept in stash, not yet restored to HEAD):**
Enrich each zone dict in `get_status()` with `score` (sum of `probability_map`
over unscanned cells in the zone) and `terrain_counts` (dict of terrain type
→ cell count) before returning.

**Rule going forward:**
When adding a field that the agent's `_format_state` reads from state JSON, add
it to the `get_status()` output — do not assume `Zone.model_dump()` is the
single source of truth.

## Regression 4 — Hazard terrain generation coupled to city footprint

**File:** `backend/simulation.py::DisasterZone`

Added a fifth terrain type `hazard` grown via BFS inside existing `city` cells.
This is stashed feature work, not a regression by itself, but it interacts with
the above: a hazard-heavy zone's `zone_score` is `7 * hazard_count +
5 * city_count + ...` which under de-normalized scoring produces very large
values and compounds Regression 2.

**Rule going forward:**
If hazard terrain is reintroduced, treat it as a modifier on city zones
(hazard ⊂ city), keep `TERRAIN_SCAN_WEIGHT['hazard']` at a moderate value
(≤ 2× city), and re-verify that `WeightedPlanner` still picks the best zone
under the test fixtures in `agent/tests/test_commander.py`.

## Recovery reference

- Backup branch: `backup/pre-reset-20260420` (points to `9a5138bb`)
- Stash of uncommitted work at reset time: `stash@{0}` —
  *"pre-reset-to-bd81f2c9: hazard feature + Commander enrichment + radio/BrainPill fixes"*
- Cherry-pick targets for the two valid committed fixes above `bd81f2c9`:
  `09f7190b` (zone-release after `assign_scan_zone`) and
  `9a5138bb` (colour-coded logs + opportunistic scan restriction)
