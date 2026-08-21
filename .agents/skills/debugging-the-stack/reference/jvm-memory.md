# JVM memory is not container memory

A JVM sized with `-Xms == -Xmx` commits its whole heap at boot, so the container's RSS sits
just under the cgroup limit from the first second of uptime whether it is doing anything or
not. Cassandra with `MAX_HEAP_SIZE=4G` reports ~5.7 GiB of a 5.86 GiB limit while using
1.3 GB of that 4 GB heap. Reading that as "about to OOM" is wrong every time, and the same
applies to Elasticsearch and any other JVM here.

Ask the runtime instead:

    nodetool info      # Heap Memory (MB): used / max
    nodetool gcstats   # GC time against uptime
    nodetool tpstats   # dropped messages

A healthy node is a low heap fraction, GC well under 1 % of wall time, and zero drops.

The container-side number worth reading is `anon` in `/sys/fs/cgroup/memory.stat`, never
the `docker stats` total, which counts reclaimable page cache as usage.
