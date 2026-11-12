#!/usr/bin/env python3
"""Install k3s, gVisor and Kata Containers on one host of the Hoover cluster. Run it as root.

This file is the source. write-host-copies.py writes one copy for each host, with THIS and SITE set
from the site file. stage-k3s.sh downloads and verifies the input files into the staging folder first.
The token files come from the operator and stay in the staging folder.

One host runs the k3s server with its embedded datastore. The other hosts join it as agents.
Install the server first. Each node uses its wg0 address, and flannel VXLAN runs over wg0.
The local node of a single-node site uses the fixed address on the dummy link hoover4 (root-install-local.py), runs
k3s and its pods in hoover4.slice, and writes its admin kubeconfig to /etc/rancher/k3s/hoover4-admin.yaml, because
/etc/rancher/k3s/k3s.yaml can belong to another k3s user of the workstation. The driver ../deploy-k3s passes the site
with --hosts and --node and the destination of the kubeconfig with --kubeconfig-out.

The script does these steps. A second run writes the same files and restarts k3s only when a file changed.
A generated file that differs only in its comment lines is current. A comment change does not restart k3s.
  1. Verify the host, the mounts and the staged files.
  2. Install gVisor in /opt/gvisor and the Kata Go runtime with Cloud Hypervisor in /opt/kata.
  3. Write the Kata, gVisor and containerd runtime settings.
  4. Write /etc/rancher/k3s/config.yaml and the token file, and install k3s.
  5. On the server, copy the admin kubeconfig to the operator user.

Commands:
  root-install-k3s-<host>.py --dry-run   Show the changes. Change nothing.
  root-install-k3s-<host>.py             Install.
  --staged DIR                           Read the staged files from DIR. The default is the folder of the script.
  --hosts FILE --node NAME               Read the site from FILE and install NAME, instead of THIS and SITE.
  --kubeconfig-out FILE                  Copy the admin kubeconfig of the server to FILE for the operator user.
The script runs with Python 3.9, the version of RHEL 9.
"""
import argparse
import hashlib
import os
import pwd
import re
import shutil
import subprocess
import sys
import time

# write-host-copies.py sets these two values in the copy of each host.
THIS = None
SITE = None

STAGED = os.path.dirname(os.path.abspath(__file__))
K3S_VERSION = "v1.36.5+k3s1"
KATA_VERSION = "4.3.1"
KATA_SHA256 = "66b35b06f6b41b56f8606ddf3ed3e5660b0971d1e309d903457c4056a0b9eff0"
INSTALL_SH_SHA256 = "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad"
# The site file names the server node, the operator user and, for each host, wg_ip, onprem and the
# kubelet system-reserved value. hosts.example.json shows the format.
HOSTS = {}
SERVER = SERVER_URL = USER = None
KUBECONFIG_OUT = None


def use_site(site, this):
    """Set the site values of the script."""
    global THIS, SITE, HOSTS, SERVER, SERVER_URL, USER
    THIS, SITE = this, site
    HOSTS = site["hosts"] if site else {}
    SERVER = site["server"] if site else None
    SERVER_URL = f"https://{address(HOSTS[SERVER])}:6443" if site else None
    USER = site["user"] if site else None


def address(host):
    return host.get("wg_ip") or host.get("node_ip") or host.get("lan_ip")


def single(host):
    return bool(host.get("single") and host.get("local"))


def arch(host):
    return host.get("architecture") or "amd64"


K3S_DIR = "/etc/rancher/k3s"
CONTAINERD_DROPIN = "/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/runtimes.toml"
KATA_CONFIG = "/etc/kata-containers/configuration-clh.toml"
RUNSC_CONFIG = "/etc/gvisor/runsc.toml"
GVISOR_DIR = "/opt/gvisor"

RUNTIMES_TOML = f"""\
# gVisor for the openDesk and Hoover web applications.
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
  runtime_path = "{GVISOR_DIR}/containerd-shim-runsc-v1"
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runsc.options]
  TypeUrl = "io.containerd.runsc.v1.options"
  ConfigPath = "{RUNSC_CONFIG}"
# Kata Containers with the Go runtime and Cloud Hypervisor for the stores and parse workers.
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.kata]
  runtime_type = "io.containerd.kata.v2"
  runtime_path = "/opt/kata/bin/containerd-shim-kata-v2"
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.kata.options]
  ConfigPath = "{KATA_CONFIG}"
  SystemdCgroup = true
"""

# A GPU node also registers runsc with nvproxy, the GPU support of gVisor, as the handler runsc-nvproxy. The RuntimeClass
# gvisor-gpu of ../cluster/runtimeclasses.yaml names it. The NVIDIA container toolkit of the host gives k3s the handler
# nvidia, which runs a GPU pod with runc: the fallback of decision D20. stage-runsc-nvproxy.sh can stage a runsc that
# is built with gVisor PR 16643 (decision D3) in <staged>/runsc-nvproxy/. The handler then uses that binary.
RUNSC_NVPROXY_DIR = "/opt/gvisor-nvproxy"
RUNSC_NVPROXY_CONFIG = "/etc/gvisor/runsc-nvproxy.toml"
RUNSC_NVPROXY_TOML_FILE = f"""\
# runsc with nvproxy for the GPU services. The binary is the staged build of gVisor PR 16643 when it exists.
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runsc-nvproxy]
  runtime_type = "io.containerd.runsc.v1"
  runtime_path = "{GVISOR_DIR}/containerd-shim-runsc-v1"
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runsc-nvproxy.options]
  TypeUrl = "io.containerd.runsc.v1.options"
  ConfigPath = "{RUNSC_NVPROXY_CONFIG}"
"""
# The node label and taint of a GPU node. Only the GPU pods tolerate the taint (../platform/gpu/gpu_pool.py).
GPU_LABEL = "hoover.dev/gpu=true"
GPU_TAINT = "hoover.dev/gpu=true:NoSchedule"

RUNSC_TOML = f"""\
binary_name = "{GVISOR_DIR}/runsc"
# The kubelet uses the systemd cgroup driver. The runc option SystemdCgroup does not apply to the runsc options type.
[runsc_config]
  systemd-cgroup = "true"
"""

# The VM runs in the pod cgroup, so the RuntimeClass overhead and the pod limits hold it.
# The guest starts with 512 MiB and adds the memory limits of the containers.
KATA_CHANGES = [
    ("sandbox_cgroup_only = false", "sandbox_cgroup_only = true"),
    ("default_memory = 2048", "default_memory = 512"),
]

DRY = False
CHANGED = False


def say(text=""):
    print(text, flush=True)


def fail(text):
    say(f"ERROR: {text}")
    sys.exit(1)


def run(cmd, env=None, check=True):
    say("  $ " + " ".join(cmd))
    if DRY:
        return ""
    proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout.splitlines():
        say("    " + line)
    if check and proc.returncode != 0:
        fail(f"{cmd[0]} exited with code {proc.returncode}")
    return proc.stdout


def write_file(path, text, mode=0o644, secret=False):
    """Write a file when its content differs. Record that a k3s input changed."""
    global CHANGED
    old = open(path).read() if os.path.exists(path) else None
    if old == text:
        say(f"  {path} is current")
        return
    if old is not None and without_comments(old) == without_comments(text):
        say(f"  {path} is current. Only its comment lines differ.")
        return
    CHANGED = True
    say(f"  write {path}")
    if not secret:
        for line in text.splitlines():
            say(f"    | {line}")
    if DRY:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".root-install-tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def without_comments(text):
    """Return the lines of a TOML or YAML text without its comment lines."""
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


def sha(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def staged(name):
    path = os.path.join(STAGED, name)
    if not os.path.isfile(path):
        fail(f"{path} is missing. Run stage-k3s.sh as {USER} first.")
    return path


def verify():
    me = HOSTS[THIS]
    interface = ["hoover4"] if single(me) else ["wg0"]
    out = subprocess.run(["ip", "-4", "-o", "addr", "show", *interface], stdout=subprocess.PIPE, text=True).stdout
    if f" {address(me)}/" not in out:
        fail(f"{interface[0]} does not have {address(me)}. Use the script of this host, or run root-install-local.py.")
    if me["onprem"] or single(me):
        for path in ["/var/lib/rancher", "/var/lib/kubelet"]:
            if subprocess.run(["findmnt", "-rn", path], stdout=subprocess.DEVNULL).returncode != 0:
                fail(f"{path} is not mounted. Run root-install-{THIS}.py first.")
    sums = open(staged(f"k3s-sha256sum-{arch(me)}.txt")).read()
    binary = "k3s" if arch(me) == "amd64" else "k3s-arm64"
    expected = re.search(rf"(?m)^([0-9a-f]{{64}})\s+{binary}$", sums).group(1)
    checks = [
        ("k3s", sha(staged("k3s")), expected),
        ("install-k3s.sh", sha(staged("install-k3s.sh")), INSTALL_SH_SHA256),
        ("gvisor.tar.zstd", sha(staged("gvisor.tar.zstd"), "sha512"), open(staged("gvisor.tar.zstd.sha512")).read().split()[0]),
    ]
    # A GPU node runs no Kata, and stage-k3s.sh stages Kata for amd64 only.
    if kata(me):
        checks.append(("kata-go-static.tar.zst", sha(staged("kata-go-static.tar.zst")), KATA_SHA256))
    for name, actual, wanted in checks:
        if actual != wanted:
            fail(f"{name} has the digest {actual}, not {wanted}")
        say(f"  {name} is verified")
    token = "server-token" if THIS == SERVER else "agent-token"
    if len(open(staged(token)).read().strip()) < 32:
        fail(f"{token} is too short")


def kata(host):
    return arch(host) == "amd64" and not host.get("gpu")


def gpu(host):
    return bool(host.get("gpu"))


def runsc_nvproxy_toml():
    """The runsc configuration of the GPU handler, with the staged patched binary when it exists."""
    binary = f"{RUNSC_NVPROXY_DIR}/runsc" if os.path.exists(staged("runsc-nvproxy/runsc")) else f"{GVISOR_DIR}/runsc"
    return (f'binary_name = "{binary}"\n'
            "# nvproxy passes the NVIDIA device calls of the sandbox to the host driver.\n"
            "[runsc_config]\n"
            '  systemd-cgroup = "true"\n'
            '  nvproxy = "true"\n'
            '  nvproxy-docker = "true"\n')


def install_gpu_runtime():
    """Check the NVIDIA driver and the container toolkit, and register the runsc-nvproxy handler."""
    code = subprocess.run(["nvidia-smi", "-L"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) \
        if shutil.which("nvidia-smi") else None
    if code is None or code.returncode:
        fail("this GPU node has no working NVIDIA driver: nvidia-smi -L failed. Install the driver, then run the script again.")
    say("  " + code.stdout.strip().splitlines()[0])
    if not shutil.which("nvidia-container-runtime"):
        fail("this GPU node has no nvidia-container-runtime. Install the NVIDIA container toolkit, which gives k3s the "
             "runtime handler nvidia for the runc fallback, then run the script again.")
    if os.path.exists(staged("runsc-nvproxy/runsc")):
        wanted = open(staged("runsc-nvproxy/runsc.sha256")).read().split()[0]
        if sha(staged("runsc-nvproxy/runsc")) != wanted:
            fail("the staged runsc-nvproxy/runsc does not match runsc-nvproxy/runsc.sha256.")
        current = f"{RUNSC_NVPROXY_DIR}/runsc"
        if not os.path.exists(current) or sha(current) != wanted:
            run(["install", "-d", RUNSC_NVPROXY_DIR])
            run(["install", "-m", "755", staged("runsc-nvproxy/runsc"), current])
        say(f"  {current} is the patched runsc build")
    write_file(RUNSC_NVPROXY_CONFIG, runsc_nvproxy_toml())


def install_runtimes():
    version = open(f"{GVISOR_DIR}/VERSION").read().strip() if os.path.exists(f"{GVISOR_DIR}/VERSION") else ""
    gvisor_sum = open(staged("gvisor.tar.zstd.sha512")).read().split()[0]
    if version != gvisor_sum:
        run(["rm", "-rf", GVISOR_DIR])
        run(["install", "-d", GVISOR_DIR])
        run(["tar", "--zstd", "-xf", staged("gvisor.tar.zstd"), "-C", GVISOR_DIR])
        if not DRY:
            open(f"{GVISOR_DIR}/VERSION", "w").write(gvisor_sum + "\n")
    else:
        say(f"  {GVISOR_DIR} is current")
    for name in ["runsc", "containerd-shim-runsc-v1"]:
        link = f"/usr/local/bin/{name}"
        if os.path.realpath(link) != f"{GVISOR_DIR}/{name}":
            run(["ln", "-sfn", f"{GVISOR_DIR}/{name}", link])
    if gpu(HOSTS[THIS]):
        install_gpu_runtime()
        write_file(RUNSC_CONFIG, RUNSC_TOML)
        write_file(CONTAINERD_DROPIN, RUNTIMES_TOML.split("# Kata Containers")[0] + RUNSC_NVPROXY_TOML_FILE)
        return
    if not kata(HOSTS[THIS]):
        write_file(RUNSC_CONFIG, RUNSC_TOML)
        write_file(CONTAINERD_DROPIN, RUNTIMES_TOML.split("# Kata Containers")[0])
        return
    kata_version = open("/opt/kata/VERSION").read().strip() if os.path.exists("/opt/kata/VERSION") else ""
    if kata_version != KATA_VERSION:
        run(["rm", "-rf", "/opt/kata"])
        run(["tar", "--zstd", "-xf", staged("kata-go-static.tar.zst"), "-C", "/", "./opt/kata"])
    else:
        say(f"  /opt/kata is {KATA_VERSION}")
    default = "/opt/kata/share/defaults/kata-containers/configuration-clh.toml"
    text = open(default).read() if not DRY or os.path.exists(default) else ""
    for old, new in KATA_CHANGES:
        if text and old not in text:
            fail(f"{default} has no line {old!r}. Verify the Kata release.")
        text = text.replace(old, new)
    if text:
        write_file(KATA_CONFIG, text)
    write_file(RUNSC_CONFIG, RUNSC_TOML)
    write_file(CONTAINERD_DROPIN, RUNTIMES_TOML)
    if not DRY:
        out = subprocess.run(["/opt/kata/bin/kata-runtime", "--config", KATA_CONFIG, "check", "--no-network-checks"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        say("  kata-runtime check: " + (out.stdout.strip().splitlines() or ["(no output)"])[-1])


def k3s_config():
    me = HOSTS[THIS]
    lines = [
        f"node-name: {THIS}",
        f"node-ip: {address(me)}",
        "flannel-iface: " + ("hoover4" if single(me) else "wg0"),
        "kubelet-arg:",
        "  # One node can hold several zones. A zone has about 50 pods, and the node pod network is a /24.",
        "  - max-pods=250",
        "  # The pods must not use the memory of the system and k3s, because memory is not overcommitted.",
        "  - eviction-hard=memory.available<500Mi,nodefs.available<5%,imagefs.available<5%",
    ]
    if me.get("reserved"):
        lines.insert(-1, f"  - system-reserved={me['reserved']}")
    if gpu(me):
        lines += [
            "# A GPU node runs only the GPU pods, which tolerate this taint.",
            "node-label:",
            f"  - {GPU_LABEL}",
            "node-taint:",
            f"  - {GPU_TAINT}",
        ]
    if single(me):
        lines += [
            "  # k3s and the pods share hoover4.slice, whose limits keep memory for the other services of the host.",
            "  - cgroup-root=/hoover4",
            f"write-kubeconfig: {K3S_DIR}/hoover4-admin.yaml",
        ]
    if THIS == SERVER:
        lines = [
            f"advertise-address: {address(me)}",
            "tls-san:",
            f"  - {address(me)}",
            "flannel-backend: " + ("host-gw" if single(me) else "vxlan"),
            f"token-file: {K3S_DIR}/token",
            f"agent-token-file: {K3S_DIR}/agent-token",
            'write-kubeconfig-mode: "0600"',
            "# The public host runs the frontend. TopoLVM replaces the local-path volumes.",
            "disable:",
            "  - traefik",
            "  - servicelb",
            "  - local-storage",
        ] + lines
    else:
        lines = [f"server: {SERVER_URL}", f"token-file: {K3S_DIR}/agent-token"] + lines
    # The file names the token files and holds no secret. The k3s kubectl reads it as the operator user.
    write_file(f"{K3S_DIR}/config.yaml", "\n".join(lines) + "\n", mode=0o644)
    if THIS == SERVER:
        write_file(f"{K3S_DIR}/token", open(staged("server-token")).read().strip() + "\n", mode=0o600, secret=True)
    write_file(f"{K3S_DIR}/agent-token", open(staged("agent-token")).read().strip() + "\n", mode=0o600, secret=True)


def install_k3s():
    unit = "k3s" if THIS == SERVER else "k3s-agent"
    installed = os.path.exists("/usr/local/bin/k3s") and sha("/usr/local/bin/k3s") == sha(staged("k3s"))
    active = subprocess.run(["systemctl", "is-active", unit], stdout=subprocess.DEVNULL).returncode == 0
    if installed and active and not CHANGED:
        say(f"  k3s {K3S_VERSION} runs as {unit}, and no input changed")
        return unit
    run(["install", "-m", "755", staged("k3s"), "/usr/local/bin/k3s"])
    env = dict(os.environ, INSTALL_K3S_SKIP_DOWNLOAD="true", INSTALL_K3S_SKIP_SELINUX_RPM="true",
               INSTALL_K3S_VERSION=K3S_VERSION, INSTALL_K3S_EXEC="server" if THIS == SERVER else "agent")
    run(["sh", staged("install-k3s.sh")], env=env)
    return unit


def wait_server():
    if DRY:
        return
    deadline = time.time() + 300
    while time.time() < deadline:
        out = subprocess.run(["/usr/local/bin/k3s", "kubectl", "--kubeconfig",
                              f"{K3S_DIR}/hoover4-admin.yaml" if single(HOSTS[THIS]) else f"{K3S_DIR}/k3s.yaml",
                              "get", "node", THIS, "--no-headers"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
        if " Ready " in out:
            say("  " + out.strip())
            break
        time.sleep(5)
    else:
        fail(f"the node {THIS} is not Ready after 300 s. See journalctl -u k3s.")
    user = pwd.getpwnam(USER)
    kube = os.path.join(user.pw_dir, ".kube")
    os.makedirs(kube, exist_ok=True)
    os.chown(kube, user.pw_uid, user.pw_gid)
    source = f"{K3S_DIR}/hoover4-admin.yaml" if single(HOSTS[THIS]) else f"{K3S_DIR}/k3s.yaml"
    target = KUBECONFIG_OUT or f"{kube}/config"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy(source, target)
    os.chown(target, user.pw_uid, user.pw_gid)
    os.chmod(target, 0o600)
    say(f"  copied the admin kubeconfig to {target}")


def main():
    global DRY, STAGED
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show the changes and change nothing")
    parser.add_argument("--staged", help="the folder of the staged files. The default is the folder of the script.")
    parser.add_argument("--hosts", help="the hosts.json form of the site file")
    parser.add_argument("--node", help="the node of this host in --hosts")
    parser.add_argument("--kubeconfig-out", help="the destination of the admin kubeconfig")
    args = parser.parse_args()
    global KUBECONFIG_OUT
    if args.hosts:
        import json
        use_site(json.load(open(args.hosts)), args.node)
    else:
        use_site(SITE, THIS)
    KUBECONFIG_OUT = args.kubeconfig_out
    if THIS is None or THIS not in HOSTS:
        fail("this file has no host. Run write-host-copies.py, then run the copy of this host.")
    if args.staged:
        STAGED = os.path.abspath(os.path.expanduser(args.staged))
    if os.geteuid() != 0:
        fail("run the script as root")
    DRY = args.dry_run
    say(f"== root-install-k3s-{THIS}.py {time.strftime('%Y-%m-%d %H:%M:%S')}{' dry run' if DRY else ''}")
    say("== verify")
    verify()
    say("== runtimes")
    install_runtimes()
    say("== k3s")
    k3s_config()
    unit = install_k3s()
    if THIS == SERVER:
        wait_server()
    elif not DRY:
        time.sleep(10)
        state = subprocess.run(["systemctl", "is-active", unit], stdout=subprocess.PIPE, text=True).stdout.strip()
        say(f"  {unit} is {state}. The server shows the node with: kubectl get nodes")
    say("== done")


if __name__ == "__main__":
    main()
