# An unresponsive host

`uptime` plus `ps -eo user,ni,pcpu,args --sort=-pcpu | head` names the cause in one step.

Three things that are easy to get wrong:

- **Check the owner column.** More than one account runs its own rootless podman here, so
  the process at the top of the list is not necessarily yours, and killing your own work
  will not help when it is not.
- **Prefer `renice -n 19` on an in-flight build's process tree over killing it.** A build
  most of the way through has already paid for gigabytes of wheel downloads; renicing
  restores interactive responsiveness without discarding that.
- **Load average stays high after the fix** — it counts runnable tasks, so it lags. Judge by
  `%CPU` of the top processes and by whether the desktop responds, not by the number.

Image builds bound their own parallelism through the `BUILD_JOBS` build arg (default 6),
which feeds every backend's own spelling of it — `MAX_JOBS`, `MAKEFLAGS`,
`CMAKE_BUILD_PARALLEL_LEVEL`, `CARGO_BUILD_JOBS`, and the `OMP`/`MKL` thread caps. Missing
one of them loses the bound, which is why they are set as a group.
