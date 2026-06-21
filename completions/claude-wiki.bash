# bash completion for claude-wiki

_claude_wiki_completion() {
    local cur prev opts cmds
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmds=(compile graph init lint migrate query register registry rename-catalog status tags)

    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=( $(compgen -W "${cmds[*]}" -- "$cur") )
        return 0
    fi

    local cmd="${COMP_WORDS[1]}"
    if [ "$cmd" = "compile" ]; then
        local compile_opts=(--all --continue-on-error --dry-run --file --help --limit --max-logs --path)
        COMPREPLY=( $(compgen -W "${compile_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "graph" ]; then
        local graph_opts=(--help --json --path --top)
        COMPREPLY=( $(compgen -W "${graph_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "init" ]; then
        local init_opts=(--daily-dir --force --global --help --kb-dir --no-hooks --path)
        COMPREPLY=( $(compgen -W "${init_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "lint" ]; then
        local lint_opts=(--dry-run --fail-on-warning --fix --help --json --path --structural-only --threshold)
        COMPREPLY=( $(compgen -W "${lint_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "migrate" ]; then
        local migrate_opts=(--daily-dir --dry-run --help --kb-dir --path --reports-dir)
        COMPREPLY=( $(compgen -W "${migrate_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "query" ]; then
        local query_opts=(--category --file-back --help --json --max-chars --path --since --tag)
        COMPREPLY=( $(compgen -W "${query_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "register" ]; then
        local register_opts=(--help --path)
        COMPREPLY=( $(compgen -W "${register_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "registry" ]; then
        if [ $COMP_CWORD -eq 2 ]; then
            COMPREPLY=( $(compgen -W "clean list remove show" -- "$cur") )
            return 0
        fi
        local subcmd="${COMP_WORDS[2]}"
        case "$subcmd" in
            clean)
                local registry_clean_opts=(--help)
                COMPREPLY=( $(compgen -W "${registry_clean_opts[*]}" -- "$cur") )
                ;;
            list)
                local registry_list_opts=(--help)
                COMPREPLY=( $(compgen -W "${registry_list_opts[*]}" -- "$cur") )
                ;;
            remove)
                local registry_remove_opts=(--help --yes)
                COMPREPLY=( $(compgen -W "${registry_remove_opts[*]}" -- "$cur") )
                ;;
            show)
                local registry_show_opts=(--help)
                COMPREPLY=( $(compgen -W "${registry_show_opts[*]}" -- "$cur") )
                ;;
        esac
        return 0
    fi
    if [ "$cmd" = "rename-catalog" ]; then
        local rename_catalog_opts=(--dry-run --help --path)
        COMPREPLY=( $(compgen -W "${rename_catalog_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "status" ]; then
        local status_opts=(--help --json --path)
        COMPREPLY=( $(compgen -W "${status_opts[*]}" -- "$cur") )
        return 0
    fi
    if [ "$cmd" = "tags" ]; then
        local tags_opts=(--help --json --path)
        COMPREPLY=( $(compgen -W "${tags_opts[*]}" -- "$cur") )
        return 0
    fi

    COMPREPLY=()
    return 0
}

complete -F _claude_wiki_completion claude-wiki

