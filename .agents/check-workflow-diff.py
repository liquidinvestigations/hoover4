#!/usr/bin/env python3
"""Say whether a diff changes Temporal workflow code, which a running execution replays.

A workflow's history is replayed against the code that is deployed *now*, not against the
code that was deployed when it started. Change an activity and a running execution never
notices: activity results are already in the history and the new code only runs for the
next call. Change a workflow -- the order of its commands, the ids it gives its children,
a loop it takes, a timer it sets -- and the replay of a live execution reaches a point
where history and code disagree, and the execution wedges with a non-determinism error
until someone terminates it.

So the rule is asymmetric, and this tool is what makes it checkable rather than
remembered:

* **An `activities.py` change deploys freely.** Restart the worker whenever.
* **A `workflows.py` change needs no live executions of the workflows it touches.**
  Drain first -- let the queue empty, or terminate what is running and re-drive it --
  and only then deploy.

Usage:
    .agents/check-workflow-diff.py                  # working tree vs HEAD
    .agents/check-workflow-diff.py <ref>            # HEAD vs that ref
    .agents/check-workflow-diff.py <ref> <ref>      # between two refs

Exit status is 1 when the diff touches workflow code, so it can gate a deploy, and 0 when
the diff is activity-only or touches no pipeline code at all. Exit 1 is not "wrong": it is
"this one needs draining", and the files it names are why.
"""

import subprocess
import sys

#: Where the pipeline's Temporal code lives. Anything outside this is not workflow code
#: no matter what it is called.
PIPELINE_ROOT = "main_services/processing/tasks/"

#: Modules whose top-level symbols are replayed. `workflows.py` is the obvious one; the
#: others are files under the same root that define a `@workflow.defn` class, which is why
#: the filename test below is a fallback and the content test is the real one.
WORKFLOW_FILENAMES = ("workflows.py",)

#: What marks a file as replayed regardless of its name. `@workflow.defn` is the decorator
#: every workflow class carries; `workflow.execute_child_workflow` and `workflow.start_child_workflow`
#: appear in files that compose workflows without declaring one.
WORKFLOW_MARKERS = (
    "@workflow.defn",
    "workflow.execute_child_workflow",
    "workflow.start_child_workflow",
)


def run(args):
    return subprocess.run(
        args, capture_output=True, text=True, check=True).stdout


def changed_files(refs):
    if len(refs) == 0:
        # Working tree against HEAD, staged changes included.
        out = run(["git", "diff", "--name-only", "HEAD"])
    elif len(refs) == 1:
        out = run(["git", "diff", "--name-only", refs[0], "HEAD"])
    else:
        out = run(["git", "diff", "--name-only", refs[0], refs[1]])
    return [line for line in out.splitlines() if line.strip()]


def file_defines_workflow(path):
    """Whether the file at HEAD (or on disk) declares or drives a workflow."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        # Deleted in this diff: read it from HEAD instead, because deleting a workflow
        # is exactly as replay-breaking as editing one.
        try:
            text = run(["git", "show", "HEAD:%s" % path])
        except subprocess.CalledProcessError:
            return False
    return any(marker in text for marker in WORKFLOW_MARKERS)


def main(argv):
    refs = argv[1:]
    if any(a in ("-h", "--help") for a in refs):
        print(__doc__)
        return 0

    workflow_files = []
    activity_files = []
    for path in changed_files(refs):
        if not path.startswith(PIPELINE_ROOT) or not path.endswith(".py"):
            continue
        if path.endswith(WORKFLOW_FILENAMES) or file_defines_workflow(path):
            workflow_files.append(path)
        else:
            activity_files.append(path)

    if activity_files and not workflow_files:
        print("activity-only diff: %d pipeline file(s), no workflow code."
              % len(activity_files))
        print("Deploy and restart the worker whenever; running executions do not replay "
              "these.")
        return 0

    if not workflow_files:
        print("no pipeline code in this diff.")
        return 0

    print("WORKFLOW CODE CHANGED — drain before deploying.")
    print()
    for path in sorted(workflow_files):
        print("    %s" % path)
    print()
    print("A live execution of any of these replays its history against the new code and "
          "wedges on the first disagreement. Let the queue empty, or terminate what is "
          "running and re-drive it, before restarting the worker. What is live shows in "
          "the Temporal UI, filtered to running executions.")
    if activity_files:
        print()
        print("(%d activity file(s) in the same diff; those are free.)"
              % len(activity_files))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
