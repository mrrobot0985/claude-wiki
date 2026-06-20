"""Shell completion script generator for claude-wiki.

This module introspects the live argparse parser produced by ``cli.py`` and
emits bash, zsh, and fish completion scripts.  It is imported by both the
standalone generator script (``scripts/generate_completions.py``) and the
completion drift-guard tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

COMPLETION_NAMES = ("claude-wiki.bash", "claude-wiki.zsh", "claude-wiki.fish")


def get_parser() -> argparse.ArgumentParser:
    """Return the live CLI parser, including all auto-discovered commands."""
    from claude_wiki.cli import _build_parser

    parser, _handlers = _build_parser()
    return parser


def _top_commands(parser: argparse.ArgumentParser) -> list[str]:
    """Return the list of top-level subcommand names."""
    subparsers_action = _subparsers_action(parser)
    if subparsers_action is None:
        return []
    return sorted(subparsers_action.choices.keys())


def _subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[argparse.ArgumentParser] | None:
    """Locate the ``_SubParsersAction`` on a parser."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _option_flags(parser: argparse.ArgumentParser) -> list[str]:
    """Return all ``--`` long options declared on a parser, excluding --version."""
    flags: list[str] = []
    for action in parser._actions:
        for opt in action.option_strings:
            if opt.startswith("--") and opt != "--version":
                flags.append(opt)
    return sorted(set(flags))


def _command_flags(parser: argparse.ArgumentParser, command: str) -> list[str]:
    """Return option flags for a specific top-level subcommand."""
    subparsers_action = _subparsers_action(parser)
    if subparsers_action is None or command not in subparsers_action.choices:
        return []
    return _option_flags(subparsers_action.choices[command])


def _nested_commands(parser: argparse.ArgumentParser, command: str) -> list[str] | None:
    """Return nested subcommands if the given command has its own subparsers."""
    subparsers_action = _subparsers_action(parser)
    if subparsers_action is None or command not in subparsers_action.choices:
        return None
    subparser = subparsers_action.choices[command]
    nested = _subparsers_action(subparser)
    if nested is None:
        return None
    return sorted(nested.choices.keys())


def _nested_command_flags(
    parser: argparse.ArgumentParser, command: str, subcommand: str
) -> list[str]:
    """Return option flags for a nested subcommand."""
    subparsers_action = _subparsers_action(parser)
    if subparsers_action is None or command not in subparsers_action.choices:
        return []
    subparser = subparsers_action.choices[command]
    nested_action = _subparsers_action(subparser)
    if nested_action is None or subcommand not in nested_action.choices:
        return []
    return _option_flags(nested_action.choices[subcommand])


def _bash_var(name: str) -> str:
    """Return a bash-safe variable name from a command name."""
    return name.replace("-", "_")


def generate_bash(parser: argparse.ArgumentParser) -> str:
    """Emit a bash completion script."""
    commands = _top_commands(parser)
    lines: list[str] = [
        "# bash completion for claude-wiki",
        "",
        "_claude_wiki_completion() {",
        "    local cur prev opts cmds",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"',
        f"    cmds=({' '.join(commands)})",
        "",
        "    if [ $COMP_CWORD -eq 1 ]; then",
        '        COMPREPLY=( $(compgen -W "${cmds[*]}" -- "$cur") )',
        "        return 0",
        "    fi",
        "",
        '    local cmd="${COMP_WORDS[1]}"',
    ]

    for command in commands:
        flags = _command_flags(parser, command)
        nested = _nested_commands(parser, command)
        var_prefix = _bash_var(command)
        if nested:
            lines.append(f'    if [ "$cmd" = "{command}" ]; then')
            lines.append("        if [ $COMP_CWORD -eq 2 ]; then")
            lines.append(
                f'            COMPREPLY=( $(compgen -W "{" ".join(nested)}" -- "$cur") )'
            )
            lines.append("            return 0")
            lines.append("        fi")
            lines.append('        local subcmd="${COMP_WORDS[2]}"')
            lines.append('        case "$subcmd" in')
            for sub in nested:
                sub_flags = _nested_command_flags(parser, command, sub)
                all_flags = sorted(set(flags + sub_flags))
                lines.append(f"            {sub})")
                lines.append(
                    f"                local {var_prefix}_{_bash_var(sub)}_opts=({' '.join(all_flags)})"
                )
                lines.append(
                    f'                COMPREPLY=( $(compgen -W "${{{var_prefix}_{_bash_var(sub)}_opts[*]}}" -- "$cur") )'
                )
                lines.append("                ;;")
            lines.append("        esac")
            lines.append("        return 0")
            lines.append("    fi")
        elif flags:
            lines.append(f'    if [ "$cmd" = "{command}" ]; then')
            lines.append(f"        local {var_prefix}_opts=({' '.join(flags)})")
            lines.append(
                f'        COMPREPLY=( $(compgen -W "${{{var_prefix}_opts[*]}}" -- "$cur") )'
            )
            lines.append("        return 0")
            lines.append("    fi")

    lines.extend(
        [
            "",
            "    COMPREPLY=()",
            "    return 0",
            "}",
            "",
            "complete -F _claude_wiki_completion claude-wiki",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_zsh(parser: argparse.ArgumentParser) -> str:
    """Emit a zsh completion script."""
    commands = _top_commands(parser)
    lines: list[str] = [
        "#compdef claude-wiki",
        "",
        "_claude_wiki_commands() {",
        f"    local commands=({' '.join(commands)})",
        "    _describe -t commands 'claude-wiki command' commands",
        "}",
        "",
        "_claude_wiki() {",
        '    local curcontext="$curcontext" state line',
        "    typeset -A opt_args",
        "",
        "    _arguments -C \\",
        "        '(-)--version[Show version and exit]' \\",
        "        '1:command:_claude_wiki_commands' \\",
        "        '*::arg:->args'",
        "",
        "    case $line[1] in",
    ]

    for command in commands:
        flags = _command_flags(parser, command)
        nested = _nested_commands(parser, command)
        if nested:
            lines.append(f"        ({command})")
            lines.append("            case $line[2] in")
            for sub in nested:
                sub_flags = _nested_command_flags(parser, command, sub)
                all_flags = sorted(set(flags + sub_flags))
                lines.append(f"                ({sub})")
                lines.append("                    _arguments -C \\")
                for flag in all_flags:
                    lines.append(f"                        '{flag}[]' \\")
                lines.append("                        '*:: :_files'")
                lines.append("                    ;;")
            lines.append("            esac")
            lines.append("            ;;")
        elif flags:
            lines.append(f"        ({command})")
            lines.append("            _arguments -C \\")
            for flag in flags:
                lines.append(f"                '{flag}[]' \\")
            lines.append("                '*:: :_files'")
            lines.append("            ;;")
        else:
            lines.append(f"        ({command})")
            lines.append("            _files")
            lines.append("            ;;")

    lines.extend(
        [
            "    esac",
            "}",
            "",
            '_claude_wiki "$@"',
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_fish(parser: argparse.ArgumentParser) -> str:
    """Emit a fish completion script."""
    commands = _top_commands(parser)
    lines: list[str] = [
        "# fish completion for claude-wiki",
        "",
        "# Global options",
        "complete -c claude-wiki -l version -d 'Show version and exit'",
        "",
        "# Top-level commands",
        f"complete -c claude-wiki -n '__fish_use_subcommand' -a \"{' '.join(commands)}\"",
        "",
    ]

    for command in commands:
        flags = _command_flags(parser, command)
        nested = _nested_commands(parser, command)
        if nested:
            lines.append(f"# {command} subcommands")
            for sub in nested:
                lines.append(
                    f"complete -c claude-wiki -n '__fish_seen_subcommand_from {command}' "
                    f"-a {sub}"
                )
            lines.append(f"# {command} flags")
            for flag in flags:
                lines.append(
                    f"complete -c claude-wiki -n '__fish_seen_subcommand_from {command}' "
                    f"-l {flag.lstrip('-')}"
                )
        elif flags:
            lines.append(f"# {command} flags")
            for flag in flags:
                lines.append(
                    f"complete -c claude-wiki -n '__fish_seen_subcommand_from {command}' "
                    f"-l {flag.lstrip('-')}"
                )

    lines.append("")
    return "\n".join(lines) + "\n"


def generate_all(output_dir: Path) -> None:
    """Write all three completion scripts into ``output_dir``.

    The directory is created if it does not already exist.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    parser = get_parser()
    writers = {
        "claude-wiki.bash": generate_bash,
        "claude-wiki.zsh": generate_zsh,
        "claude-wiki.fish": generate_fish,
    }
    for name, writer in writers.items():
        (output_dir / name).write_text(writer(parser), encoding="utf-8")
