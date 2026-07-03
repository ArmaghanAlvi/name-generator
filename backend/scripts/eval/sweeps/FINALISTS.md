# Knob sensitivity outcome & finalists

Epsilon for "moved": 0.02 (shape-aggregated proxy range across swept values).
Displacement threshold: 0.5 positions (mean rank change vs. center).
Selection rule: PER-SHAPE — a knob is a mover if it clears the displacement
threshold on ANY shape, and is rated in 7.6 on the shapes where it moves.

## Per-knob verdict (ordering-sensitive)

The four count/membership/spread proxies read FLAT for all three knobs — a
proxy-blindness artifact: these knobs tune ORDERING, which those proxies don't
measure (confirmed — knobs reorder 56–86/128 cells; storm reorders visibly under
alpha). Rank-displacement (mean position change vs. center) is the correct proxy.

- **decay_per_hop** — overall displacement 0.926; clears 0.5 on ALL shapes
  (short 1.337, polysemous 1.195, tight-concrete 0.866, abstract-quality 0.818,
  compositional-prone 0.762). MOVES ORDERING broadly. Finalists to rate:
  0.00, 0.02, 0.05. Rubric: rate across all shapes.

- **alpha_origin** — overall displacement 0.426; clears 0.5 on polysemous
  (0.626), near-misses tight-concrete (0.443) and abstract-quality (0.364).
  MOVES ORDERING on polysemous. Independently proven live (7.1 verification,
  storm cross-check) — not frozen despite sub-0.5 overall. Finalists to rate:
  0.20, 0.35, 0.50. Rubric: rate on POLYSEMOUS words (light, storm, shadow,
  dark, fire, bright), where origin-pull reorders competing senses.

- **family_penalty_step** — overall displacement 0.356; clears 0.5 on polysemous
  (0.565) and short (0.529). Low elsewhere BY DESIGN — the throttle only
  reorders same-family survivors, a minority of most sets. MOVES ORDERING in its
  narrow domain. Finalists to rate: 0.03, 0.06 (and 0.00 to see families
  un-throttled). Rubric: rate on FAMILY-HEAVY words (light/lumin-, storm/storm-,
  brave/val-), where morphological clusters appear.

## MIN_EXPANSION_SCORE gate (5c)
- Floor pathology: ABSENT — FROZEN, shared single-hop code untouched.
  Evidence: across 4961 vector-tier results, only 16 (0.3%) sit within 0.01 of
  the 0.78 floor; median vector score 0.864, min 0.785, zero below floor. No
  clustering at the threshold => the floor is not a binding constraint;
  lowering it would admit ~nothing, raising it would cut ~nothing.
  MIN_EXPANSION_SCORE stays sweepable-deferred; NOT threaded.
- NOTE: the earlier near-floor "cliff" count (21) read anchored_score (blended +
  decayed), a DIFFERENT scale than the raw similarity the floor gates — it was
  not valid floor evidence. The starved-cell count (35) was self-pruning
  convergence (river/fierce/wild/lion terminate early by design), orthogonal to
  the floor. Both dropped from the gate reasoning.

## Carried to 7.6
All three knobs move ordering on at least one shape, so all go to UI rating with
SHAPE-TARGETED rubrics (decay: all shapes; alpha: polysemous; family:
family-heavy). Reordering is what the user perceives, so aesthetic judgment —
not a proxy — picks the winner. Ties bias to the current default (6c).

Non-default settings to rate: 6 (alpha 0.20/0.50, decay 0.00/0.05,
family 0.00/0.06), plus the shared default center (alpha 0.35, decay 0.02,
family 0.03).
