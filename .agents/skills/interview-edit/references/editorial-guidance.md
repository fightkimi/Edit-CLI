# Editorial guidance for speech-led creator videos

Use this reference only when proposing or revising narrative choices. It supplies decision criteria,
not automatic quality guarantees. Preserve the speaker's meaning and mark uncertain choices for
review rather than inventing intent.

## Minimum edit brief

Infer only what the user has made clear. Resolve material gaps in this order:

1. format: interview, talking head, tutorial, review, or vlog;
2. audience and viewing context;
3. target duration or acceptable range;
4. must-keep claims, demonstrations, disclosures, or emotional beats;
5. protected ranges, speakers, wording, and prohibited transformations;
6. optional style preferences: pace, titles, subtitles, camera density, and B-roll restraint.

Do not block on a decorative preference. Do block when the missing choice could change meaning,
remove a required disclosure, misrepresent a review, or reorder a tutorial dependency.

## Shared selection rubric

For every proposed keep/remove/reorder decision, prefer evidence-backed reasons:

- **Keep:** advances the promise, supplies necessary context/evidence, demonstrates a step, reveals
  a meaningful turn, or preserves required attribution/disclosure.
- **Tighten:** repetition, recoverable hesitation, off-topic setup, or dead air whose removal does
  not change meaning or create an unnatural speech boundary.
- **Reorder:** only when the new order preserves factual causality and speaker intent. Record the
  source ranges transparently in the cut-list.
- **Emphasize:** use a camera change, title, still, B-roll, or subtitle when it adds comprehension;
  visual change frequency is not a quality metric by itself.
- **Escalate:** unclear pronoun/reference, conflicting takes, apparent factual contradiction,
  missing step, uncertain consent, or edit that may change the speaker's position.

Treat scene/silence detection, transcript search, and QC as candidate evidence. They do not decide
what is boring, true, safe, or on-brand.

## Format-specific priorities

| Format | Narrative spine | Usually protect | Common risk |
|---|---|---|---|
| interview | question/context → answer → evidence/turn | speaker intent, attribution, emotional cadence | removing qualifiers or making answers appear contiguous |
| talking head | promise → problem → explanation → takeaway/CTA | central claim and supporting logic | over-tight jump cuts or unsupported hook claims |
| tutorial | outcome → prerequisites → ordered steps → verification | dependency order, commands, warnings, visible result | reordering steps or hiding failure/recovery context |
| review | criteria → evidence → tradeoffs → verdict | disclosures, negative evidence, conditions on recommendation | turning a qualified view into an absolute endorsement |
| vlog | goal → progression → setback/turn → payoff/reflection | chronology when it carries meaning, location/time cues | montage that loses causal or emotional continuity |

`content_role` may record the format or local purpose without changing render semantics. Continue to
use the typed `primary`, `broll`, `still`, and `title` item kinds defined by the cut-list contract.

## Building a reviewable first cut

1. Work from corrected transcript ranges and current sync evidence when they exist.
2. Select a coherent primary spoken spine before adding visual enrichment.
3. Keep uncertain ranges and label the decision in the user summary; conservative inclusion is safer
   than irreversible semantic deletion.
4. Add camera changes and B-roll only where valid indexed/synchronized evidence supports them.
5. Keep subtitles within the item and safe area; do not silently rewrite spoken claims in captions.
6. Validate, render a preview, inspect preview QC, and compare the result with the brief.

The CLI does not currently publish, download online media, generate stock footage, predict retention,
or guarantee platform performance. Record these as product gaps instead of imitating public Skills
that expose different tools.
