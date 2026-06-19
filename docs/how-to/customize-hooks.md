# Customise Hook Behaviour

The three hooks are registered automatically by `claude-wiki init`. You can adjust their behaviour via the global `settings.json` or by extending the handler modules.

---

## Hook Events

| Event | Trigger | Default Timeout |
|-------|---------|-----------------|
| `SessionStart` | New Claude Code session begins | 15s |
| `SessionEnd` | Session ends or user exits | 10s |
| `PreCompact` | Before auto-compaction | 10s |

## Adjust Timeouts

Edit `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uvx claude-wiki claude-wiki-hook SessionStart",
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

Handlers are auto-discovered at runtime by `hooks.py`.
