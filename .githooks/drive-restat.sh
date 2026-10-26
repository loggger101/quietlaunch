#!/bin/sh
#
# Repair git's stat cache after Google Drive lies about file size.
#
# THE BUG
# Diagnosed in economicspace, whose tree has lived in synced folders: first a
# Google Drive File Stream mount (G:), then OneDrive.  When git
# writes a file during checkout / merge / pull and immediately stats it, Drive
# returns a placeholder size of 16384 bytes rather than the real size.  Git
# caches that bogus number in the index:
#
#     $ git ls-files --debug master.py
#         size: 16384          <- what Drive told git at write time
#     $ ls -l master.py
#         328335               <- the truth, moments later
#
# Every later `git status` compares the two, sees a size mismatch, and reports
# the file as modified.  Git never re-reads the content, because differing
# size is normally conclusive proof of a change, a sound inference from a
# false premise.  So the tree looks permanently dirty while `git diff` shows
# nothing, and `git update-index --refresh` refuses to help for the same
# reason.  The knock-on effect is worse than the cosmetics: `git merge
# --ff-only` and `git checkout` abort with "your local changes would be
# overwritten", so a merged PR silently fails to land locally.
#
# THE REPAIR
# Re-stat the affected entries once Drive has settled.  A file is touched only
# when its content hash ALREADY matches what the index records, so this cannot
# stage, hide, or discard a real modification, verified by test.  Anything
# genuinely changed is left exactly as it was.
#
# Shipped by samebytes; `python -m samebytes hooks install <repo>` copies it
# and the three post-* hooks into <repo>/.githooks and sets core.hooksPath,
# and `hooks check` says when a copy has drifted.  The repo's .gitattributes
# must pin `.githooks/* text eol=lf`.  Safe to run by hand at any
# time:  sh .githooks/drive-restat.sh

# One path per LINE, never `for f in $(...)`: word splitting cut
# `_START HERE.vbs` into two names that both failed `-f`, so the one tracked
# path with a space in it could never be repaired.  The here-document (not a
# pipe) keeps the loop in this shell, so the count survives it; quotePath off
# hands non-ASCII names over as-is rather than octal-escaped.
restated=0
modified=$(git -c core.quotePath=false ls-files -m)
while IFS= read -r f; do
    [ -n "$f" ] && [ -f "$f" ] || continue
    worktree=$(git hash-object -- "$f" 2>/dev/null) || continue
    indexed=$(git rev-parse ":$f" 2>/dev/null)      || continue
    if [ "$worktree" = "$indexed" ]; then
        git update-index -- "$f" 2>/dev/null && restated=$((restated + 1))
    fi
done <<EOF
$modified
EOF

if [ "$restated" -gt 0 ]; then
    echo "drive-restat: repaired $restated stale index entr$([ "$restated" -eq 1 ] && echo y || echo ies)"
fi

exit 0
