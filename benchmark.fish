#!/usr/bin/env fish

# Benchmark `kcd-gfx diff` between two commits, each in its own temporary worktree and venv.
# Must be run from inside the repository (its root or any subdirectory).

set -l usage "usage: benchmark.fish [-b REV] [-a REV | -t] [-w N] [-r N] [--] DIFF_ARGS...

Benchmark `kcd-gfx diff` between two git revisions, each checked out in its own
temporary worktree with its own virtual environment.

  DIFF_ARGS           arguments for `kcd-gfx diff`; put them after -- if they
                      clash with the options below
  -b, --before REV    baseline revision (default: parent of --after)
  -a, --after REV     revision to compare against the baseline (default: HEAD)
  -t, --working-tree  benchmark the working tree, uncommitted changes included,
                      instead of --after (--before then defaults to HEAD)
  -w, --warmup N      number of warmup runs per revision (default: 1)
  -r, --runs N        number of timed runs per revision (default: 20)
  -h, --help          show this help and exit

REV is anything that resolves to a commit: hash, branch, tag, HEAD~1, etc."

argparse --name=benchmark.fish --ignore-unknown --exclusive after,working-tree h/help 'b/before=' 'a/after=' \
    t/working-tree 'w/warmup=!_validate_int --min 1' 'r/runs=!_validate_int --min 1' -- $argv
or begin
    echo $usage >&2
    return 1
end

if set -q _flag_help
    echo $usage
    return 0
end

if test (count $argv) -eq 0
    echo $usage >&2
    return 1
end

set -l after_ref HEAD
set -q _flag_after && set after_ref $_flag_after
set -l before_ref "$after_ref~1"
set -q _flag_working_tree && set before_ref HEAD
set -q _flag_before && set before_ref $_flag_before
set -l warmup 1
set -q _flag_warmup && set warmup $_flag_warmup
set -l runs 20
set -q _flag_runs && set runs $_flag_runs

set -l root (path dirname (path resolve (status filename)))
if test "$(git rev-parse --show-toplevel 2>/dev/null)" != "$root"
    echo "benchmark.fish: must be run from inside $root" >&2
    return 1
end

for ref in $after_ref $before_ref
    if not git rev-parse --verify --quiet "$ref^{commit}" >/dev/null
        echo "benchmark.fish: not a commit: $ref" >&2
        return 1
    end
end

if not set -q _flag_working_tree
    and test (git rev-parse "$before_ref^{commit}") = (git rev-parse "$after_ref^{commit}")
    echo "benchmark.fish: before ($before_ref) and after ($after_ref) are the same commit" >&2
    return 1
end

set -l run_dir (mktemp -d -t kcd-gfx-benchmark.XXXXXX) || return 1
set -l before_wt $run_dir/before
set -l after_wt $run_dir/after
set -l command "kcd-gfx diff $(string join ' ' -- (string escape -- $argv))"

function __benchmark_on_sigint --on-signal INT
    # Observing SIGINT keeps fish from killing itself when a child is interrupted, so the cleanup still runs.
    set -g __benchmark_interrupted
end

function __benchmark_cleanup --on-event fish_exit -V run_dir -V before_wt -V after_wt
    for wt in $before_wt $after_wt
        test -d $wt && git worktree remove --force $wt
    end
    rm -rf $run_dir
end

function __benchmark_label -a ref
    # "REF, SHORT_HASH", or just SHORT_HASH when REF is itself a (possibly abbreviated) hash.
    set -l short (git rev-parse --short "$ref^{commit}")
    string match -q -- "$ref*" (git rev-parse "$ref^{commit}") && echo $short || echo "$ref, $short"
end

function __benchmark_notify -a exit_status
    set -l message "Finished with exit status $exit_status"
    if command -q osascript
        set -l sound Glass
        test $exit_status -ne 0 && set sound Basso
        osascript -e "display notification \"$message\" with title \"benchmark.fish\" sound name \"$sound\""
    else if command -q notify-send
        notify-send benchmark.fish $message
    end
end

git worktree add --detach --quiet $before_wt $before_ref || return 1
uv sync --project $before_wt --frozen --quiet || return 1

set -l after_project $root
set -l after_label "after (working tree)"
if not set -q _flag_working_tree
    git worktree add --detach --quiet $after_wt $after_ref || return 1
    uv sync --project $after_wt --frozen --quiet || return 1
    set after_project $after_wt
    set after_label "after ($(__benchmark_label $after_ref))"
end

# Let Python cache bytecode as in normal use. Otherwise fresh worktrees recompile every module on each run,
# while an existing venv (as used by --working-tree) still reads its old .pyc files.
set -e PYTHONDONTWRITEBYTECODE

# Keep the machine from sleeping during the benchmark. `env` just runs the command, if no tool is available.
# systemd-inhibit may exist but be denied (e.g. under WSL, or outside an active login session), so probe it first.
set -l keep_awake env
if command -q caffeinate
    set keep_awake caffeinate
else if command -q systemd-inhibit && systemd-inhibit --what=idle:sleep true 2>/dev/null
    set keep_awake systemd-inhibit --what=idle:sleep
end

# Use --project rather than cd, so that relative DIFF_ARGS resolve from the caller's directory.
$keep_awake hyperfine --warmup $warmup --runs $runs \
    -n "before ($(__benchmark_label $before_ref))" \
    "uv run --no-sync --project $(string escape -- $before_wt) $command" \
    -n $after_label "uv run --no-sync --project $(string escape -- $after_project) $command"
set -l benchmark_status $status

# No need to notify when interrupted with Ctrl-C (systemd-inhibit reports it as exit status 1, not 130).
set -q __benchmark_interrupted || __benchmark_notify $benchmark_status

return $benchmark_status
