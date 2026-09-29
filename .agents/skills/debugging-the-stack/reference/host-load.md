# Host load

Inspect load, process ownership, CPU use, memory pressure, and I/O wait.
Do not infer the cause from load average alone.

```sh
uptime
ps -eo user,ni,pcpu,args --sort=-pcpu | head
```

Identify project-owned work before changing priorities or stopping a process.
A priority reduction can preserve an active build when CPU contention is the cause.
Verify the result against the resource that limited responsiveness.

Build parallelism uses `BUILD_JOBS` across the supported build tools.
Verify the rendered values for make, CMake, Cargo, and numerical-library thread settings.
Do not assume the configured default matches the running process.
