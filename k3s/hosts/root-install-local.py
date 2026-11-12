#!/usr/bin/env python3
"""Prepare the local Arch-based host of a single-node site for k3s. Run it as root through ../deploy-k3s.

The driver writes the bundle ~<operator>/k3s-install/<revision> with the hosts.json form of the site file
(config.legacy_hosts), and passes the bundle name and the node name. Arguments are names, and the rules of
root-install-k3s.py apply. The private folder of the operator comes from the entry `private` of the local node in
hosts.json. The steps run in this order. Each step reads the state of the host first and skips the work that is already done, so a second run changes
nothing and a run after a failure continues.
  software   Install the missing pacman packages.
  settings   Write the kernel module and sysctl settings, the NetworkManager exception, the dummy link hoover4 with the
             fixed node address, and the slice hoover4.slice that holds k3s and every pod.
  storage    Create the volume group of the node on its physical volumes, and the volumes of /var/lib/rancher and
             /var/lib/kubelet. TopoLVM uses the free space of the volume group.
  dns        Run dnsmasq on the node address. It answers every name below the site suffix with the node address, and
             systemd-resolved sends only those names to it.
  frontend   Install the unit hoover4-frontend, which runs Caddy as the operator user with the Caddyfile of
             ../platform/frontend/install-local-frontend.sh.
  trust      Add the local CA of the frontend to the system trust store.
Commands:
  root-install-local.py --bundle NAME --node NODE [--only STEP ...] [--dry-run]
  root-install-local.py --bundle NAME --node NODE --service start|stop
--dry-run prints the changes and changes nothing. --service starts or stops the units of the site in their order. The
stop also ends the containers of the pods with the kill script of k3s.
"""
import argparse
import json
import os
import pwd
import re
import subprocess
import sys

# A single-node site keeps its dataset folders on claims, so the host needs no NFS client.
PACKAGES = ['lvm2', 'dnsmasq', 'zstd', 'nss', 'curl', 'openssl', 'podman']
MODULES = ['overlay', 'br_netfilter', 'tun', 'vhost_net', 'vhost_vsock', 'dm_thin_pool']
SYSCTL = {
    'net.ipv4.ip_forward': '1',
    'net.bridge.bridge-nf-call-iptables': '1',
    'net.bridge.bridge-nf-call-ip6tables': '1',
    'fs.inotify.max_user_instances': '8192',
    'fs.inotify.max_user_watches': '1048576',
    'vm.max_map_count': '262144',
}
MODULES_FILE = '/etc/modules-load.d/90-hoover4-k3s.conf'
SYSCTL_FILE = '/etc/sysctl.d/90-hoover4-k3s.conf'
NM_FILE = '/etc/NetworkManager/conf.d/90-hoover4-k3s.conf'
NM_TEXT = '[keyfile]\nunmanaged-devices=interface-name:hoover4;interface-name:cni0;interface-name:flannel*;interface-name:veth*\n'
LINK = 'hoover4'
ADDRESS_UNIT = '/etc/systemd/system/hoover4-address.service'
SLICE = '/etc/systemd/system/hoover4.slice'
DNS_CONF = '/etc/hoover4/dnsmasq.conf'
DNS_UNIT = '/etc/systemd/system/hoover4-dns.service'
FRONTEND_UNIT = '/etc/systemd/system/hoover4-frontend.service'
CA_ANCHOR = '/etc/ca-certificates/trust-source/anchors/hoover4-local-ca.crt'
# The k3s data holds the images of openDesk and Hoover. lvextend -r can grow both volumes later.
K3S_VOLUMES = [('rancher', '150G', '/var/lib/rancher'), ('kubelet', '40G', '/var/lib/kubelet')]
FSTAB = '/etc/fstab'
STEPS = ['software', 'settings', 'storage', 'dns', 'frontend', 'trust']

DRY = False
CHANGED = []


def say(text=''):
    print(text, flush=True)


def fail(text):
    say(f'ERROR: {text}')
    sys.exit(1)


def read(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return r.returncode, r.stdout.strip()


def change(cmd, input_text=None):
    say('  $ ' + ' '.join(cmd))
    CHANGED.append(' '.join(cmd))
    if DRY:
        return ''
    r = subprocess.run(cmd, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in r.stdout.splitlines()[-20:]:
        say('    ' + line)
    if r.returncode:
        fail(f'{cmd[0]} exited with code {r.returncode}')
    return r.stdout


def write_file(path, text, mode=0o644):
    """Write a file when its content differs. Return True when it changed."""
    old = open(path).read() if os.path.exists(path) else None
    if old == text:
        say(f'  {path} is current')
        return False
    say(f'  write {path}')
    for line in text.splitlines():
        say(f'    | {line}')
    CHANGED.append(path)
    if DRY:
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.hoover4-tmp'
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), 'w') as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return True


def unit_active(name):
    return read(['systemctl', 'is-active', name])[1] == 'active'


def ensure_unit(name, changed):
    if changed:
        change(['systemctl', 'daemon-reload'])
        change(['systemctl', 'enable', name])
        change(['systemctl', 'restart', name])
    elif not unit_active(name):
        change(['systemctl', 'enable', '--now', name])
    else:
        say(f'  {name} is active')


def memory_gib(text):
    """GiB of a Kubernetes quantity such as 69Gi or 4096Mi."""
    units = {'Gi': 1, 'Mi': 1 / 1024, 'G': 1, 'M': 1 / 1024}
    for suffix, factor in units.items():
        if text.endswith(suffix):
            return float(text[:-len(suffix)]) * factor
    return float(text) / 2 ** 30


def reserved(host):
    values = dict(part.split('=', 1) for part in host.get('reserved', '').split(',') if '=' in part)
    return memory_gib(values.get('memory', '8Gi')), float(values.get('cpu', '2'))


# ----------------------------------------------------------------------------------------------------------------------

def step_software(host, ctx):
    missing = [p for p in PACKAGES if read(['pacman', '-Q', p])[0] != 0]
    if not missing:
        say('  every package is installed')
        return
    change(['pacman', '-S', '--needed', '--noconfirm', *missing])


def step_settings(host, ctx):
    write_file(MODULES_FILE, ''.join(m + '\n' for m in MODULES))
    for module in MODULES:
        if read(['modprobe', '-n', '--first-time', module])[0] == 0:
            change(['modprobe', module])
    if write_file(SYSCTL_FILE, ''.join(f'{k} = {v}\n' for k, v in SYSCTL.items())):
        change(['sysctl', '--load', SYSCTL_FILE])
    if os.path.isdir('/etc/NetworkManager') and write_file(NM_FILE, NM_TEXT):
        change(['systemctl', 'reload', 'NetworkManager'])
    address = host['node_ip']
    unit = f"""[Unit]
Description=The fixed address of the local k3s node on the dummy link {LINK}
Before=k3s.service hoover4-dns.service hoover4-frontend.service
After=network-pre.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'ip link show {LINK} >/dev/null 2>&1 || ip link add {LINK} type dummy'
ExecStart=/bin/sh -c 'ip -4 addr show dev {LINK} | grep -q " {address}/" || ip addr add {address}/32 dev {LINK}'
ExecStart=/usr/bin/ip link set {LINK} up
[Install]
WantedBy=multi-user.target
"""
    ensure_unit('hoover4-address.service', write_file(ADDRESS_UNIT, unit))
    total = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2 ** 30
    memory, cpu = reserved(host)
    limit = int(total - memory)
    cores = os.cpu_count() - cpu
    # The kubelet reserves the same memory (system-reserved), so the pods that it admits fit into this slice.
    # The rest of the host, for example a Compose stack, keeps the reserved memory.
    slice_text = f"""[Unit]
Description=Memory and CPU limits of the local k3s node and its pods
[Slice]
CPUAccounting=yes
MemoryAccounting=yes
CPUQuota={int(cores * 100)}%
MemoryHigh={limit - 2}G
MemoryMax={limit}G
TasksMax=32768
"""
    if write_file(SLICE, slice_text):
        change(['systemctl', 'daemon-reload'])
    # The kubelet needs every controller of the host in the cgroup of its pods. systemd enables only the controllers
    # that it manages, so the unit enables the hugetlb controller for the root and the slice before k3s starts.
    hugetlb = ' '.join(f'echo +hugetlb > /sys/fs/cgroup/{p}cgroup.subtree_control;' for p in ('', 'hoover4.slice/'))
    if write_file('/etc/systemd/system/k3s.service.d/10-hoover4-slice.conf',
               f"[Service]\nSlice=hoover4.slice\nExecStartPre=/bin/sh -c 'grep -qw hugetlb /sys/fs/cgroup/cgroup.controllers || exit 0; {hugetlb}'\n"):
        change(['systemctl', 'daemon-reload'])


def lvm_state(vg):
    code, out = read(['vgs', '--noheadings', '-o', 'vg_name', vg])
    return code == 0


def step_storage(host, ctx):
    vg = host.get('vg')
    devices = host.get('physical_volumes') or []
    if not vg or not devices:
        fail('the node needs lvm_volume_group and lvm_physical_volumes in the site file.')
    for device in devices:
        code, kind = read(['blkid', '-o', 'value', '-s', 'TYPE', device])
        if kind != 'LVM2_member':
            fail(f'{device} is not an LVM physical volume (blkid TYPE {kind or "none"}). '
                 f'Create it with pvcreate after you verify that the device holds no data.')
        code, owner = read(['pvs', '--noheadings', '-o', 'vg_name', device])
        owner = owner.strip()
        if owner and owner != vg:
            fail(f'{device} belongs to the volume group {owner}, not {vg}.')
    if not lvm_state(vg):
        change(['vgcreate', vg, *devices])
    else:
        say(f'  the volume group {vg} exists')
    fstab = open(FSTAB).read()
    for name, size, mount in K3S_VOLUMES:
        device = f'/dev/{vg}/{name}'
        if read(['lvs', '--noheadings', f'{vg}/{name}'])[0] != 0:
            change(['lvcreate', '--yes', '-n', name, '-L', size, vg])
            change(['mkfs.ext4', '-q', '-L', f'hoover4-{name}', device])
        else:
            say(f'  {device} exists')
        line = f'{device} {mount} ext4 defaults,noatime 0 2'
        if line not in fstab.splitlines():
            fstab = fstab.rstrip('\n') + '\n' + line + '\n'
            write_file(FSTAB, fstab)
        if read(['findmnt', '-rn', mount])[0] != 0:
            if os.path.isdir(mount) and os.listdir(mount):
                # The earlier content moves into the volume, so the mount hides no file.
                change(['mkdir', '-p', f'/run/hoover4-{name}'])
                change(['mount', device, f'/run/hoover4-{name}'])
                change(['cp', '-a', f'{mount}/.', f'/run/hoover4-{name}/'])
                change(['umount', f'/run/hoover4-{name}'])
            change(['mkdir', '-p', mount])
            change(['systemctl', 'daemon-reload'])
            change(['mount', mount])
        else:
            say(f'  {mount} is mounted')


def step_dns(host, ctx):
    address, suffix = host['node_ip'], ctx['suffix']
    conf = f"""# The local DNS server of the single-node site. It answers only the names below {suffix}.
listen-address={address}
bind-interfaces
no-resolv
no-hosts
no-poll
local=/{suffix}/
address=/{suffix}/{address}
log-facility=-
"""
    unit = f"""[Unit]
Description=DNS server for the names below {suffix}
Requires=hoover4-address.service
After=hoover4-address.service network.target
[Service]
ExecStart=/usr/bin/dnsmasq --keep-in-foreground --conf-file={DNS_CONF} --pid-file=
ExecStartPost=/usr/bin/resolvectl dns {LINK} {address}
ExecStartPost=/usr/bin/resolvectl domain {LINK} ~{suffix}
Restart=on-failure
[Install]
WantedBy=multi-user.target
"""
    changed = write_file(DNS_CONF, conf)
    changed = write_file(DNS_UNIT, unit) or changed
    ensure_unit('hoover4-dns.service', changed)


def step_frontend(host, ctx):
    operator, private = ctx['operator'], ctx['private']
    user = pwd.getpwnam(operator)
    unit = f"""[Unit]
Description=HTTPS frontend of the local k3s site
Requires=hoover4-address.service
After=hoover4-address.service k3s.service
[Service]
User={operator}
AmbientCapabilities=CAP_NET_BIND_SERVICE
Environment=HOME={user.pw_dir}
ExecStart={private}/bin/caddy run --config {private}/frontend/Caddyfile --adapter caddyfile
ExecReload={private}/bin/caddy reload --config {private}/frontend/Caddyfile --adapter caddyfile
Restart=on-failure
[Install]
WantedBy=multi-user.target
"""
    if not os.path.isfile(f'{private}/frontend/Caddyfile'):
        fail(f'{private}/frontend/Caddyfile is missing. Run platform/frontend/install-local-frontend.sh first.')
    ensure_unit('hoover4-frontend.service', write_file(FRONTEND_UNIT, unit))


def step_trust(host, ctx):
    ca = f"{ctx['private']}/frontend/local-ca.crt"
    if not os.path.isfile(ca):
        fail(f'{ca} is missing. The frontend writes it at its first start.')
    if write_file(CA_ANCHOR, open(ca).read()):
        change(['update-ca-trust'])


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


# The units of a single-node site in their start order. A stop runs in the reverse order of the units that k3s needs.
START_UNITS = ('hoover4-address.service', 'hoover4-dns.service', 'k3s.service', 'hoover4-frontend.service')
STOP_UNITS = ('hoover4-frontend.service', 'k3s.service')


def service(action):
    """Start or stop the units of the site. The pods reach the zone names through the frontend, so it starts with k3s."""
    for unit in START_UNITS if action == 'start' else STOP_UNITS:
        say(f'  $ systemctl {action} {unit}')
        if not DRY:
            subprocess.run(['systemctl', action, unit], check=True)
    # The containers of the pods keep running after the k3s unit stops. The kill script of k3s stops them.
    if action == 'stop' and not DRY and os.path.exists('/usr/local/bin/k3s-killall.sh'):
        subprocess.run(['/usr/local/bin/k3s-killall.sh'], stdout=subprocess.DEVNULL, check=False)
        # The kill script misses the gVisor shims and sandboxes, which keep volumes mounted in their namespaces.
        for pattern in ('^/opt/gvisor/', '^runsc-'):
            subprocess.run(['pkill', '-KILL', '-f', pattern], check=False)


def main():
    global DRY
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bundle', required=True, help='the bundle ~<operator>/k3s-install/NAME of the driver')
    parser.add_argument('--node', required=True)
    parser.add_argument('--only', nargs='+', choices=STEPS)
    parser.add_argument('--operator', help='the operator user of a root run without sudo')
    parser.add_argument('--service', choices=('start', 'stop'), help='start or stop the units of the site')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        fail('run the script as root')
    user = operator_user(args.operator)
    site = json.load(open(below(install_folder(user, args.bundle), 'hosts.json')))
    host = site['hosts'].get(name_arg(args.node, 'node'))
    if host is None or not host.get('local') or not host.get('single'):
        fail(f'{args.node} is not the local node of a single-node site.')
    DRY = args.dry_run
    if args.service:
        service(args.service)
        return
    if not str(host.get('private') or '').startswith('/'):
        fail('the local node in hosts.json has no private folder. Write the bundle with the driver again.')
    for step in args.only or STEPS:
        say(f'== {step}')
        ctx = {'operator': user.pw_name, 'private': host['private'], 'suffix': site['suffix']}
        globals()[f'step_{step}'](host, ctx)
    say(f'== done, {len(CHANGED)} changes{" planned" if DRY else ""}')


if __name__ == '__main__':
    main()
