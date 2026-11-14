#!/usr/bin/python3
"""Write a WireGuard interface of a hoover4 node when it is missing, and add its direct peers. An Ansible module.

Without the interface file /etc/wireguard/<interface>.conf, the module writes one with a new private key, the address
and the listen port, and starts the unit wg-quick@<interface>. The result names the new public key, which the site file
needs. An existing interface must be up and hold public_key. The module sets ListenPort, adds a [Peer] section for
each peer whose key the file does not have, and adds the missing routed addresses to the AllowedIPs of the peers. It
removes no peer and no address, so the other peers and routes of the interface stay unchanged. The new file is
checked with wg-quick strip and applied with wg syncconf before it replaces the interface file. A refused file
changes nothing. The private key never reaches the output.
"""
import os
import re
import shutil
import subprocess
import tempfile

from ansible.module_utils.basic import AnsibleModule

KEEPALIVE = 21


def set_listen_port(lines, port, fail):
    lines = list(lines)
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == '[interface]'), None)
    if start is None:
        fail('the interface file has no [Interface] section')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith('[')), len(lines))
    wanted = f'ListenPort = {port}'
    for i in range(start + 1, end):
        if re.match(r'\s*ListenPort\s*=', lines[i], re.I):
            lines[i] = wanted
            return lines
    lines.insert(start + 1, wanted)
    return lines


def widen_allowed_ips(lines, peers):
    """Add the missing addresses to the AllowedIPs of the peers in the file. Remove no address."""
    by_key = {p['key']: p for p in peers}
    lines = list(lines)
    peer = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('['):
            peer = None
        found = re.match(r'PublicKey\s*=\s*(\S+)', stripped, re.I)
        if found:
            peer = by_key.get(found.group(1))
        allowed = re.match(r'(\s*AllowedIPs\s*=\s*)(.*)', line, re.I)
        if allowed and peer:
            present = [a.strip() for a in allowed.group(2).split(',') if a.strip()]
            missing = [a for a in peer['allowed_ips'] if a not in present]
            if missing:
                lines[i] = allowed.group(1) + ', '.join(present + missing)
    return lines


def peer_blocks(text, peers):
    present = set(re.findall(r'^\s*PublicKey\s*=\s*(\S+)', text, re.M | re.I))
    blocks = []
    for peer in peers:
        if peer['key'] in present:
            continue
        blocks += ['', f'# Direct peer {peer["name"]}, added by hoover4', '[Peer]', f'PublicKey = {peer["key"]}']
        if peer.get('endpoint'):
            blocks.append(f'Endpoint = {peer["endpoint"]}')
        blocks += [f'AllowedIPs = {", ".join(peer["allowed_ips"])}', f'PersistentKeepalive = {KEEPALIVE}']
    return blocks


def interface_text(private_key, address, port):
    """The text of a new interface file."""
    return '\n'.join(['# Written by hoover4. The installer adds the peers of the site file.', '[Interface]',
                      f'PrivateKey = {private_key}', f'Address = {address}', f'ListenPort = {port}']) + '\n'


def create(module, interface, conf):
    """Write the interface file with a new key and start its unit. Return the new public key."""
    p = module.params
    if not p['address']:
        module.fail_json(msg=f'{conf} does not exist, and the module has no address for a new interface.')
    if module.check_mode:
        module.exit_json(changed=True, created=True, public_key='', added=[f'new interface {interface}'])
    code, private, err = module.run_command(['wg', 'genkey'])
    if code:
        module.fail_json(msg=f'wg genkey failed: {err.strip()[-300:]}')
    code, public, err = module.run_command(['wg', 'pubkey'], data=private.strip())
    if code:
        module.fail_json(msg=f'wg pubkey failed: {err.strip()[-300:]}')
    os.makedirs('/etc/wireguard', mode=0o700, exist_ok=True)
    with open(os.open(conf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        f.write(interface_text(private.strip(), p['address'], p['listen_port']))
    code, _, err = module.run_command(['systemctl', 'enable', '--now', f'wg-quick@{interface}'])
    if code:
        module.fail_json(msg=f'wg-quick@{interface} did not start: {err.strip()[-300:]}. {conf} stays for the next run.')
    return public.strip()


def main():
    module = AnsibleModule(argument_spec={
        'interface': {'type': 'str', 'required': True},
        'address': {'type': 'str', 'default': ''},
        'listen_port': {'type': 'int', 'required': True},
        'public_key': {'type': 'str', 'default': ''},
        'peers': {'type': 'list', 'elements': 'dict', 'default': []},
    }, supports_check_mode=True)
    p = module.params
    interface = p['interface']
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', interface):
        module.fail_json(msg=f'{interface!r} is not an interface name')
    conf = f'/etc/wireguard/{interface}.conf'
    created = False
    if not os.path.exists(conf):
        created_key = create(module, interface, conf)
        created = True
    code, key, _ = module.run_command(['wg', 'show', interface, 'public-key'])
    if code:
        module.fail_json(msg=f'{interface} is not up. Start the interface of the VPN, then run the play again.')
    key = key.strip()
    if created:
        if p['public_key'] and key != p['public_key']:
            module.fail_json(msg=f'the new interface {interface} has the public key {created_key}, and the site file '
                                 f'names {p["public_key"]}. Set the new key in the site file.')
    elif p['public_key'] and key != p['public_key']:
        module.fail_json(msg=f'the public key of {interface} is {key}, not the public_key of the site file.')
    if not p['public_key']:
        # The site file does not have the key yet, so no other node has a peer for this node. Add no peer.
        module.exit_json(changed=created, created=created, public_key=key)
    peers = [x for x in p['peers'] if x.get('key') and x.get('allowed_ips')]
    text = open(conf).read()
    lines = text.splitlines()
    new = widen_allowed_ips(set_listen_port(lines, p['listen_port'], lambda m: module.fail_json(msg=m)), peers)
    new += peer_blocks(text, peers)
    if new == lines:
        module.exit_json(changed=created, created=created, public_key=key, msg=f'{conf} has the listen port and every peer')
    shown = [line for line in new if line not in lines and not re.match(r'\s*PrivateKey', line, re.I)]
    if module.check_mode:
        module.exit_json(changed=True, created=created, public_key=key, added=shown)
    folder = tempfile.mkdtemp(dir='/run', prefix='hoover4-wg-')
    try:
        candidate = os.path.join(folder, f'{interface}.conf')
        with open(os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
            f.write('\n'.join(new) + '\n')
        code, stripped, err = module.run_command(['wg-quick', 'strip', candidate])
        if code:
            module.fail_json(msg=f'wg-quick strip refused the new {conf}: {err.strip()[-300:]}. {conf} is unchanged.')
        plain = os.path.join(folder, 'stripped.conf')
        with open(os.open(plain, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
            f.write(stripped)
        # syncconf changes the peers and the port of the running interface and keeps the other peers up.
        code, _, err = module.run_command(['wg', 'syncconf', interface, plain])
        if code:
            module.fail_json(msg=f'wg syncconf refused the new {conf}: {err.strip()[-300:]}. {conf} is unchanged.')
        if not os.path.exists(conf + '.before-root-install'):
            shutil.copy2(conf, conf + '.before-root-install')
            os.chmod(conf + '.before-root-install', 0o600)
        tmp = conf + '.hoover4-tmp'
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
            f.write('\n'.join(new) + '\n')
        os.replace(tmp, conf)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    module.exit_json(changed=True, created=created, public_key=key, added=shown)


if __name__ == '__main__':
    main()
