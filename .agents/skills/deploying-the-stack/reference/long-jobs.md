# Running a long job without losing it

Builds, resets, re-ingests and the end-to-end verification all run for tens of minutes.
Three habits, each of which has already cost real time when skipped.

## Capture the whole output, always

```
.agents/skills/deploying-the-stack/scripts/deploy-logged.sh --build
```

It redirects everything to a file, echoes the exit status on its own line, and prints the
error context. Then grep the file. **Never judge a build from `tail -50`**: the interesting
failure is usually thousands of lines above the end, and reading only the tail has cost a
full rebuild cycle to recover.

## Background it and keep working

Start it detached and let the harness notify you when it exits, rather than writing an
`until … grep … done` loop or re-tailing an output file every thirty seconds. Polling by hand
costs attention continuously and answers nothing that the exit notification does not.

If you do want a monitor, **make it emit only on failure signatures** — and then check that
its filter would actually fire on a crash. A monitor whose pattern cannot match a crash makes
silence indistinguishable from success, which is worse than no monitor.

## Do not disturb something already running

The end-to-end verification runs inside the worker container. **Any deploy restarts that
container and kills the run** with a signal exit. Before deploying:

```
docker ps --format '{{.Names}}\t{{.Status}}'
uptime
ps -eo user,ni,pcpu,args --sort=-pcpu | head
```

Check the **owner** column: more than one account may run its own container runtime on a
shared machine, so the process at the top of the list is not necessarily yours, and killing
your own work will not help when it is not.

If a long build is most of the way through and the machine is unresponsive, **renice its
process tree to 19 rather than killing it**. It has already paid for gigabytes of downloads,
and renicing restores interactive responsiveness without discarding that.

Load average lags the fix — it counts runnable tasks. Judge by the top processes' CPU share
and by whether the machine responds, not by the number.

## Batch your fixes

One restart should serve several changes. Collecting three fixes and deploying once is not
laziness; it is the difference between one interruption of whatever else is running and
three.
