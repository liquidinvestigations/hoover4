"""The peers that coturn may relay to.

coturn relays only to the pod range of the cluster. When the media node has a public address, LiveKit offers that
address to the clients, so a client that can only use TURN needs coturn to relay to it. coturn can allow a peer
address but not a port. The table of ../../hosts/root-install-public-firewall.sh on the media node therefore drops
every packet of the coturn user, COTURN_UID, to the public address of the node, except to the LiveKit media ports.
The hook of that chain runs before the DNAT of the LiveKit host ports, so it sees the public address.
The pod admission policy of the calls namespace refuses a privileged container and the host process namespace, so the
rule is a host rule and not a part of the coturn pod.
"""

# The user id of the coturn process. No other process of the media node uses it. root-install-public-firewall.sh
# names the same value.
COTURN_UID = 64981
# The media ports that LiveKit publishes as host ports of the media node (install-calls.py).
LIVEKIT_TCP = 7881
LIVEKIT_UDP = 7882


def peer_lines(pods, public):
    """The coturn lines of the allowed peers: the pod range, and the public address of the media node when it has one."""
    lines = ['denied-peer-ip=0.0.0.0-255.255.255.255', f'allowed-peer-ip={pods}']
    if public:
        lines.append(f'allowed-peer-ip={public}')
    return lines
