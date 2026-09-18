# Operating profiles

OmniCodex exposes five routing strategies. Profiles define the **control-plane strength and delegation policy**, not a promise to use one model for every token.

## Economy

Goal: maximize useful work per quota.

- Control plane: Terra-first; use Sol for consequential planning/review.
- Bulk work: Luna and Terra.
- Astra: emergency escalation only.
- Aggressive de-escalation and context budgeting.

## Balanced

Goal: strong engineering quality with materially lower usage than all-premium execution.

- Control plane: **Sol / Medium**.
- Bulk work: Luna / Low and Terra / Medium.
- Sol / High: difficult specialist/review work.
- Astra: exceptional escalation.
- Default profile.

## Quality

Goal: favor decision quality while still avoiding premium-model waste.

- Control plane: **Sol / High**.
- Bulk implementation: Terra where bounded and safe.
- Sol performs more planning/review.
- Astra handles exceptionally difficult bugs, architecture or unresolved reasoning barriers.

## Max

Goal: maximum available capability.

- Control plane: **Astra**.
- Astra may retain more consequential work.
- Deterministic/mechanical work can still be delegated to Terra/Luna when quality is unaffected.
- Cost/quota is secondary to capability.

Max is not "Astra does every shell command." It is "Astra controls the task and decides where delegation is safe."

## Auto

Goal: choose the appropriate profile for the task and adapt when conditions change.

Candidate signals:
- blast radius;
- architectural scope;
- security/data integrity risk;
- ambiguity;
- number of modules involved;
- prior failed attempts;
- production criticality;
- reversibility.

Illustrative classification:

```
small deterministic change        -> Economy
normal product feature            -> Balanced
auth/data/concurrency refactor     -> Quality
repeatedly unresolved critical bug -> Quality/Max
```

Auto must remain explainable: it should state the selected profile and why.

## Overrides

Target UX, subject to runtime validation:

```
/omnicodex economy
/omnicodex balanced
/omnicodex quality
/omnicodex max
/omnicodex auto
```

A temporary task override should revert to the prior profile after completion.

## Invariant

Profiles change resource allocation, not acceptance criteria.
