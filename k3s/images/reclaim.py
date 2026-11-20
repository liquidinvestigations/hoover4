"""Find and remove the images of the retired applications on the nodes and in the site registry. Standard library only.

deploy-k3s reset (../driver/reset.py) runs inventory() before it removes the zone workloads, and reclaim() after.
An image is retired when every reference of it names a retired repository (../zones/applications.py: the retired
images of the pinned openDesk release, the repositories of earlier releases and of LiveKit, and the images of the pods
of retired workloads in the inventory). A retained repository of the pinned release never counts as retired.
- A retired image that no container of the node uses loses every reference (crictl rmi of its id). containerd then
  removes the content that no other image references, so a layer that a retained image shares stays.
- An image with retired and other references (an alias or a shared digest) keeps the image and its other
  references. Only the retired references go (ctr images rm).
- An image that a container uses stays, and the result names it.
Each node reports the used bytes of its file system of /var/lib/rancher and the bytes of the content store of
containerd before and after, and the sum of the sizes that crictl reports for the removed images. crictl counts a
shared layer in each image, so only the change of the content store measures the reclaimed space.
A node that does not run the command pod (../driver/nodepod.py) stays in the result as unreachable, and a resume runs
it again.
The site registry holds only images that the deployment builds (registry.hoover.internal/hoover/*). A repository of
the registry that names a retired image loses its manifests, and the garbage collection of the registry removes the
blobs that no other manifest references.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'zones'))
sys.path.insert(0, str(HERE.parent / 'driver'))
import applications  # noqa: E402
import nodepod  # noqa: E402

CONTENT = '/var/lib/rancher/k3s/agent/containerd/io.containerd.content.v1.content'
SPLIT = '----hoover-split----'
INVENTORY = (f'k3s crictl images -o json; echo {SPLIT}; k3s crictl ps -a -o json; echo {SPLIT}; '
             f'df -B1 --output=used /var/lib/rancher | tail -1; echo {SPLIT}; du -sb {CONTENT} | cut -f1')
MEASURE = f'df -B1 --output=used /var/lib/rancher | tail -1; echo {SPLIT}; du -sb {CONTENT} | cut -f1'
REGISTRY_NAMESPACE = 'registry'
REGISTRY_CONFIG = '/etc/distribution/config.yml'


def repository(reference):
    """The repository of an image reference, without the tag and the digest."""
    name = reference.split('@', 1)[0]
    last = name.rsplit('/', 1)[-1]
    return name.rsplit(':', 1)[0] if ':' in last else name


def parse_node(text):
    """(images, used image ids, used bytes, content bytes) of the INVENTORY output of a node."""
    parts = text.split(SPLIT)
    images = json.loads(parts[0]).get('images') or []
    containers = json.loads(parts[1]).get('containers') or []
    used = {c.get('imageRef') for c in containers} | {(c.get('image') or {}).get('image') for c in containers}
    numbers = [int(p.strip() or 0) for p in parts[2:4]]
    return images, used, numbers[0], numbers[1]


def parse_removal(text):
    """(report, used bytes, content bytes) of the output of the removal script and MEASURE: the report, then the two
    numbers, each part after a split mark."""
    parts = text.split(SPLIT)
    if len(parts) != 3:
        raise ValueError(f'the removal output has {len(parts) - 1} split marks, not 2')
    return parts[0], int(parts[1].strip() or 0), int(parts[2].strip() or 0)


def classify(images, used, retired_repositories, retained_repositories):
    """{'remove': [...], 'aliases': [...], 'in_use': [...], 'kept': n} of the images of a node.

    remove: retired images without another reference, {'id', 'references', 'size'}. aliases: images with retired and
    other references, {'id', 'retired', 'kept'}. in_use: retired images that a container of the node uses."""
    out = {'remove': [], 'aliases': [], 'in_use': [], 'kept': 0}
    for image in images:
        refs = list(image.get('repoTags') or []) + list(image.get('repoDigests') or [])
        retired = [r for r in refs if retired_repository(repository(r), retired_repositories, retained_repositories)]
        if not retired:
            out['kept'] += 1
            continue
        other = [r for r in refs if r not in retired]
        entry = {'id': image['id'], 'references': sorted(refs), 'size': int(image.get('size') or 0)}
        if image['id'] in used or any(r in used for r in refs):
            out['in_use'].append(entry)
        elif other:
            out['aliases'].append({'id': image['id'], 'retired': sorted(retired), 'kept': sorted(other)})
        else:
            out['remove'].append(entry)
    return out


def retired_repository(name, retired_repositories, retained_repositories):
    if name in retained_repositories:
        return False
    return name in retired_repositories or applications.retired_repository(name, retained_repositories)


def pod_repositories(pods):
    """(retired, retained) repositories of the images of the pods: a pod of a retired workload names a retired one."""
    retired, retained = set(), set()
    for pod in pods:
        owners = [o.get('name', '') for o in pod['metadata'].get('ownerReferences') or []]
        names = [pod['metadata']['name']] + owners
        target = retired if any(applications.retired_part(n) for n in names) else retained
        spec = pod.get('spec') or {}
        for c in (spec.get('containers') or []) + (spec.get('initContainers') or []):
            target.add(repository(c['image']))
    return retired - retained, retained


def repositories(opendesk, pods):
    """(retired, retained) repositories from the pinned release and the pods of the inventory."""
    pinned = applications.repositories(opendesk) if opendesk and Path(opendesk).exists() else {'retired': set(), 'retained': set()}
    from_pods, live = pod_repositories(pods)
    retained = pinned['retained'] | {r for r in live if not applications.retired_repository(r)}
    return sorted((pinned['retired'] | from_pods) - retained), sorted(retained)


def node_inventory(kubeconfig, node, retired, retained):
    images, used, used_bytes, content = parse_node(nodepod.run(kubeconfig, node, INVENTORY))
    found = classify(images, used, set(retired), set(retained))
    return {'images': len(images), 'used_bytes': used_bytes, 'content_bytes': content, **found}


def inventory(kubeconfig, nodes, opendesk, pods):
    """The images of every node and the registry before the removal of the zone workloads. A node that does not
    answer is named in unreachable."""
    retired, retained = repositories(opendesk, pods)
    out = {'retired_repositories': retired, 'retained_repositories': retained, 'nodes': {}, 'unreachable': {}}
    for node in nodes:
        try:
            out['nodes'][node] = node_inventory(kubeconfig, node, retired, retained)
        except (nodepod.Unreachable, nodepod.Failed, RuntimeError, ValueError) as error:
            out['unreachable'][node] = str(error)[:300]
    return out


def remove_script(found):
    """The shell lines that remove the retired images and the retired references of a node."""
    lines = []
    for image in found['remove']:
        lines.append(f'k3s crictl rmi {image["id"]} || echo "failed {image["id"]}"')
    for alias in found['aliases']:
        refs = ' '.join(alias['retired'])
        lines.append(f'k3s ctr -n k8s.io images rm {refs} || echo "failed {alias["id"]}"')
    return '\n'.join(lines) or 'true'


def reclaim(kubeconfig, nodes, retired, retained):
    """Remove the retired images on each node with a new inventory, so an image that a resume removed before counts as
    gone. Return {'nodes': {node: result}, 'unreachable': {node: message}}."""
    out = {'nodes': {}, 'unreachable': {}}
    for node in nodes:
        try:
            images, used, used_before, content_before = parse_node(nodepod.run(kubeconfig, node, INVENTORY))
            found = classify(images, used, set(retired), set(retained))
            text = nodepod.run(kubeconfig, node, remove_script(found) + f'\necho {SPLIT}\n' + MEASURE)
            report, used_after, content_after = parse_removal(text)
            failed = re.findall(r'failed (sha256:[0-9a-f]+)', report)
            out['nodes'][node] = {
                'removed_images': len(found['remove']) - len(failed),
                'removed_aliases': len(found['aliases']),
                'reported_bytes': sum(i['size'] for i in found['remove'] if i['id'] not in failed),
                'in_use': found['in_use'], 'failed': failed,
                'used_bytes': {'before': used_before, 'after': used_after},
                'content_bytes': {'before': content_before, 'after': content_after,
                                  'reclaimed': max(0, content_before - content_after)}}
        except (nodepod.Unreachable, nodepod.Failed, RuntimeError, ValueError) as error:
            out['unreachable'][node] = str(error)[:300]
    return out


def remaining(kubeconfig, nodes, retired, retained):
    """{node: [ids]} of the retired images that a node still has, without the images that a container uses."""
    out = {}
    for node in nodes:
        images, used, _, _ = parse_node(nodepod.run(kubeconfig, node, INVENTORY))
        found = classify(images, used, set(retired), set(retained))
        ids = [i['id'] for i in found['remove']] + [a['id'] for a in found['aliases']]
        if ids:
            out[node] = ids
    return out


def registry_repositories(catalog, retained):
    """The repositories of the site registry that name a retired image."""
    return sorted(r for r in catalog if applications.retired_repository(r, retained) or
                  applications.retired_repository('registry.hoover.internal/' + r, retained))
