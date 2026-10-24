# notes: find a note in julz-mem by name or by what it says, preview it, open it in nvim.
#   notes           every note, type to filter by path
#   notes dhcp      notes whose folder, name or text mentions dhcp
#   notes inbox     so this lists everything in Inbox/
#   notes -l        what changed lately (git log of the vault)
# Install: cp tools/notes.fish ~/.config/fish/functions/
function notes --description 'Find, preview and open a note in julz-mem'
    set -l vault ~/Documents/julz-mem
    if test "$argv[1]" = -l
        git -C $vault log --format='%h %ad %s' --date=short -20
        return
    end
    set -l list
    set list (rg --files --glob '*.md' $vault)
    if test (count $argv) -gt 0
        # A word matches the path (folder or file name) or the text. -F: plain text, not a
        # regex. -l: file names only
        set -l by_path (string match -i -e -- "$argv" $list)
        set -l by_text (rg -l -i -F --glob '*.md' -- "$argv" $vault)
        set list (printf '%s\n' $by_path $by_text | sort -u)
    end
    test (count $list) -eq 0; and echo "no note mentions $argv"; and return 1
    set -l pick (printf '%s\n' $list | string replace "$vault/" '' | sort \
        | fzf --preview "bat --color=always --style=plain $vault/{}" --preview-window=right:60%)
    test -n "$pick"; and nvim $vault/$pick
end
