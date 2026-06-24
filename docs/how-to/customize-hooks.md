# Customise Hook Behaviour

The three hooks are registered automatically by `claude-wiki init` into the repo-local `.claude/settings.local.json`. You can adjust their behaviour via that file, or via `~/.claude/settings.json` if you used `init --global`.

______________________________________________________________________

## Hook Events

| Event          | Trigger                        | Default Timeout |
| -------------- | ------------------------------ | --------------- |
| `SessionStart` | New Claude Code session begins | 15s             |
| `SessionEnd`   | Session ends or user exits     | 10s             |
| `PreCompact`   | Before auto-compaction         | 10s             |

## Adjust Timeouts

Edit `.claude/settings.local.json` (or `~/.claude/settings.json` if you used `init --global`):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uvx --from claude-wiki claude-wiki-hook SessionStart",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

## Writing Custom Handlers

Create a module under `src/claude_wiki/hook_handlers/` that exports a `register` function:

```python
def register(handlers: dict[str, Any]) -> None:
    handlers["MyEvent"] = my_handler
```

Handlers are loaded from the explicit `_HANDLER_MODULES` list in `hook_handlers/__init__.py`; add your module name to that list after creating the file.
