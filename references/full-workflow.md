---
name: areaday-full-workflow
description: "Prepare one confirmed AreaDay domain, launch its verified calibration workbench, and finish the personalized vocabulary after the user's answers."
---

# AreaDay first-time workflow

Python commands below use `.venv/bin/python` on macOS. On Windows, replace it
with `.\.venv\Scripts\python.exe` and keep the remaining arguments unchanged.

Use this reference only when establishing or rebuilding a research domain. An
ordinary request to open vocabulary, briefs, review, or domain switching uses
the fast path in `SKILL.md`.

This reference needs no license check, no activation step, and no network
probe. There is no prediction service: profile confirmation, paper collection,
local corpus analysis, and the 30-question calibration all run locally in one
uninterrupted preparation operation.

## The lifecycle contract

There is one uninterrupted preparation operation:

```text
confirmed profile and workspace
        ↓
unattended research and host-agent review
        ↓
canonical vocabulary finalized
        ↓
vocabulary cards + terminology finalized
        ↓
registered library service started and live-verified
        ↓
user receives the 30-word calibration page
```

Discovery, candidate review, downloads, analysis, orthography review, and
terminology review are implementation checkpoints inside that operation. Never
report one of them as the outcome, never ask the user to return merely because a
checkpoint finished, and never interpret a helper process exit as permission to
stop. The user may leave the task while the host agent continues.

`<workspace>/status.json` is the only lifecycle record. Its meaning is strict:

- `terminal: false`: this task is still responsible for continuing. If
  `next_action.actor` is `current_host_agent`, do that review and immediately
  run the provided `resume` command. If a command is live, wait on that exact
  command. If status is `failed`, diagnose the preserved error and resume the
  same operation.
- `terminal: true` with `checkpoint: calibration_ready`: the automated
  preparation is finished and the next actor is the user. This is valid only
  after the live service proves it has the selected registered domain, a usable
  vocabulary question, and the exact finalized terminology count.

Do not call the whole initialization complete at that handoff. Full
initialization completes only after the user submits 30 answers and the result
and personalized TSV are verified.

The mini corpus is built locally. When calibration starts, the Skill assembles
only the compact word statistics listed in `vocabulary-calibration.md` and uses
them in the same process. PDFs, extracted text, sentences, paper sources, and
local paths never leave the confirmed workspace.

## Prepare the local runtime

Run commands from this Skill root. First check the Skill-local runtime.

macOS or Linux:

```bash
sh scripts/install.sh --check
```

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1 -Mode check
```

If dependencies are missing, tell the user that the first installation may
temporarily use about 2 GB, settles near 1.2 GB after verification and cache
cleanup, and may take several minutes. Request network and disk-write permission
once, then run the platform installer yourself.

macOS or Linux:

```bash
sh scripts/install.sh --install
```

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1 -Mode install
```

The launcher owns uv, managed Python 3.12, `.venv`, pinned packages, spaCy, and
the embedding model. Success requires exit code 0 and the final offline
verification reporting `"status": "ok"` after real spaCy and 384-dimensional
embedding inference. Do not create a second environment.

AreaDay may use keyed OpenAlex, arXiv, or a useful combination. Choose the
method autonomously from the confirmed research area (before this unattended
phase starts, the user has already been told that they may leave the task and
may not be available to answer another provider-choice question). OpenAlex has
no anonymous mode and stops with a configuration error without a personal key,
so configure the key before telling the user they can leave: key configuration
requires interaction. Never ask the user to paste a key into chat, print it, or
store it in corpus artifacts.

## Confirm the research domain

Ask the user to describe the research problem in their own words. Then ask
exactly three or four concise follow-up questions that together clarify:

- the central phenomenon, object, or outcome;
- what is in scope and which adjacent interpretation is wrong;
- the methods, evidence, or output that matters;
- optionally, indispensable papers, authors, venues, or terms.

Summarize the domain in ordinary language and ask for confirmation. In that
same confirmation, explain that 70 papers is a reference for an active
direction: if the accessible literature is genuinely sparse, preparation may
continue with the smaller high-relevance corpus that can be found, clearly
scoped as such. After confirmation, derive the technical retrieval plan
yourself. Default to English public full text, the most recent ten years, and
at most ten older foundation papers, while respecting any historical scope or
indispensable seeds the user already specified. The agent owns providers,
taxonomy IDs, queries, retry policy, and fallback order (the user has confirmed
the research scope before being told that they may leave the unattended task).

Write the confirmed research scope and the agent-owned retrieval plan in the
schema from `profile-format.md`. The plan may change across bounded retrieval
attempts as long as it remains faithful to the confirmed research area.

Propose one absolute local workspace and explain that it will contain PDFs,
text, caches, and analysis. Wait for explicit confirmation of that exact path.
Then create the directory and save the confirmed profile as
`research-profile-input.json`. The controller registers this exact workspace in
this Skill instance's own registry; never scan for domains or borrow another
Skill installation's registry.

## Run the one preparation operation

Tell the user:

> 你现在可以先离开这个任务，不需要守着对话；但在处理完成前，请暂时不要退出 Codex / Work Buddy 桌面应用，也不要关闭电脑。准备好后，我会直接打开校准页面让你回答 30 个单词。

Then run the controller. Use 70 papers for a real user build. The smaller value
10 is reserved for development acceptance experiments.

macOS or Linux:

```bash
.venv/bin/python scripts/initialize.py run \
  --profile <confirmed-workspace>/research-profile-input.json \
  --workspace <confirmed-workspace> \
  --target-papers 70
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\initialize.py run `
  --profile <confirmed-workspace>\research-profile-input.json `
  --workspace <confirmed-workspace> `
  --target-papers 70
```

Do not manually sequence `acquire_mini_corpus.py`,
`finalize_domain_assets.py`, `app/server.py`, or `open_workbench.py` during
normal initialization. The controller calls the deterministic helpers and
issues the host review requests. When a long helper yields a live session,
wait on the same session; do not launch a duplicate.

For each `host_action_required`, read `next_action.input` or every file in
`next_action.inputs`, write `next_action.output`, then immediately execute the
supplied `resume` command in this same task. The host actions include:

1. Retrieval strategy: when the current results are insufficient, create the
   requested next strategy from the existing profile and outcomes autonomously
   (the user was told before this phase that they may leave the task and may not
   see another question). Change provider, scholarly wording, synonyms, or search angle while
   staying inside the confirmed research scope. The controller rejects a
   duplicate strategy and never requests more than three total attempts.
2. Candidate review: select and order directly relevant title-and-abstract
   records, including enough relevant backups for failed links. Reject
   incidental keyword matches, off-scope disciplines, comments, replies,
   corrections, withdrawn records, and violations of the confirmed date or
   category boundary. Paper screening belongs to the current host agent (the
   user may already be away after the unattended handoff).
3. Vocabulary orthography review: review every queued lemma before any
   vocabulary-card lookup begins. Put every valid queued lemma in `lemma_keeps`, correct
   only confirmed lemma/fused-form errors in `lemma_replacements`, and put only
   extraction noise in `lemma_drops`. Every queued lemma must appear in exactly
   one of those three fields. The controller applies this review and writes the
   finalized vocabulary before continuing.
4. Learning-asset review: review terminology candidates and every unresolved or
   context-sensitive vocabulary-card candidate from the finalized vocabulary.
   The vocabulary-card input array is the top-level `.candidates` field; there
   is no `.vocabulary_cards` field. Verify its length against `candidate_count`
   before reviewing it. The controller supplies bounded batches sequentially;
   write only the supplied batch's glosses and drops. Never read or reproduce
   earlier batch outputs; the controller validates immutable batch results and
   merges them into the final selection. Keep stable
   shared multiword concepts supported by a representative source-paper
   sentence, supplying complete English meaning, Chinese meaning, concept role,
   and stable sense key. For every vocabulary-card candidate whose meaning can
   be determined confidently, supply a concise Chinese gloss, stable sense key,
   and brief rationale keyed by its finalized canonical lemma. Put uncertain or
   noisy lemmas in `vocabulary_card_drops` instead of forcing a gloss. Never
   bulk-fill review output from the first dictionary entry. For a unique corpus
   acronym expansion, use that expansion as the exact English meaning and its
   suggested sense key; a conflicting dictionary abbreviation must be rejected.

Every review JSON uses `schema_version: 1` and
`reviewer: current-host-agent`. After orthography finalization, the bundled
dictionary supplies only low-risk meanings for resulting canonical vocabulary;
its entries remain suggestions wherever corpus evidence triggers review. The
controller then runs `finalize_domain_assets.py` exactly once
to finalize and load the stable bilingual vocabulary-card catalog and
terminology, write `domain-assets-summary.json`, and return success only when
all assets are ready. Only then may it start the calibration service.

A clean `corpus_unavailable` terminal result is not initialization success. It
means all three online retrieval strategies were used without obtaining a
usable PDF (the user was told before this unattended phase that they may leave
the task and may not see another search-choice question).

The acquisition algorithm, evidence rules, and artifact layout are specified
once in `mini-corpus-workflow.md`. A target of 70 is a reference for an active
direction, not a minimum corpus size. A route gets a bounded retry in the same
invocation before fallback. Analysis runs whenever at least one usable PDF was
obtained; the final calibration handoff still requires its separate minimum of
30 unique vocabulary lemmas.

During acquisition, optimize for relevant usable PDFs rather than compliance
with one fixed provider plan or paper count. Try at most three meaningfully
different retrieval strategies, reusing every candidate and valid PDF already
found. The first strategy comes from the profile; if needed, the current host
agent writes the next strategy from previous outcomes and immediately resumes.
Once a target-70 run has at least 100 plausible candidates, stop searching
merely to enlarge the candidate pool; 100 is a sufficiency signal, not a hard
prohibition or a user decision point. If the available research is sparse and
the user accepted a corpus bounded by what can be found, proceed with the
relevant usable PDFs that exist and report their actual number rather than
claiming full-field coverage. Only when all three strategies produce no usable
PDF should the operation end and offer a later local PDF directory. Process that
directory together with all valid PDFs already collected. Continue the same
vocabulary workflow; provider metadata is optional for these local files, and
no separate import procedure is required. If a local paper has no public source
URL, identify it as a local paper in the learning asset; a missing URL must not
block finalization.

## Hand the verified service to the user

Do not construct or launch the page yourself. The controller starts the domain
through the same registry-identified library service used for later daily
opening. It verifies the service identity, selected domain, calibration state,
embedded terminology, `/api/terms`, and the reviewed terminology count before
it can return:

```json
{
  "status": "awaiting_user_calibration",
  "terminal": true,
  "checkpoint": "calibration_ready"
}
```

Require `service.vocabulary_ready: true` and
`service.terminology_ready: true`. Open only `next_action.url`, tell the user
that the 30 questions use first reaction, and stop so the user can answer. The
terminology set is already final and does not depend on those answers.

When the user finishes, read and validate
`analysis/vocabulary-calibration-result.json` and
`analysis/personalized-vocabulary.tsv`. Report the factual corpus, vocabulary,
terminology, familiarity, and A/B/C/D counts, and link the result, personalized
TSV, finalized terminology TSV, and paper-decision audit. Only then say that
initialization is complete.

Later workbench openings must use `scripts/open_workbench.py`; it reuses the
same compatible live service when present. Weekly scheduling follows
`continuous-workflow.md` and is not forced into initialization.

## Invariants

- All documents and content stay in the user-confirmed workspace, and the Skill
  instance uses only its own explicit registry. Nothing is sent to a server:
  vocabulary calibration assembles only the compact word statistics described
  in `vocabulary-calibration.md` and consumes them locally. Never scan the
  filesystem, infer another
  workspace, or copy domain data from another Skill installation.
- Vocabulary and terminology are both derived from retained full text. Titles
  and abstracts are for paper-level relevance only.
- Calibration never selects, removes, or redefines terminology.
- A helper checkpoint is never a task-completion signal. The controller returns
  control only for the verified calibration handoff or after all three bounded
  retrieval strategies end with no usable PDF in `corpus_unavailable`.
- `status.json` is a recovery and control contract, not a notification system.
