# Tree-order finalist rating slate & rubric

Fixed BEFORE rating. All words from corpus.py. Rate at breadth=3, depth=3
(widest tree). Under tree ordering, all three knobs affect ONLY sibling order
within a parent group (decay also via dedup) — never membership. So the rubric
is per-group and structural, NOT the old flat tight->wild.

## Slate per knob

### decay_per_hop — live ordering knob (P1b: reorders 9/16 words, membership same)
Words: light, storm, whisper, fire (the strongest reorderers from P1b)
Settings: 0.00, 0.02 (default), 0.05

### family_penalty_step — within-group de-clusterer (see Step 1 frequency)
Words: light (lumin-), storm (storm-), brave (val-), bright
Settings: 0.00, 0.03 (default), 0.06

### alpha_origin — sibling-order within groups
Words: light, storm, shadow, dark (polysemous, where alpha moved most in 7.5)
Settings: 0.20, 0.35 (default), 0.50

## Rubric (answer per word per setting)

T1. Within each parent group, is the highest-ranked sibling the best/closest
    of that group? (yes / no + which group fails)
T2. Does the overall tree read logically — each hop level a sensible step out,
    groups coherent under their parent? (yes / no)
T3. Any sibling that reads as NOISE ranked above a better sibling in its group?
    (which group + words, or none)
T4. (family knob only) Do same-family siblings cluster in a way that reads as
    redundant (favor throttle ON) or as legitimate closeness (favor OFF)?

## Recording (one block per word per setting)
# <knob>=<value>  word=<word>
#   T1: ...
#   T2: ...
#   T3: ...
#   T4: ...  (family only)