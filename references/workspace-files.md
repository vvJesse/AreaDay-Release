# What a workspace contains

The workspace is the directory the user confirmed during intake. It accumulates
four kinds of file, and only the first kind is what the researcher ends up with.
The step-by-step list of names lives in
[mini-corpus-workflow.md](mini-corpus-workflow.md) ("Output layout"); this page
answers the question that list does not: which file is the deliverable, which one
is a handoff, which one must never be deleted, and which one is disposable.

The same split is enforced in code. `validate_initialized_workspace` and
`validate_completed_workspace` (`scripts/domain_registry.py:131`, `:145`) refuse
a workspace whose required files are missing or invalid, so a workspace that the
controller accepts already satisfies section 1.

## 1. Finished material — what the researcher receives

| Path | What it is | Written by |
| --- | --- | --- |
| `analysis/first-terminology-map.tsv` | domain terminology after review and orthography fixes | `scripts/finalize_host_review.py:163` |
| `analysis/personalized-vocabulary.tsv` | the learner's own classification per lemma (columns `lemma`, `classification`) | the calibration session (`scripts/vocabulary_calibration.py:619`) |
| `analysis/vocabulary-calibration-result.json` | the calibration result | the calibration session |
| `analysis/vocabulary-calibration-session.json` | the session state the result was computed from | the calibration session |
| `analysis/paper-decisions.jsonl` | one audit line per paper: kept, dropped, and why | `scripts/corpus_analysis.py:298` |
| `analysis/summary.md` | human-readable corpus summary | `scripts/corpus_analysis.py:378` |
| `analysis/domain-assets-summary.json` | roll-up that marks the corpus complete (`ready_for_calibration`) | `scripts/finalize_domain_assets.py:66` |

`full-workflow.md` ("Hand the verified service to the user") names the set the
final report must link: the calibration result, `personalized-vocabulary.tsv`,
`first-terminology-map.tsv`, and `paper-decisions.jsonl`.

A corpus counts as finished when `analysis/personalized-vocabulary.tsv` exists —
that is the file the unified app and the weekly brief read
(`scripts/domain_registry.py:170`, `scripts/continuous_workflow.py:332`).

## 2. Handoff files — what the host agent reads and writes

The controller never lets the host agent guess a filename. Every judgement call
appears in `status.json` as a `host_action_required` checkpoint with a
`next_action` block: read `next_action.input` or every file in
`next_action.inputs`, write `next_action.output`, then run `next_action.resume`
(`references/full-workflow.md:185`). The concrete paths for the four host
actions in one completed run:

| Step | The agent reads | The agent writes |
| --- | --- | --- |
| Retrieval strategy | `retrieval-strategy-state.json`, previous outcomes | the requested `retrieval-strategy-0N.json` (at most three strategies in total) |
| Candidate review | `candidate-review-packet.jsonl` | `candidate-review-selection.json` (a later attempt adds `-0N`) |
| Orthography review | `analysis/orthography-review-input.json` | `analysis/orthography-review-selection.json` |
| Learning assets | `analysis/terminology-review-input.json`, `analysis/vocabulary-card-review-input.json`, `analysis/vocabulary-card-review-batches/` | the supplied batch under `analysis/vocabulary-card-review-results/`, merged by the controller into `analysis/domain-review-selection.json` |
| Weekly brief | `continuous/working/<run-id>/agent-brief-input.json` | `continuous/working/<run-id>/brief-agent-output.json` |

Two conventions make these files safe to check automatically:

- every review JSON carries `schema_version: 1` and `reviewer: current-host-agent`;
  `scripts/finalize_domain_assets.py` rejects anything else;
- an input states how many items it expects (`candidate_count`, batch ids). Echo
  exactly that many items and never invent ids: the ids come from the packet
  file, not from memory.

## 3. State — never delete

| Path | Why it must survive |
| --- | --- |
| `status.json` | controller-owned lifecycle; `terminal: false` means the run has to be resumed, not restarted |
| `retrieval-strategy-state.json`, `search-attempts.json` | the three-strategy budget and the record of what was already tried |
| `analysis/papers.jsonl`, `analysis/vocabulary-map.tsv` | the corpus of record: initialization refuses to start without them (`scripts/domain_registry.py:85`) |
| `papers/*.pdf` | the downloaded corpus; rebuilding it costs OpenAlex requests |
| `cache/openalex-search/` | search cache for resumes and later briefs |
| `continuous/areaday.sqlite3`, `continuous/discovery/` | briefs, vocabulary, review log, discovery pool |
| `data/real-domains.json`, `data/global-learning.sqlite3` | in the Skill, not the workspace: the domain registry and the learning state shared by every domain |

## 4. Disposable output — safe to delete, rebuilt by a rerun

Deleting any of these costs time, never data: the controller recreates them from
the state above.

- acquisition: `candidates.jsonl`, `candidate-review-packet.jsonl`,
  `candidate-review-summary.json`, `download-results.jsonl`,
  `cold-start-summary.json`, `run-timings.json`;
- extracted text: `analysis/text/` (rebuilt from `papers/*.pdf`);
- analysis intermediates: `analysis/raw-terminology-candidates.{tsv,jsonl}`,
  `analysis/terminology-candidates.{tsv,jsonl}`,
  `analysis/pre-orthography-vocabulary-map.{tsv,jsonl}`;
- vocabulary cards: `analysis/vocabulary-card-catalog.jsonl`,
  `analysis/vocabulary-card-review-batches/`,
  `analysis/vocabulary-card-review-results/`,
  `analysis/vocabulary-card-summary.json` (derived from the finalized
  terminology and the corpus text by `scripts/vocabulary_cards.py`);
- brief runs: `continuous/working/<run-id>/` (temporary material, removed after a
  successful import; a failed run keeps its directory on purpose).

`run-timings.json` is never a completion signal: it is written for every attempt,
so it exists in aborted runs too. Read `status.json` instead.
