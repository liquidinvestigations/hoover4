"""The peers that coturn may relay to, and the host rule that limits the public address to the LiveKit media ports.

coturn relays only to the pod range of the cluster. When the media node has a public address, LiveKit offers that
address to the clients, so a client that can only use TURN needs coturn to relay to it. coturn can allow a peer
address but not a port, so a host rule limits that address to the LiveKit media ports:
- coturn runs with its own user id, COTURN_UID.
- An init container of the coturn pod writes the chain HOOVER4-COTURN into the raw table of the host. The raw table
  sees the public address before the host port DNAT of LiveKit rewrites it.
- The OUTPUT chain of the raw table sends the packets of COTURN_UID to the public address through that chain. The
  chain lets the LiveKit media ports pass and drops every other packet.
The init container runs at each start of the pod, so the rule comes back after a reboot of the node.
"""
import shlex

# The user id of the coturn process. No other process of the media node uses it.
COTURN_UID = 64981
# The media ports that LiveKit publishes as host ports of the media node (install-calls.py).
LIVEKIT_TCP = 7881
LIVEKIT_UDP = 7882
CHAIN = 'HOOVER4-COTURN'


def peer_lines(pods, public):
    """The coturn lines of the allowed peers: the pod range, and the public address of the media node when it has one."""
    lines = ['denied-peer-ip=0.0.0.0-255.255.255.255', f'allowed-peer-ip={pods}']
    if public:
        lines.append(f'allowed-peer-ip={public}')
    return lines


def guard_script(public):
    """The host shell script that writes the chain and the jump to it. A second run gives the same rules."""
    rules = '\n'.join([
        '*raw',
        f':{CHAIN} - [0:0]',
        f'-A {CHAIN} -p udp --dport {LIVEKIT_UDP} -j RETURN',
        f'-A {CHAIN} -p tcp --dport {LIVEKIT_TCP} -j RETURN',
        f'-A {CHAIN} -j DROP',
        'COMMIT', ''])
    jump = f'OUTPUT -d {public}/32 -m owner --uid-owner {COTURN_UID} -j {CHAIN}'
    # iptables-restore --noflush replaces the chain that the input names in one step and keeps the other chains.
    return '\n'.join([
        'set -eu',
        f'printf %s {shlex.quote(rules)} | iptables-restore --noflush',
        f'iptables -t raw -C {jump} 2>/dev/null || iptables -t raw -I {jump}',
        f'iptables -t raw -S {CHAIN}'])


def guard_container(image, public):
    """The privileged init container that runs guard_script in the network and mount namespaces of the host."""
    return {'name': 'peer-guard', 'image': image,
            'command': ['nsenter', '-t', '1', '-m', '-n', '--', 'sh', '-c', guard_script(public)],
            'securityContext': {'privileged': True},
            'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '200m', 'memory': '64Mi'}}}
