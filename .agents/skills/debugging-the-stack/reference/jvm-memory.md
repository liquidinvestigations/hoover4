# JVM and container memory

Verify that the affected process is a JVM before applying these checks.
Heap configuration, committed memory, resident memory, and container accounting measure different values.

For Cassandra, inspect heap usage, garbage collection, and dropped messages with the available runtime tools.

```sh
nodetool info
nodetool gcstats
nodetool tpstats
```

Compare those results with cgroup memory statistics and OOM events.
Inspect anonymous memory and reclaimable file cache separately.
A large container total alone does not establish heap exhaustion.
Use the process's actual settings and workload when judging available capacity.
