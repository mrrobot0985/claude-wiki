# Examples

Self-contained demonstrations of `claude-wiki` output.

## minimal-walkthrough

A synthetic daily log and its compiled knowledge base.

```bash
cd examples/minimal-walkthrough
claude-wiki lint --structural-only --path .
```

You can inspect the compiled articles in `knowledge/` without running `compile`
(which requires a Claude Code API call). The `daily/` log is fully synthetic and
contains no real conversation data.
