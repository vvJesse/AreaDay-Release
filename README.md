# AreaDay

[English](README.md) | [简体中文](README.zh-CN.md)

AreaDay is distributed as a self-contained Skill for Codex and WorkBuddy.
It runs completely offline and needs no license, activation code, or account.

#### Note for WorkBuddy Users

This Skill has been tested end-to-end on **WorkBuddy** using
**DeepSeek-V4-Flash**. Other compatible models may also work.

WorkBuddy's sandbox restricts certain system-level operations required by the
complete workflow. For example, `schtasks` may be blocked, preventing scheduled
tasks from completing.

We have not yet found a sufficiently reliable and user-friendly solution that
preserves all sandbox restrictions. For affected steps, **temporarily disabling
the WorkBuddy sandbox is currently the most reliable workaround**.

Disabling the sandbox reduces WorkBuddy's security isolation and may allow the
agent to access files and system resources available to your account. Only
proceed when you trust the Skill and task, avoid running WorkBuddy as
administrator, and **re-enable the sandbox when finished**.

If you are uncomfortable disabling the sandbox temporarily, please consider
this limitation **before purchasing**. We cannot currently guarantee
the complete workflow while the sandbox remains enabled.

## Install

First download the complete delivery ZIP for the current computer from the
[latest release](https://github.com/vvJesse/AreaDay-Release/releases/latest).
In a new Codex or WorkBuddy task, send the release repository URL, the request
`帮我安装这个 Skill。`, and the ZIP's full local path, then send it. No activation
key or credential file is needed.

See the Chinese [AreaDay installation and usage guide](docs/customer-guide/AreaDay-安装和使用指南.md)
for direct download links and the complete first-use flow. The agent must read
[INSTALL.md](INSTALL.md) and complete installation and verification.
The user does not need to extract the ZIP, move folders, run terminal commands,
or install dependencies.

Supported release platforms:

- 64-bit Windows on Intel or AMD
- Apple silicon Mac (M1 or newer)

Intel Macs are not currently supported.

## Learning without a brief

After the 30-question calibration, **今日复习** can offer a small set of
priority domain words even when no research brief has been generated. Their
Chinese meanings, optional English meanings, and an original-paper context are
prepared during domain setup, before the calibration page opens. Choosing
“需要学习” adds a word to the local review schedule; choosing “已经会了” keeps it
out. A later brief may add a new paper context for the same word, but cannot
replace its established meaning.

## Safety & Privacy

- Papers, PDFs, extracted text, notes, profiles, and vocabulary data are stored
  on the user's computer. AreaDay does not upload the original paper text or
  local file paths anywhere. Text tokenization, embedding inference, and the
  30-question vocabulary calibration all run locally inside the Skill, with
  ONNX Runtime telemetry explicitly disabled.
- To find papers, AreaDay sends search requests and related metadata to the
  enabled providers (OpenAlex and, when selected, arXiv). Those providers'
  terms and privacy policies apply to those requests.
- AreaDay has no server of its own. It does not need a license, an activation
  key, a device identifier, or an account, and it does not enforce a device
  limit.
- OpenAlex API keys are credentials.
  Keep them private and do not commit or paste them into public issues,
  prompts, or repositories. AreaDay does not need access to your other files.
- AreaDay is a research and vocabulary aid. Review generated results before
  relying on them in research or other professional work.
