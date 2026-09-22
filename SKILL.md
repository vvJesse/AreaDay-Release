---
name: areaday
display_name: AreaDay
display_name_en: AreaDay
description: "Build a local research area and personal domain vocabulary, view or generate research briefs, open the AreaDay workbench, or schedule weekly briefs and daily review reminders."
description_zh: "建立本地研究领域与个人词表，查看研究简报并进行复习。"
description_en: "Build a local research area and personal vocabulary, read briefs, and review terminology."
category: education
version: 1.1.0
author: AreaDay
---

# AreaDay

## Local-only operation

AreaDay runs entirely on the user's computer. There is no license, no
activation step, no device code, and no AreaDay server: every entrypoint works
offline from the start. Never ask for or mention a license, activation key, or
credential, and never describe AreaDay as licensed, activated, or bound to a
device limit. If the user asks about licensing, answer that this Skill needs
none.

For installation or upgrade requests, read
[INSTALL.md](INSTALL.md) completely, then perform its agent installation
protocol. Use [customer-installation.md](references/customer-installation.md)
only as supplementary customer-delivery context. Never describe the ZIP as a
desktop App or ask the user to perform terminal installation steps for you.

Commands in this file use `.venv/bin/python` for macOS. On Windows, always use
`.\.venv\Scripts\python.exe` in its place and keep every following argument
unchanged. Never try to execute the macOS `.venv/bin/python` path on Windows.

AreaDay has four user-facing capability groups:

- **首次建立**: establish a confirmed research area and build its personal
  domain vocabulary and terminology from a local research corpus.
- **日常使用**: open one unified workbench. Inside it, the user can:
  - 查看领域词表；
  - 查看最新或往期研究简报；
  - 复习生词与术语；
  - 自己切换研究领域。
- **研究简报**: view existing briefs, generate one brief now, or schedule weekly
  generation for an initialized domain.
- **复习提醒**: independently schedule a daily reminder when words or terms are due.

**打开工作台** is the single ordinary entry point for daily use. It does not
replace the separate product capability to establish a research area and build
its personal domain vocabulary.

When the user asks what AreaDay or this Skill can do, answer with concise
bullet points rather than one compressed paragraph. Use this structure:

> 我可以帮你：
>
> - **建立研究领域与个人领域词表**：围绕你确认的研究方向收集论文，生成个人化的领域生词和术语。
> - **打开研究工作台**：在一个界面里查看领域词表和研究简报、复习生词与术语，并自行切换研究领域。
> - **生成研究简报**：立即围绕选定领域生成并保存一份新的研究简报。
> - **开启自动每周研究简报**：按照设定的时间，为选定的研究领域持续生成简报。
> - **设置每日复习提醒**：只在有到期生词或术语时提醒复习。

Keep vocabulary viewing, brief viewing, review, and domain switching grouped as
things the user does inside the workbench, not separate agent-operated commands.
Do not hide initialization behind the vague phrase "建立工作台"; explicitly say
that AreaDay can establish a research area and build a personal domain
vocabulary.

## Host permissions to request once

AreaDay runs inside the host's own permission model. Before the first step that
needs one, request every permission that step requires in a single request, name
the concrete provider or path each one covers, and wait for the grant instead of
starting the work and retrying it later.

**Network egress.** Metadata search and OpenAlex usage accounting talk to
`api.openalex.org`, and full-text retrieval talks to `content.openalex.org` plus
the publisher and repository hosts named in the paper metadata, so allow general
HTTPS egress rather than a fixed host list. `arxiv.org` and `export.arxiv.org`
are contacted only when arXiv is one of the selected providers. A delivery
package whose portable runtime is present downloads nothing; only a from-source
installation may reach the Python package indexes, the `uv` release host, and the
model endpoint. AreaDay sends nothing anywhere else: ONNX Runtime telemetry is
disabled, and there is no AreaDay server.

**Writes outside this task's writable roots.** The upgrade-safe registry, the
global learning state, the OpenAlex configuration file (`credentials.ini`) and
the embedding model all live in this Skill's own `data/` directory, next to the
installed runtime and virtual environment. Registered workspaces are written as
well, and they may be anywhere on the filesystem. A host that can grant only one
writable root therefore only has to grant this Skill directory. Nothing in the
environment can move these files: that ``data/`` directory is the only place
AreaDay reads them from.

**Loopback for the workbench.** The launcher binds `127.0.0.1` on port 8765, or on
a nearby fallback port, connects to that same local address to confirm the
service is ready, and returns the URL for the host to open in the user's browser.
`--port` pins the preferred port when the sandbox allows only one.
A sandbox that refuses local connections breaks that readiness check, not the
page itself: the launcher then reports the refused bind as a permission
restriction rather than as a busy port. Request local-binding and loopback access
for the single launcher command, or let the user run that step with the host's
network restriction lifted.

**Scheduled tasks.** Weekly briefs and daily reminders need the operating
system's own scheduler. AreaDay only writes the schedule handoff and the reminder
state; the host creates the scheduled task, which may need its own permission
step.

If the user or the host refuses a permission, say which step stops working and
what the alternatives are. Do not silently degrade, and do not invent a
workaround that leaves papers, vocabulary, or learning state in an unexpected
place.

## Open the workbench: fast path

Requests to open AreaDay, view vocabulary or briefs, review words or terms,
or switch domains all use this fast path. A specific request may choose the
matching landing view, but it remains the same workbench.

From this Skill directory, run exactly one launcher command:

```bash
.venv/bin/python scripts/open_workbench.py --view <vocabulary|briefs|review>
```

Opening the workbench writes learning state beside this instance's registry and
inside its registered workspaces. When those paths are outside the current
task's writable roots, obtain host filesystem permission before running this
single launcher command, together with the loopback access listed under Host
permissions to request once. Do not first run it in a restricted sandbox and then
retry: a startup failure must be reported from that one invocation with its
original cause.

Add `--domain <registered-domain-id>` only when the user explicitly named a
domain. Otherwise let the launcher reuse the running workbench or select the
registry's active domain. Do not infer authorization from an ambient browser
tab.

The launcher performs the operational work: it treats port 8765 as the preferred
port, identifies a compatible live AreaDay service across its bounded fallback
range by exact registry, starts the registered-domain service only when needed,
replaces a verified same-registry service whose loaded domain set is stale,
waits until it is ready, and prints the exact user-facing URL. An unattended
workbench exits after one hour by default; the open page tells the user to reopen
AreaDay through Codex or WorkBuddy. Do not repeat
runtime checks, registry inspection, server startup, identity checks, port
selection, or URL construction outside the launcher.

The production Skill uses one upgrade-safe AreaDay registry in the operating
system's application-data directory. The installer performs one exact legacy
migration from the former sibling legacy-data directory;
it never scans for or imports unrelated workspaces. Each registry entry stores
the domain ID, display name, and the absolute path of the actual user-confirmed
workspace. That workspace—and its papers—may be anywhere on the filesystem.
Global learning state lives beside the registry.

Open the returned URL through the host's direct page-opening capability and
then stop. Do not inspect the page, take control of the page, click a tab or
button, start a review session, reload it, or test the interface unless the user
explicitly asks for diagnosis or UI testing. The user operates the workbench.

The exact returned URL must contain the launcher-selected port, selected domain,
and landing view. Port 8765 remains preferred; a nearby fallback may be used
when it is unavailable:

```text
http://127.0.0.1:<selected-port>/?domain=<domain-id>#<view>
```

## First-time initialization

If no registered domain exists, explain that the first research area must be
initialized before the workbench can open. Treat any request to establish a
research area or build or rebuild its personal domain vocabulary—including
“构建词表”—as equivalent to `$areaday init`: read
[full-workflow.md](references/full-workflow.md) completely, and
[workspace-files.md](references/workspace-files.md) for what the workspace then
holds: finished material, handoff files, state that must survive, and
disposable output.

Treat everything after the user confirms the profile and workspace—discovery,
candidate review, PDF acquisition, corpus analysis, orthography review,
terminology review, joint finalization, and verified workbench startup—as **one
unattended preparation operation**. Use `scripts/initialize.py` for the normal
online-acquisition path; do not present its internal checkpoints as independent
stages. A user-provided PDF directory is an input to the same preparation
operation, not a separate user workflow, so the agent may use the available
local analysis tools to continue from those files.

During that existing profile-and-workspace confirmation, make clear that 70 is
a reference for an active direction: if accessible literature is genuinely
sparse, the workflow may continue with the smaller high-relevance corpus that
can be found, clearly scoped as such. Do not create a later confirmation
checkpoint solely for corpus size.

During corpus acquisition, choose keyed OpenAlex, arXiv, or a useful
combination autonomously (before this unattended phase starts, the user has
already been told that they may leave the task and may therefore not be
available to answer another provider-choice question). OpenAlex needs the
customer's own API key and has no anonymous fallback, so complete the key setup
before the unattended operation: run `.venv/bin/python scripts/configure_openalex.py
--check` to see whether a key is already configured. When it is not, run
`.venv/bin/python scripts/configure_openalex.py`, which opens the credentials
file in the user's own editor and returns at once, then stop and hand over: tell
the user to paste the key after `api_key =`, save the file and say when they are
done. Never ask for the key in chat, never wait or poll for it, and never print
the saved value. When the user says they are done, run `--check` again and
continue once it reports a usable key. `scripts/initialize.py run` enforces the
same rule before its first checkpoint: without a usable key it opens the
credentials file and exits with code 4. Exit code 4 means stop and hand over —
never retry it in a loop, and never treat the missing key as something to work
around. Try at most three
meaningfully different retrieval strategies. A target of 70 papers is a useful
reference for an active direction, not a viability floor. For a target-70 run,
100 plausible candidates are already enough to stop searching merely for more
candidates; this is not a hard cap. Where the available research is sparse and
the user accepted a corpus bounded by what can be found, a smaller high-relevance
corpus (including roughly 20–30 PDFs) may continue through analysis. If all
three strategies produce no usable PDF, end cleanly and explain that the user
may later provide a directory of relevant PDFs. When such a directory is
provided, use its valid PDFs together with every valid PDF already collected.
Continue the same workflow without requiring a separate import procedure or
provider metadata. A local paper does not need a public source URL; label it as
a local paper instead of blocking vocabulary or learning-card finalization.

The first retrieval strategy is the plan in the confirmed profile. If more
searching is needed, the controller assigns the next strategy to the current
host agent (the user was told before this unattended phase that they may leave
the task and may not see another question). The agent writes
`retrieval-strategy-02.json` or `retrieval-strategy-03.json` from the preserved
outcomes and resumes. Never invent a fourth strategy. A terminal
`corpus_unavailable` status means no usable PDF was obtained and ends the
current run; it is not a successful initialization.

Each OpenAlex search query may optionally set `candidate_limit` to exactly 50,
100, 150, or 200. This is a per-query retained-candidate quota, not a fixed
global search limit. Use 100 by default; choose 50 for lower-value query angles
or 150/200 for strong, high-value query angles. The acquisition client uses cursor paging to
reach the selected quota and records the fetched, retained, and total counts.

The controller's `status.json` is authoritative. While `terminal` is `false`,
the current task must continue:

- wait on the same live command when it is still running;
- perform any `next_action` whose actor is `current_host_agent`, write the exact
  requested output, and immediately run the supplied `resume` command;
- diagnose a real failure from preserved artifacts and resume the same
  operation.

For a vocabulary-card review action, the review records are always in the
input file's top-level `.candidates` array; `vocabulary_card_review_batch` is
only the controller's label for that input path, not a JSON field. Check
`.candidate_count == (.candidates | length)` before reviewing. Work through a
large review only through the bounded batch supplied on each controller resume.
Write decisions for that batch only; never read, copy, or merge earlier batch
outputs because the controller validates and combines them deterministically.
Make a corpus-grounded sense decision for each item. Never generate the review
by taking the first dictionary meaning
or by filling fields merely to make finalization continue. For each candidate,
either write a contextual gloss with a stable sense key and a brief rationale,
or put an uncertain or noisy lemma in `vocabulary_card_drops`. A
unique `acronym_expansion` controls the exact English meaning and suggested
`sense_key`; it overrides a conflicting dictionary abbreviation. If exhaustive
semantic review is not complete, do not write a nominally complete selection
and do not resume finalization.

An internal command exit, a candidate count, downloaded PDFs, completed corpus
analysis, a vocabulary file, or a terminology count is never a reason to stop.
The controller must finish the standalone exhaustive orthography review before
preparing any vocabulary-card gloss candidates. It then runs
`finalize_domain_assets.py`, which loads the already finalized vocabulary and
finalizes its cards together with terminology. `ready_for_calibration` is a
pipeline-readiness signal, not an independent claim that arbitrary prose is
correct; it is valid only after the vocabulary-card semantic review contract
and the asset loaders both succeed. It may start calibration only after that
invocation succeeds.
The preparation operation may hand control to the user only when the controller
returns `terminal: true`, `checkpoint: calibration_ready`, and a live URL whose
record says both `vocabulary_ready` and
`terminology_ready`. Open that exact URL and ask the user to answer the 30
calibration questions. Do not claim that full initialization is complete until
those answers and the personalized export have been verified.

Start by checking the Skill-local runtime. If dependencies are missing,
proactively request the required network and disk-write permission, as listed
under Host permissions to request once; after approval, run the platform
installer yourself and verify it before continuing.
Configure Python dependencies as part of setup rather than handing that work to
the user. Do not read the
long workflow reference for an ordinary workbench-opening request.

## Research briefs and reminders

Keep these four requests distinct:

For both immediate brief generation and weekly brief scheduling, resolve the
domain before doing any work:

- If the user named a registered domain, use it.
- If the user did not name a domain and exactly one initialized domain is
  registered, use it directly (there is no ambiguous domain choice to resolve).
- If several domains are registered and the user did not name one, ask the user
  to choose from the registered domains. Do not start generation, save schedule
  settings, or create a task before the choice is made.
- If the named domain is not registered, show the registered choices and ask
  again. Never fall back to the active domain, an open workbench tab, or another
  Skill instance's registry.

Once a weekly task is created, bind it to the resolved domain ID and workspace;
scheduled runs reuse that already confirmed choice.

- **View briefs**: use the ordinary workbench fast path with `--view briefs`.
  Opening the page never starts research or creates a schedule. If no brief
  exists, tell the user that none has been generated and that Codex / Work Buddy
  can generate one.
- **Generate a brief**: read
  [continuous-workflow.md](references/continuous-workflow.md), then run the
  single controller below after applying the domain rule above.

  ```bash
  .venv/bin/python scripts/generate_brief.py run [--domain <domain-id>]
  ```

  While its `terminal` value is `false`, perform the supplied host-agent
  `next_action` and immediately run its exact `resume` command. Discovery,
  selection, download, preparation, and draft writing are never completion
  points. When it returns `terminal: true` with `generated: true`, open the
  workbench at `--view briefs`. When it returns `generated: false`, report that
  no brief was saved and give the controller's reason.
- **Schedule a weekly brief**: read only the scheduling section of the same
  reference. Resolve the domain using the same rule, obtain the weekday and
  time, run `configure_schedule.py weekly`, then create or update exactly the
  one host scheduled task emitted in its handoff. The task runs the same
  brief-generation controller. Do not generate a brief immediately unless the
  user also asked for one.
- **Schedule a daily review reminder**: obtain the time, run
  `configure_schedule.py daily`, then create or update exactly the one reminder
  task emitted in its handoff. It only checks due words and terms. It never
  generates a brief or changes the weekly task.

Never treat a research brief as necessarily weekly. Repeated scheduling updates
the task with the same `automation_key`; it must not create duplicates. Do not
read the continuous workflow for ordinary viewing or review.

PDFs, extracted text, source metadata, corpora, briefs, settings, and learning
records remain in the user-confirmed local AreaDay directories. The 30-question
vocabulary calibration runs entirely inside the Skill: only the compact word
statistics defined in `references/vocabulary-calibration.md` are assembled, they
are used in this same process, and nothing is sent anywhere. The final result is
saved locally and can be viewed later.
