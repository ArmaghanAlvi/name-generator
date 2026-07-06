# Stage 7.6 — Fixed judgment slate & rubric

Fixed BEFORE rating. Do not change words or rubric mid-rating (biases comparison).
All words come from the 32-word corpus (corpus.py). Rate at breadth=3, depth=3
unless noted — that's the widest cell, where reordering is most visible.

## Slate per knob (shapes where 7.5 showed the knob moves)

### decay_per_hop — moves on ALL shapes (rate broadly)
Words: light (polysemous), brave (abstract-quality), river (tight-concrete),
       frost (compositional-prone), joy (short), storm (polysemous)
Settings: 0.00, 0.02 (default), 0.05

### alpha_origin — moves on polysemous (rate polysemous)
Words: light, storm, shadow, dark, fire, bright
Settings: 0.20, 0.35 (default), 0.50

### family_penalty_step — moves on family-heavy words (rate those)
Words: light (lumin-), storm (storm-), brave (val-), bright (bright-)
Settings: 0.00, 0.03 (default), 0.06

## Rubric (fixed — answer per word per setting)

R1. Are the top-5 results all plausible near-synonyms? (yes / no + which fails)
R2. Does the order read tight->wild? (root-close first, drift later) (yes / no)
R3. Any result that reads as NOISE, and where does it rank? (rank + word, or none)
R4. Family monopoly: does one morphological root crowd the top-5?
    (family only — yes/no + which root)

## Recording (one block per word per setting; fill in Step 2)
# <knob>=<value>  word=<word>
#   R1: ...
#   R2: ...
#   R3: ...
#   R4: ...  (family knob only)
