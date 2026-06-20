# fish completion for claude-wiki

# Global options
complete -c claude-wiki -l version -d 'Show version and exit'

# Top-level commands
complete -c claude-wiki -n '__fish_use_subcommand' -a "compile init lint migrate query register registry rename-catalog status tags"

# compile flags
complete -c claude-wiki -n '__fish_seen_subcommand_from compile' -l all
complete -c claude-wiki -n '__fish_seen_subcommand_from compile' -l dry-run
complete -c claude-wiki -n '__fish_seen_subcommand_from compile' -l file
complete -c claude-wiki -n '__fish_seen_subcommand_from compile' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from compile' -l path
# init flags
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l daily-dir
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l force
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l global
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l kb-dir
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l no-hooks
complete -c claude-wiki -n '__fish_seen_subcommand_from init' -l path
# lint flags
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l dry-run
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l fail-on-warning
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l fix
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l json
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l path
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l structural-only
complete -c claude-wiki -n '__fish_seen_subcommand_from lint' -l threshold
# migrate flags
complete -c claude-wiki -n '__fish_seen_subcommand_from migrate' -l daily-dir
complete -c claude-wiki -n '__fish_seen_subcommand_from migrate' -l dry-run
complete -c claude-wiki -n '__fish_seen_subcommand_from migrate' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from migrate' -l kb-dir
complete -c claude-wiki -n '__fish_seen_subcommand_from migrate' -l path
complete -c claude-wiki -n '__fish_seen_subcommand_from migrate' -l reports-dir
# query flags
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l category
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l file-back
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l json
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l max-chars
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l path
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l since
complete -c claude-wiki -n '__fish_seen_subcommand_from query' -l tag
# register flags
complete -c claude-wiki -n '__fish_seen_subcommand_from register' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from register' -l path
# registry subcommands
complete -c claude-wiki -n '__fish_seen_subcommand_from registry' -a clean
complete -c claude-wiki -n '__fish_seen_subcommand_from registry' -a list
complete -c claude-wiki -n '__fish_seen_subcommand_from registry' -a remove
complete -c claude-wiki -n '__fish_seen_subcommand_from registry' -a show
# registry flags
complete -c claude-wiki -n '__fish_seen_subcommand_from registry' -l help
# rename-catalog flags
complete -c claude-wiki -n '__fish_seen_subcommand_from rename-catalog' -l dry-run
complete -c claude-wiki -n '__fish_seen_subcommand_from rename-catalog' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from rename-catalog' -l path
# status flags
complete -c claude-wiki -n '__fish_seen_subcommand_from status' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from status' -l path
# tags flags
complete -c claude-wiki -n '__fish_seen_subcommand_from tags' -l help
complete -c claude-wiki -n '__fish_seen_subcommand_from tags' -l json
complete -c claude-wiki -n '__fish_seen_subcommand_from tags' -l path

