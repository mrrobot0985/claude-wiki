# Install Shell Completions and the Man Page

Enable tab completion for `claude-wiki` and view its manual page.

______________________________________________________________________

## Where the Files Ship

Completion scripts and the man page are bundled inside the wheel under the
`claude_wiki/data/` package directory:

| File            | Wheel path                                      |
| --------------- | ----------------------------------------------- |
| Bash completion | `claude_wiki/data/completions/claude-wiki.bash` |
| Zsh completion  | `claude_wiki/data/completions/claude-wiki.zsh`  |
| Fish completion | `claude_wiki/data/completions/claude-wiki.fish` |
| Man page        | `claude_wiki/data/man/claude-wiki.1`            |

Locate the installed copy on your machine:

```bash
CW_DATA=$(uv run python -c "import claude_wiki, pathlib; print(pathlib.Path(claude_wiki.__file__).parent / 'data')")
echo "$CW_DATA"
```

If you are not inside a uv project, use `python` instead of `uv run python`.

## Bash

Copy the completion file to the system completion directory:

```bash
sudo cp "$CW_DATA/completions/claude-wiki.bash" /etc/bash_completion.d/claude-wiki
```

On macOS with Homebrew, use the Homebrew-managed path:

```bash
cp "$CW_DATA/completions/claude-wiki.bash" "$(brew --prefix)/etc/bash_completion.d/claude-wiki"
```

Start a new shell or run `exec bash` to load the completions.

## Zsh

Copy the completion into a directory on your `$fpath`, then refresh the
completion cache:

```bash
mkdir -p ~/.config/zsh/completions
cp "$CW_DATA/completions/claude-wiki.zsh" ~/.config/zsh/completions/_claude-wiki
chmod 644 ~/.config/zsh/completions/_claude-wiki
```

Add the directory to `$fpath` in `~/.zshrc` if it is not already there:

```bash
fpath+=("$HOME/.config/zsh/completions")
autoload -U compinit && compinit
```

## Fish

Copy the completion file to Fish's completion directory:

```bash
mkdir -p ~/.config/fish/completions
cp "$CW_DATA/completions/claude-wiki.fish" ~/.config/fish/completions/claude-wiki.fish
```

Run `exec fish` or open a new terminal. Test with `claude-wiki <Tab>`.

## Man Page

Install the man page system-wide and refresh the index:

```bash
sudo mkdir -p /usr/local/share/man/man1
sudo cp "$CW_DATA/man/claude-wiki.1" /usr/local/share/man/man1/
sudo mandb   # Linux
# On macOS, the man page is picked up automatically on the next man-db refresh.
```

Then view it:

```bash
man claude-wiki
```

## Updating After an Upgrade

Completion scripts and the man page may change when new commands or flags are
added. Repeat the copy steps for your shell after upgrading the package.
