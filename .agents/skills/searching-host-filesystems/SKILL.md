---
name: searching-host-filesystems
description: Find a file or a configuration on a workstation or cluster host without a walk of every disk. Use before any find, fd, du, or locate outside the repository.
allowed-tools: Bash, Read
---

# Searching host file systems

A walk from `/` or from a top-level mount directory reads every disk that the host mounts.
On the hoover4 hosts that includes the dataset disks, the TopoLVM volumes, the Compose volumes, and the home disk.
Such a walk loads all disks for many minutes and slows the cluster and the user's work.
The harness moves a long command to the background, and the walk then continues there.

## Find the location from a record first

1. Read `INFRASTRUCTURE_INVENTORY.md`. It names the data, configuration, and runtime directories.
2. Read the install script or the unit that created the file. `systemctl cat <unit>` shows its paths.
3. Read the command line of the process that uses the file: `ps -o args= -p <pid>`.
4. Read the configuration that names the file, for example a containerd drop-in or a runtime class handler.

## Search only a named directory

- Name the directory that should hold the file, for example `find /var/lib/rancher/k3s/agent/etc -name 'config.toml*'`.
- Add `-xdev` so the walk stays on one file system.
- Add `-maxdepth 3` when the directory is a system directory such as `/etc` or `/var/lib`.
- Do not write `find /` as a fallback after `||`. A failed first command then starts the walk without review.
- Do not run `du`, `find`, or `locate` with `sudo` on `/`, `/mnt`, `/home`, or `/var` without a depth limit.

## Run a necessary wide search with limits

A wide search is necessary only when the records do not name the location.
Ask the user before you start it, and name the directory and the expected duration.
Run it with `ionice -c3 timeout 120`, with `-xdev`, and in the foreground.
Stop the search when it reaches its time limit. Do not let the harness move it to the background.

## Stop a walk that runs too long

Find it with `ps -eo pid,etime,args | grep '[f]ind /'`.
Stop it with `sudo -n kill <pid>`, and verify that the process is absent.
Report the command, the start time, and the disks that it read.

## The hook enforces part of this procedure

`.agents/hooks/deny-unscoped-search.py` refuses `find` and `fd` rooted at `/` or at a top-level mount directory.
It allows the walk when `-maxdepth` is 3 or less. It cannot read a command inside `sh -c '...'` or a script.
