#!/bin/sh
# Deliberately do not fall back to Apple Terminal: it corrupts this RGB artwork.
set -eu
resources_path=${1:?Missing app resources directory}
wezterm_bin=""
for candidate in "/Applications/WezTerm.app/Contents/MacOS/wezterm" \
    "$HOME/Applications/WezTerm.app/Contents/MacOS/wezterm" \
    "/opt/homebrew/bin/wezterm" "/usr/local/bin/wezterm"; do
    if [ -x "$candidate" ]; then
        wezterm_bin=$candidate
        break
    fi
done
if [ -z "$wezterm_bin" ]; then
    wezterm_bin=$(command -v wezterm || true)
fi
if [ -z "$wezterm_bin" ]; then
    echo "Humming Bird needs WezTerm for correct RGB colors and held-key controls. Install WezTerm (brew install --cask wezterm), then reopen this app. Your artwork and settings are unchanged." >&2
    exit 1
fi
game_bin="$resources_path/humming-bird/humming-bird"
config_file="$resources_path/humming-bird-wezterm.lua"
if [ ! -x "$game_bin" ] || [ ! -f "$config_file" ]; then
    echo "The Humming Bird app is incomplete. Reinstall the app; your preferences are stored separately." >&2
    exit 1
fi
log_dir="$HOME/Library/Logs/Humming Bird"
mkdir -p "$log_dir"
nohup "$wezterm_bin" --config-file "$config_file" start --always-new-process \
    --cwd "$HOME" -- "$game_bin" >> "$log_dir/terminal.log" 2>&1 < /dev/null &
terminal_pid=$!
sleep 0.5
if ! kill -0 "$terminal_pid" 2>/dev/null; then
    echo "WezTerm could not start. See $log_dir/terminal.log for details." >&2
    exit 1
fi
