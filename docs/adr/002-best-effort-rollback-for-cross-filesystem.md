# ADR-002: Best-Effort Rollback for Cross-Filesystem Moves

## Status

Partial

> Implementation uses `shutil.move` for all directory moves. The pre-flight `st_dev` check, same-filesystem `os.rename` optimisation, and cross-filesystem warning described below are not yet implemented. Rollback currently reverses every completed move unconditionally, including cross-filesystem moves.

## Context

`shutil.move` falls back to `copytree` + `rmtree` when source and destination are on different filesystems. A full copy is expensive, non-atomic, and consumes double disk space. If such a move succeeds and a subsequent move fails, rolling back via another copy may also fail (disk full, quota exceeded).

## Decision

Migration performs a **pre-flight device check**: `os.stat(src).st_dev == os.stat(dst.parent).st_dev`.

- **Same filesystem** (`st_dev` matches): use `os.rename`, which is atomic and reversible. Full rollback is guaranteed.
- **Different filesystem** (`st_dev` differs): proceed with `shutil.move` but log a clear warning:\
  `"Cross-filesystem move detected; rollback is best-effort only."`
  No automatic rollback is attempted. The CLI exits with a specific error code and a message telling the user which paths are split.

## Consequences

- **Positive:** Same-filesystem migrations remain safe and reversible.
- **Positive:** Users are not blocked from moving between `$HOME` and project disks.
- **Negative:** Cross-filesystem partial failures leave data split; manual recovery is required.
- **Negative:** Test suite needs to simulate cross-filesystem behavior (tmpfs mounts or mock `st_dev`).

## Alternatives Rejected

- **Ban cross-filesystem** — blocks the common case of migrating from `project` mode (repo disk) to `user` mode (`$HOME` disk).
- **Always attempt rollback** — a cross-filesystem rollback can fail due to disk space, producing confusing split-state errors.
