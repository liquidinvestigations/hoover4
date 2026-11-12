#!/usr/bin/env python3
"""Prepare one host of the Hoover k3s cluster for the k3s install. Run it as root.

This file is the source. write-host-copies.py writes one copy for each host, with THIS and SITE set
from the site file. Run the copy of the host, root-install-<host>.py.

The script has four steps and runs them in this order. Each step reads the state of the host
first and skips the work that is already done. A second run continues after a failure.

  wireguard  Add direct WireGuard peers to the VPN interface of the host (vpn_interface of the site file, default wg0).
             The two on-prem hosts connect over the LAN. The other peers and routes of the interface stay unchanged.
  software   Install the missing packages. Stop and disable Docker on the on-prem hosts.
  settings   Write the kernel module, sysctl, NetworkManager and SELinux settings for k3s.
  storage    Shrink the ext4 file system of /storage to 300 GiB on an on-prem host. Add an LVM
             partition in the free space of the disk. Create the volume group and the k3s volumes.
  backup     On the backup node of the site file, create the backup mount folder with the folders zones and platform.
             The operator user owns them, with mode 0700. The step changes nothing on another node.

Commands:
  root-install-<host>.py --dry-run          Show the changes. Change nothing.
  root-install-<host>.py                    Do all steps.
  root-install-<host>.py --only wireguard   Do the given steps only.
  root-install-<host>.py --check            Show the state of the host.
  root-install.py --bundle NAME --node NODE Read hosts.json from ~<operator>/k3s-install/NAME instead of the SITE of
                                            this copy. --operator USER names the operator of a root run without sudo.
Arguments are names. The host paths come from the site file. The rules of root-install-k3s.py apply.

Run the public host first, then the on-prem hosts. A new peer works when both of its hosts have it.
Run the storage step inside tmux. If resize2fs stops before it ends, the file system can be damaged.
The script runs with Python 3.9, the version of RHEL 9.
"""
import argparse
import difflib
import math
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

# write-host-copies.py sets these two values in the copy of each host.
THIS = None
SITE = None

# Each host entry of the site file has these keys. hosts.example.json shows the format.
#   wg_ip   the VPN address        wg_if   the VPN interface           key     the WireGuard public key
#   port    the WireGuard listen port
#   public  "address:port" of a host that other hosts can reach from the internet, or null
#   lan_ip  the LAN address of an on-prem host, or null                onprem  true for a host behind NAT
HOSTS = SITE["hosts"] if SITE else {}
SCRIPT = f"root-install-{THIS}.py"
WG_IF = "wg0"
WG_CONF = "/etc/wireguard/wg0.conf"


def use_interface(name):
    """Use the VPN interface of the host. A host can keep the interface of an existing VPN, for example a GPU host."""
    global WG_IF, WG_CONF
    WG_IF, WG_CONF = name, f"/etc/wireguard/{name}.conf"
KEEPALIVE = 21

# The package names on RHEL and on Debian. zstd unpacks the Kata Containers static release. The NFS client lets the
# kubelet mount the Hoover data directories.
PACKAGES = [("zstd", "zstd"), ("nfs-utils", "nfs-common")]
DOCKER_UNITS = ["docker.socket", "docker.service", "containerd.service"]
MODULES = ["overlay", "br_netfilter", "tun", "vhost_net", "vhost_vsock"]
SYSCTL = {
    "net.ipv4.ip_forward": "1",
    "net.bridge.bridge-nf-call-iptables": "1",
    "net.bridge.bridge-nf-call-ip6tables": "1",
    "fs.inotify.max_user_instances": "8192",
    "fs.inotify.max_user_watches": "1048576",
    "vm.max_map_count": "262144",
}
MODULES_FILE = "/etc/modules-load.d/90-k3s-node.conf"
SYSCTL_FILE = "/etc/sysctl.d/90-k3s-node.conf"
NM_FILE = "/etc/NetworkManager/conf.d/90-k3s-node.conf"
NM_TEXT = "[keyfile]\nunmanaged-devices=interface-name:cni0;interface-name:flannel*;interface-name:veth*\n"

DISK = "/dev/sdb"
PART = "/dev/sdb1"
NEW_PART = "/dev/sdb2"
STORAGE = "/storage"
# fstab bind mounts of folders on /storage. The script unmounts them before /storage and mounts them after it.
BIND_MOUNTS = ["/var/lib/docker", "/opt"]
STORAGE_GIB = 300
LVM_TYPE = "E6D6D379-F507-44C2-A23C-238F2A3DF928"
# TopoLVM uses the free space of this volume group. The name gives the storage tier of the disk.
VG = "tier-hdd"
# The k3s data does not fit on /var (20 GiB). lvextend -r can grow these volumes later.
K3S_VOLUMES = [("rancher", "150G", "/var/lib/rancher"), ("kubelet", "100G", "/var/lib/kubelet")]
TABLE_BACKUP = "/root/root-install-sdb-before.sfdisk"
FSTAB = "/etc/fstab"

DRY = False
LOG = None
REBOOT = []


def say(text=""):
    print(text, flush=True)
    if LOG:
        LOG.write(text + "\n")
        LOG.flush()


def fail(text):
    say(f"ERROR: {text}")
    sys.exit(1)


def read(cmd):
    """Run a command that changes nothing. Return the exit code and the output."""
    if not shutil.which(cmd[0]):
        return 127, ""
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    return proc.returncode, proc.stdout


def change(cmd, ok=(0,), input_text=None):
    """Run a command that changes the host and log its output. A dry run only shows it."""
    say("  $ " + shlex.join(cmd) + (" < (the table above)" if input_text else ""))
    if DRY:
        return ""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if input_text else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if input_text:
        proc.stdin.write(input_text)
        proc.stdin.close()
    lines = []
    for line in proc.stdout:
        lines.append(line)
        say("    " + line.rstrip())
    code = proc.wait()
    if code not in ok:
        fail(f"{cmd[0]} exited with code {code}")
    return "".join(lines)


def write_file(path, text, mode=0o644, secret=False):
    """Write a file when its content differs. Keep the first earlier version as <path>.before-root-install."""
    old = open(path).read() if os.path.exists(path) else None
    if old == text:
        say(f"  {path} is current")
        return False
    say(f"  write {path}")
    if not secret:
        for line in text.splitlines():
            say(f"    | {line}")
    if DRY:
        return True
    if old is not None and not os.path.exists(path + ".before-root-install"):
        shutil.copy2(path, path + ".before-root-install")
        # copy2 keeps the mode of the old file. A copy of a secret is readable by root only.
        os.chmod(path + ".before-root-install", mode if secret else os.stat(path).st_mode & 0o7777)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".root-install-tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------- wireguard

def peer_endpoint(name):
    me, peer = HOSTS[THIS], HOSTS[name]
    if peer["public"]:
        return peer["public"]
    if me["onprem"] and peer["onprem"]:
        return f"{peer['lan_ip']}:{peer['port']}"
    # The on-prem hosts are behind NAT. They start the handshake, and the public host learns their address.
    return None


def set_listen_port(lines, port):
    """Return the lines of the interface file with ListenPort set in the [Interface] section."""
    lines = list(lines)
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "[interface]"), None)
    if start is None:
        fail(f"{WG_CONF} has no [Interface] section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    wanted = f"ListenPort = {port}"
    for i in range(start + 1, end):
        if re.match(r"\s*ListenPort\s*=", lines[i], re.I):
            lines[i] = wanted
            return lines
    lines.insert(start + 1, wanted)
    return lines


def peer_blocks(text):
    """Return the lines of the [Peer] sections for the hosts that the interface file does not have."""
    present = set(re.findall(r"^\s*PublicKey\s*=\s*(\S+)", text, re.M | re.I))
    blocks = []
    for name, peer in HOSTS.items():
        if name == THIS or peer["key"] in present:
            continue
        blocks += ["", f"# Direct peer {name}, added by {SCRIPT}", "[Peer]", f"PublicKey = {peer['key']}"]
        endpoint = peer_endpoint(name)
        if endpoint:
            blocks.append(f"Endpoint = {endpoint}")
        blocks += [f"AllowedIPs = {peer['wg_ip']}/32", f"PersistentKeepalive = {KEEPALIVE}"]
    return blocks


def step_wireguard():
    me = HOSTS[THIS]
    code, key = read(["wg", "show", WG_IF, "public-key"])
    if code != 0:
        fail(f"{WG_IF} is not up")
    if key.strip() != me["key"]:
        fail(f"the public key of {WG_IF} is not the key of {THIS}. Use the script of this host.")
    text = open(WG_CONF).read()
    lines = text.splitlines()
    new = set_listen_port(lines, me["port"]) + peer_blocks(text)
    if new == lines:
        say(f"  {WG_CONF} has the listen port and all peers")
    else:
        # The file holds the private key, so only the changed lines are shown.
        for line in difflib.unified_diff(lines, new, lineterm="", n=0):
            if line[:1] in "+-" and not line.startswith(("+++", "---")) and not re.match(r"[+-]\s*PrivateKey", line, re.I):
                say(f"    {line}")
        write_file(WG_CONF, "\n".join(new) + "\n", mode=0o600, secret=True)
        # syncconf changes the peers and the port of the running interface. It keeps the other peers up.
        if not DRY:
            code, stripped = read(["wg-quick", "strip", WG_IF])
            if code != 0:
                fail(f"wg-quick strip {WG_IF} failed: {stripped}")
            with tempfile.NamedTemporaryFile("w", dir="/run", prefix=f"{WG_IF}-", delete=False) as f:
                f.write(stripped)
            try:
                change(["wg", "syncconf", WG_IF, f.name])
            finally:
                os.unlink(f.name)
        else:
            say(f"  $ wg syncconf {WG_IF} <(wg-quick strip {WG_IF})")
    if not DRY:
        verify_peers()


def verify_peers():
    others = [n for n in HOSTS if n != THIS]
    pending = set(others)
    deadline = time.time() + 30
    while pending and time.time() < deadline:
        _, out = read(["wg", "show", WG_IF, "latest-handshakes"])
        stamps = dict(l.split()[:2] for l in out.splitlines() if l.strip())
        pending = {n for n in pending if int(stamps.get(HOSTS[n]["key"], "0")) == 0}
        if pending:
            time.sleep(2)
    _, out = read(["wg", "show", WG_IF, "endpoints"])
    endpoints = dict(l.split()[:2] for l in out.splitlines() if l.strip())
    for name in others:
        if name in pending:
            say(f"  {name}: no handshake. Run {name}'s script, then run this script again with --only wireguard.")
            continue
        code, out = read(["ping", "-c", "3", "-W", "2", HOSTS[name]["wg_ip"]])
        rtt = re.search(r"= [\d.]+/([\d.]+)/", out)
        state = f"ping {rtt.group(1)} ms" if code == 0 and rtt else "ping failed"
        say(f"  {name}: handshake over {endpoints.get(HOSTS[name]['key'], '?')}, {state}")


# ---------------------------------------------------------------- software

def step_software():
    rpm = shutil.which("dnf") is not None
    for names in PACKAGES:
        package = names[0] if rpm else names[1]
        installed = read(["rpm", "-q", package] if rpm else ["dpkg", "-s", package])[0] == 0
        if installed:
            say(f"  {package} is installed")
        else:
            change(["dnf", "-y", "install", package] if rpm else ["apt-get", "install", "-y", package])
    if not HOSTS[THIS]["onprem"]:
        return
    # k3s brings its own containerd. Docker holds bind mounts of /storage, which the storage step unmounts.
    for unit in DOCKER_UNITS:
        active = read(["systemctl", "is-active", unit])[1].strip() == "active"
        enabled = read(["systemctl", "is-enabled", unit])[1].strip() == "enabled"
        if active or enabled:
            change(["systemctl", "disable", "--now", unit])
        else:
            say(f"  {unit} is stopped and disabled")


# ---------------------------------------------------------------- settings

def step_settings():
    write_file(MODULES_FILE, "".join(m + "\n" for m in MODULES))
    for module in MODULES:
        if not os.path.exists(f"/sys/module/{module}"):
            change(["modprobe", module])
    if write_file(SYSCTL_FILE, "".join(f"{k} = {v}\n" for k, v in SYSCTL.items())):
        change(["sysctl", "-q", "-p", SYSCTL_FILE])
    if read(["systemctl", "is-active", "NetworkManager"])[1].strip() == "active":
        if write_file(NM_FILE, NM_TEXT):
            change(["systemctl", "reload", "NetworkManager"])
    if os.path.exists("/etc/selinux/config"):
        settings_selinux()


def settings_selinux():
    """Disable SELinux. RHEL 9 disables it fully with the kernel argument selinux=0."""
    text = open("/etc/selinux/config").read()
    write_file("/etc/selinux/config", re.sub(r"(?m)^SELINUX=.*$", "SELINUX=disabled", text))
    _, info = read(["grubby", "--info", "ALL"])
    kernel_args = re.findall(r'(?m)^args="(.*)"$', info)
    if not kernel_args or any("selinux=0" not in a.split() for a in kernel_args):
        change(["grubby", "--update-kernel", "ALL", "--args", "selinux=0"])
    mode = read(["getenforce"])[1].strip()
    if mode == "Enforcing":
        change(["setenforce", "0"])
    if mode != "Disabled":
        REBOOT.append(f"SELinux is {mode}. It is disabled after the reboot.")


# ---------------------------------------------------------------- storage

def parse_table(text):
    """Return the header and the partitions of `sfdisk --dump` output."""
    header, parts = {}, {}
    for line in text.splitlines():
        if " : " in line:
            node, fields = line.split(" : ", 1)
            parts[node.strip()] = {k: v.strip() for k, v in re.findall(r'(\w+)=\s*("[^"]*"|[^,]+)', fields)}
        elif ": " in line:
            key, value = line.split(": ", 1)
            header[key.strip()] = value.strip()
    return header, parts


def new_table(text, header, parts, fs_bytes):
    """Return the new table text, the new size of the first partition and the second partition, in sectors.

    The first partition keeps its start and ends 1 MiB after the file system. The second partition
    starts at the next MiB and takes the rest of the disk.
    """
    sector = int(header.get("sector-size", "512"))
    mib = 2**20 // sector
    start = int(parts[PART]["start"])
    p1_size = math.ceil(math.ceil(fs_bytes / sector) / mib) * mib + mib
    p2_start = math.ceil((start + p1_size) / mib) * mib
    p2_size = (int(header["last-lba"]) + 1 - p2_start) // mib * mib
    if p1_size > int(parts[PART]["size"]) or p2_size < 1024 * mib:
        fail(f"{DISK} has no room for a second partition after {fs_bytes} bytes of file system")
    out = []
    for line in text.splitlines():
        if line.startswith(PART + " "):
            line = re.sub(r"(size=\s*)\d+", lambda m: m.group(1) + str(p1_size), line, count=1)
        out.append(line)
    out.append(f"{NEW_PART} : start={p2_start}, size={p2_size}, type={LVM_TYPE}")
    return "\n".join(out) + "\n", p1_size, (p2_start, p2_size)


def fs_geometry():
    code, out = read(["dumpe2fs", "-h", PART])
    if code != 0:
        fail(f"dumpe2fs -h {PART} failed")
    value = lambda name: int(re.search(rf"(?m)^{name}:\s+(\d+)", out).group(1))
    return value("Block size"), value("Block count"), value("Free blocks")


def mounted(path):
    return read(["findmnt", "-rn", path])[0] == 0


def step_backup():
    """Create the backup folder of [backup] path, owned by the operator user, when this host is the backup node."""
    backup = SITE.get("backup") or {}
    if backup.get("node") != THIS or not backup.get("path"):
        say("  this host is not the backup node")
        return
    path = backup["path"]
    if not path.startswith("/") or ".." in path.split("/"):
        fail(f"the backup path {path!r} of the site file is not an absolute path")
    user = pwd.getpwnam(name_arg(SITE.get("user") or "", "operator user"))
    for folder in (path, f"{path}/zones", f"{path}/platform"):
        if os.path.islink(folder):
            fail(f"{folder} is a symbolic link")
        if not os.path.isdir(folder):
            change(["install", "-d", "-m", "0700", "-o", user.pw_name, "-g", str(user.pw_gid), folder])
        else:
            say(f"  {folder} exists")


def step_storage(assume_yes):
    if not HOSTS[THIS]["onprem"]:
        say("  this host has no storage step")
        return
    os.chdir("/")
    code, dump = read(["sfdisk", "--dump", DISK])
    if code != 0:
        fail(f"sfdisk --dump {DISK} failed: {dump}")
    header, parts = parse_table(dump)
    if NEW_PART in parts:
        say(f"  {NEW_PART} exists. The shrink is done.")
    else:
        shrink(dump, header, parts, assume_yes)
    for path in [STORAGE] + BIND_MOUNTS[::-1]:
        if not mounted(path):
            change(["mount", path])
    make_volumes()


def shrink(dump, header, parts, assume_yes):
    if header.get("label") != "gpt" or list(parts) != [PART]:
        fail(f"{DISK} must have a GPT table with the one partition {PART}. It has {list(parts)}.")
    if read(["blkid", "-o", "value", "-s", "TYPE", PART])[1].strip() != "ext4":
        fail(f"{PART} is not ext4")
    sector = int(header.get("sector-size", "512"))
    block_size, blocks, free = fs_geometry()
    target = STORAGE_GIB * 2**30
    if mounted(STORAGE):
        # The superblock of a mounted file system has an old free block count.
        st = os.statvfs(STORAGE)
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
    else:
        used = (blocks - free) * block_size
    if used > 0.8 * target:
        fail(f"{STORAGE} holds {used / 2**30:.0f} GiB. That is more than 80 % of {STORAGE_GIB} GiB.")
    table, p1_size, (p2_start, p2_size) = new_table(dump, header, parts, min(blocks * block_size, target))
    say(f"  {PART}: ext4 {blocks * block_size / 2**30:.0f} GiB, {used / 2**30:.0f} GiB used, new size {STORAGE_GIB} GiB")
    say(f"  {PART}: new size {p1_size} sectors, {p1_size * sector / 2**30:.3f} GiB")
    say(f"  {NEW_PART}: start {p2_start}, size {p2_size} sectors, {p2_size * sector / 2**30:.0f} GiB, LVM")
    if mounted(STORAGE):
        # fuser writes the process numbers to stdout. The mount entries go to stderr.
        pids = subprocess.run(["fuser", "-m", STORAGE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True).stdout.split()
        if pids:
            say(read(["ps", "-o", "pid,user,cmd", "-p", ",".join(pids)])[1].rstrip())
            fail(f"these processes use {STORAGE}. Stop them, then run the script again.")
    if not DRY and not assume_yes:
        say(f'  Type "shrink" to unmount {STORAGE}, shrink it and change the partition table of {DISK}.')
        if input("  > ").strip() != "shrink":
            fail("the person stopped the storage step")
    for path in BIND_MOUNTS + [STORAGE]:
        if mounted(path):
            change(["umount", path])
    change(["e2fsck", "-f", "-y", PART], ok=(0, 1))
    if blocks * block_size > target:
        say("  resize2fs moves the data above the new end. This can take a long time on hard disks.")
        change(["resize2fs", "-p", PART, f"{STORAGE_GIB}G"])
    if not DRY:
        block_size, blocks, _ = fs_geometry()
        table, p1_size, _ = new_table(dump, header, parts, blocks * block_size)
        if blocks * block_size > p1_size * sector:
            fail("the file system is larger than the new partition. The partition table is not changed.")
    write_file(TABLE_BACKUP, dump, mode=0o600)
    say("  new partition table:")
    for line in table.splitlines():
        say(f"    | {line}")
    change(["sfdisk", "--wipe", "never", "--wipe-partitions", "never", DISK], input_text=table)
    change(["udevadm", "settle"])
    if DRY:
        return
    name = os.path.basename(PART)
    part_bytes = int(open(f"/sys/class/block/{name}/size").read()) * 512
    if part_bytes < blocks * block_size:
        fail(f"the kernel shows {PART} smaller than its file system. Do not mount it. "
             f"Restore the table with: sfdisk {DISK} < {TABLE_BACKUP}")
    change(["e2fsck", "-f", "-n", PART])


def make_volumes():
    if read(["vgs", VG])[0] != 0:
        if read(["pvs", NEW_PART])[0] != 0:
            change(["pvcreate", "--yes", NEW_PART])
        change(["vgcreate", VG, NEW_PART])
    else:
        say(f"  volume group {VG} exists")
    fstab = open(FSTAB).read()
    for name, size, path in K3S_VOLUMES:
        dev = f"/dev/{VG}/{name}"
        if read(["lvs", f"{VG}/{name}"])[0] != 0:
            change(["lvcreate", "--yes", "-n", name, "-L", size, VG])
        if DRY or read(["blkid", "-o", "value", "-s", "TYPE", dev])[1].strip() != "ext4":
            change(["mkfs.ext4", "-q", "-L", name, dev])
        if not re.search(rf"(?m)^{re.escape(dev)}\s", fstab):
            fstab += f"{dev} {path} ext4 defaults,noatime 0 2\n"
        if mounted(path):
            say(f"  {path} is mounted")
            continue
        if os.path.isdir(path) and os.listdir(path):
            fail(f"{path} is not empty. Move its content away, then run the script again.")
        say(f"  mkdir -p {path}")
        if not DRY:
            os.makedirs(path, exist_ok=True)
    if write_file(FSTAB, fstab):
        change(["systemctl", "daemon-reload"])
    for _, _, path in K3S_VOLUMES:
        if not mounted(path):
            change(["mount", path])
    if not DRY:
        say(read(["vgs", VG])[1].rstrip())
        say(read(["lvs", VG])[1].rstrip())


# ---------------------------------------------------------------- check

def check():
    me = HOSTS[THIS]
    say(f"host {THIS}, {WG_IF} {me['wg_ip']}")
    _, out = read(["wg", "show", WG_IF])
    say("\n".join(l for l in out.splitlines() if "private" not in l))
    verify_peers()
    for title, cmd in [
        ("SELinux", ["getenforce"]),
        ("Docker", ["systemctl", "is-active"] + DOCKER_UNITS),
        ("modules", ["sh", "-c", "lsmod | grep -E '^(" + "|".join(MODULES) + ") ' | cut -d' ' -f1"]),
        ("sysctl", ["sysctl"] + list(SYSCTL)),
    ] + ([
        ("disk", ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT", DISK]),
        ("volumes", ["lvs", VG]),
    ] if me["onprem"] else []):
        code, out = read(cmd)
        if code != 127:
            say(f"--- {title}\n{out.rstrip()}")


# Names and paths of the arguments. The same rules are in root-install.py, root-install-local.py and
# ../migration/root_copy.py, because each root script runs as one file.
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def name_arg(value, what="name"):
    """value when it is a name: letters, digits, '.', '_' and '-', no '/', and not '.' or '..' at the start."""
    if not isinstance(value, str) or not NAME.fullmatch(value):
        fail(f"the {what} {value!r} is not a name. A name has letters, digits, '.', '_' and '-', and no '/'.")
    return value


def below(base, relative):
    """The path of relative below base. Refuse an absolute path, '..', and a symbolic link below base."""
    if not relative or relative.startswith("/"):
        fail(f"{relative!r} is not a relative path")
    path = base
    if os.path.islink(base):
        fail(f"{base} is a symbolic link")
    for part in relative.split("/"):
        if part in ("", ".", ".."):
            fail(f"{relative!r} has an empty, '.' or '..' part")
        path = os.path.join(path, part)
        if os.path.islink(path):
            fail(f"{path} is a symbolic link")
    real = os.path.realpath(base)
    if os.path.commonpath([real, os.path.realpath(path)]) != real:
        fail(f"{relative!r} leaves {base}")
    return path


def operator_user(named):
    """The operator account: the user that runs sudo, else --operator, else the user of the site."""
    by_sudo = os.environ.get("SUDO_USER", "")
    if by_sudo and named and named != by_sudo:
        fail(f"--operator {named} differs from the user {by_sudo} that runs sudo")
    if os.geteuid() != 0:
        return pwd.getpwuid(os.getuid())
    name = by_sudo or named
    if not name:
        fail("name the operator user with --operator")
    try:
        return pwd.getpwnam(name_arg(name, "operator user"))
    except KeyError:
        fail(f"the user {name} does not exist")


def install_folder(user, *names):
    """~<user>/k3s-install/<names...>, checked with below()."""
    return below(user.pw_dir, "/".join(["k3s-install"] + [name_arg(n) for n in names]))


def main():
    global DRY, LOG
    steps = ["wireguard", "software", "settings", "storage", "backup"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show the changes and change nothing")
    parser.add_argument("--only", nargs="+", choices=steps, help="do these steps only")
    parser.add_argument("--yes", action="store_true", help="do not ask before the partition change")
    parser.add_argument("--check", action="store_true", help="show the state of the host")
    parser.add_argument("--bundle", help="read hosts.json from ~<operator>/k3s-install/NAME instead of the SITE of this copy")
    parser.add_argument("--node", help="the node of this host in the hosts.json of the bundle")
    parser.add_argument("--operator", help="the operator user of a root run without sudo")
    args = parser.parse_args()
    global THIS, SITE, HOSTS, SCRIPT
    if args.bundle:
        import json
        folder = install_folder(operator_user(args.operator), args.bundle)
        SITE = json.load(open(below(folder, "hosts.json")))
        node = name_arg(args.node or "", "node")
        THIS, HOSTS, SCRIPT = node, SITE["hosts"], f"root-install.py --node {node}"
    if THIS is None or THIS not in HOSTS:
        fail("this file has no host. Run write-host-copies.py, then run the copy of this host.")
    use_interface(HOSTS[THIS].get("wg_if") or "wg0")
    if os.geteuid() != 0:
        fail("run the script as root")
    DRY = args.dry_run
    if args.check:
        check()
        return
    chosen = [s for s in steps if s in (args.only or steps)]
    # Only the shrink of the file system needs tmux. A host whose partition exists already runs the step anywhere, for
    # example from the deployment driver.
    shrink_pending = HOSTS[THIS]["onprem"] and NEW_PART not in read(["sfdisk", "--dump", DISK])[1]
    if "storage" in chosen and shrink_pending and not DRY and not (os.environ.get("TMUX") or os.environ.get("STY")):
        fail("the storage step must run inside tmux or screen. Start tmux, then run the script again.")
    if not DRY:
        LOG = open(f"/root/root-install-{THIS}.log", "a")
    say(f"== {SCRIPT} {time.strftime('%Y-%m-%d %H:%M:%S')}{' dry run' if DRY else ''}")
    for step in chosen:
        say(f"== {step}")
        if step == "storage":
            step_storage(args.yes)
        else:
            globals()["step_" + step]()
    say("== done")
    for reason in REBOOT:
        say(f"Reboot needed: {reason}")
    if not DRY and set(chosen) & {"settings", "storage"}:
        say("Reboot the host, then run the script with --check. The reboot verifies the boot settings and fstab.")


if __name__ == "__main__":
    main()
