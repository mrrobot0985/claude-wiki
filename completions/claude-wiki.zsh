#compdef claude-wiki

_claude_wiki_commands() {
    local commands=(compile init lint migrate query register registry rename-catalog status)
    _describe -t commands 'claude-wiki command' commands
}

_claude_wiki() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    _arguments -C \
        '(-)--version[Show version and exit]' \
        '1:command:_claude_wiki_commands' \
        '*::arg:->args'

    case $line[1] in
        (compile)
            _arguments -C \
                '--all[]' \
                '--dry-run[]' \
                '--file[]' \
                '--help[]' \
                '--path[]' \
                '*:: :_files'
            ;;
        (init)
            _arguments -C \
                '--daily-dir[]' \
                '--force[]' \
                '--global[]' \
                '--help[]' \
                '--kb-dir[]' \
                '--no-hooks[]' \
                '--path[]' \
                '*:: :_files'
            ;;
        (lint)
            _arguments -C \
                '--fail-on-warning[]' \
                '--help[]' \
                '--json[]' \
                '--path[]' \
                '--structural-only[]' \
                '*:: :_files'
            ;;
        (migrate)
            _arguments -C \
                '--daily-dir[]' \
                '--dry-run[]' \
                '--help[]' \
                '--kb-dir[]' \
                '--path[]' \
                '--reports-dir[]' \
                '*:: :_files'
            ;;
        (query)
            _arguments -C \
                '--file-back[]' \
                '--help[]' \
                '--json[]' \
                '--path[]' \
                '*:: :_files'
            ;;
        (register)
            _arguments -C \
                '--help[]' \
                '--path[]' \
                '*:: :_files'
            ;;
        (registry)
            case $line[2] in
                (clean)
                    _arguments -C \
                        '--help[]' \
                        '*:: :_files'
                    ;;
                (list)
                    _arguments -C \
                        '--help[]' \
                        '*:: :_files'
                    ;;
                (remove)
                    _arguments -C \
                        '--help[]' \
                        '--yes[]' \
                        '*:: :_files'
                    ;;
                (show)
                    _arguments -C \
                        '--help[]' \
                        '*:: :_files'
                    ;;
            esac
            ;;
        (rename-catalog)
            _arguments -C \
                '--dry-run[]' \
                '--help[]' \
                '--path[]' \
                '*:: :_files'
            ;;
        (status)
            _arguments -C \
                '--help[]' \
                '--path[]' \
                '*:: :_files'
            ;;
    esac
}

_claude_wiki "$@"

