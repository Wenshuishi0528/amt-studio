# Codex working method

## Starting the project

Open the repository root in the Codex app. Codex will read the root `AGENTS.md` before it works. Paste `CODEX_BOOTSTRAP_PROMPT.txt` as the first task.

## One task per conversation

Use one Codex conversation for one numbered task. A conversation should end with:

- a small, reviewable diff;
- tests and exact evidence;
- the task file updated;
- a Git commit only after you review the result;
- the next task prompt.

Do not give Codex a broad request such as “build the whole app.” The numbered task files already contain the larger plan.

## Preventing loops

When Codex repeats an approach without new evidence, use this intervention:

```text
Stop repeating the current approach. Summarize the observed facts, the exact failing command, and the last three materially different hypotheses tested. Read AGENTS.md and the active task's acceptance criteria again. Propose at most three new hypotheses ranked by likelihood and test the cheapest discriminating one. Do not reinstall everything or change architecture without evidence.
```

When Codex expands scope, use:

```text
Return to the active numbered task. Put later ideas in docs/BACKLOG.md. Revert unrelated changes and satisfy only the active acceptance criteria.
```

When Codex claims success too early, use:

```text
Show the exact command output that proves each acceptance criterion. Mark anything not executed as unverified. Do not infer Mac or Hyak behavior from a different machine.
```

## Branching and parallelism

Keep Tasks 001–002 sequential because they define the project and worker contract. After the canonical worker interface is stable, independent workers may be developed in separate branches or Codex worktrees, for example source separation and beat tracking. Merge only after each branch passes the same schemas and manifests.

Avoid parallel edits to `src/amt_core`, schemas, or architecture documents unless one branch clearly owns the contract change.

## Review before accepting a Codex change

Check:

1. private audio and weights are still ignored;
2. no global `pip install` or login-node compute was introduced;
3. raw model output remains preserved;
4. model versions and weights are pinned or explicitly unverified;
5. tests actually ran;
6. later tasks were not silently implemented;
7. measured results are separated from assumptions.
