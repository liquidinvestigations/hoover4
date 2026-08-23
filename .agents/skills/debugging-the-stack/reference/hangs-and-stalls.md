# Hangs and stalls

A hang is a question about who is blocked. Check the runtime's view and the process's view
separately and compare. They routinely disagree. Temporal reporting `State: Started` did
not mean the worker was running anything.

`docker stats` showing low CPU means blocked on I/O or on a lock, not slow work.

To see Python stacks, py-spy needs `CAP_SYS_PTRACE`, which these containers drop. Attach
from a sidecar sharing the pod and PID namespace:

    scripts/pyspy-sidecar.sh <container> [pid]

A thread dump ends the guessing immediately. Reach for it earlier than feels justified.

A synchronous call on the event-loop thread stalls an activity indefinitely while
heartbeats keep flowing, so it is never retried and never fails. The dump is the only
thing that shows it.
