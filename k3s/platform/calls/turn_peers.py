"""The peers that coturn may relay to, and the check of the host rule that limits the public peer.

coturn relays UDP only (no-tcp-relay). Every store of a zone serves TCP, so a TURN user cannot reach a store through
coturn. The UDP peers are the pod addresses of the media node, where the JVB runs, and the public address of the media
node when it has one. The pod address of the bridge cni0, the network address and the broadcast address of
the pod range of the node are no peers, so coturn does not relay to the node itself through the bridge. Every other
address is denied, also the pods of the other nodes.
A media node without a public address advertises the pod address of the JVB. The Jitsi bridge connection uses coturn to
reach the JVB pod address (../../zones/postrender.py), also on a node with a public address.
The retired LiveKit SFU offered the public address to the clients, so coturn may relay to it. coturn can allow a peer
address but not a port. The chain coturn_peers of
../../ansible/roles/hoover4_public_firewall/files/coturn-peers.sh on the media node therefore drops every packet of
the coturn user, COTURN_UID, to the public address of the node. The hook of that chain runs before the DNAT of the host
ports, so it sees the public address.
The calls step adds the public peer only after a probe pod on the media node shows the rule: in the host network, a
connection of the coturn user to the public address on PROBE_PORT is dropped, and the same connection of another user
reaches the port. The admin kubeconfig runs the probe and records its result (install-calls.py --probe). Without a
record for the media node and its public address the step stops with a message.
The pod admission policy of the calls namespace refuses a privileged container and the host process namespace, so the
rule is a host rule and not a part of the coturn pod.
"""
import ipaddress

# The user id of the coturn process. No other process of the media node uses it. public-firewall.sh names the same value.
COTURN_UID = 64981
# The probe port: the kubelet listens on it on every address of every k3s node, and the chain coturn_peers drops it.
PROBE_PORT = 10250
# The user of the control connection of the probe.
PROBE_CONTROL_UID = 65534


def peer_lines(node_pods, public):
    """The coturn lines of the relay peers. node_pods is the pod range of the media node, public its public address."""
    network = ipaddress.ip_network(node_pods)
    lines = ['no-tcp-relay', 'denied-peer-ip=0.0.0.0-255.255.255.255',
             'denied-peer-ip=::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff',
             f'allowed-peer-ip={network[2]}-{network[-2]}']
    if public:
        lines.append(f'allowed-peer-ip={public}')
    return lines


# The probe: one connection to the address on the port. open: the connection or a refusal reached the port. blocked: a
# host rule dropped it (EPERM for a local packet, or a timeout).
PROBE = r"""
import socket, sys
s = socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET)
s.settimeout(5)
try:
    s.connect((sys.argv[1], int(sys.argv[2])))
    print('open')
except ConnectionRefusedError:
    print('open')
except (PermissionError, socket.timeout):
    print('blocked')
except OSError as error:
    print('error', error)
"""


# The PriorityClass of the pods that can run on one node only (../../cluster/priorityclasses.yaml).
NODE_BOUND = 'hoover-node-bound'


def probe_pod(namespace, node, address, image, security):
    """The pod that checks the chain coturn_peers on node: one container as the coturn user, one as another user.

    The pod must run on the media node. It requests little memory and has the PriorityClass NODE_BOUND. On a full
    media node it therefore preempts a pod of the default priority, and the calls step continues.
    """
    def container(name, uid):
        return {'name': name, 'image': image, 'command': ['python3', '-c', PROBE, address, str(PROBE_PORT)],
                'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '100m', 'memory': '64Mi'}},
                'securityContext': {**security, 'runAsUser': uid, 'runAsGroup': uid}}
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'coturn-peer-check', 'namespace': namespace},
            'spec': {'restartPolicy': 'Never', 'hostNetwork': True, 'automountServiceAccountToken': False,
                     'enableServiceLinks': False, 'nodeSelector': {'kubernetes.io/hostname': node},
                     'priorityClassName': NODE_BOUND,
                     'containers': [container('coturn', COTURN_UID), container('control', PROBE_CONTROL_UID)]}}


def chain_problem(node, address, coturn, control):
    """Empty when the probe results show the chain coturn_peers for address on node, else the message of the step."""
    if coturn.strip() == 'blocked' and control.strip() == 'open':
        return ''
    if control.strip() != 'open':
        return (f'the calls step cannot verify the host rule of {node}: a connection to {address}:{PROBE_PORT} '
                f'from the host network gave "{control.strip()}". The kubelet must answer on that address.')
    return (f'the media node {node} has no host rule coturn_peers for its public address {address}, so coturn could '
            f'relay to every port of that address. Run the host play with the role hoover4_public_firewall on {node}, '
            'then run the calls step again.')
