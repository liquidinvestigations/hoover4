#!/usr/bin/env python3
"""Build the Hoover images of compose.IMAGES from one commit of this repository and push them to the cluster registry.

The script exports the commit with `git archive` into k3s/private/build/<commit>, so local changes of the checkout
stay unchanged and stay out of the images. The image tag is the first 12 characters of the commit.
../hoover/manifests.py names the images with the same tag (image_tag()).
The website image is the release Dockerfile. The processing image starts the installed interpreter.
Usage: build-hoover.py [--revision REV] [name ...]    Without names it builds every image of compose.IMAGES.
                                                      The default revision is HEAD.
       build-hoover.py --gpu [--revision REV] [--builder NODE] [name ...]
                                                      Builds the images of compose.GPU_IMAGES for the architecture
                                                      of the GPU nodes of the site file. The model server image gets
                                                      the base image of deploy.py (QWEN_FLASH_BASE_IMAGE).
                                                      --builder builds on a node of that architecture over SSH: the
                                                      tree of the commit goes to ~/hoover4-build/<commit> of the node,
                                                      the node builds with its Docker or Podman, and the image comes
                                                      back with save and load. This host then pushes it.
A run inside an exported tree (deploy-k3s runs the tree of its commit) needs no git: the stamp of the tree names the
commit.
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'hoover'))
import settings  # noqa: E402
import compose  # noqa: E402
IMAGES = compose.IMAGES


def commit(revision):
    stamp = Path(settings.HOOVER4) / '.hoover-build-commit'
    if stamp.exists():
        # An exported tree builds its own commit only.
        tree = stamp.read_text().strip()
        if revision not in (tree, 'HEAD'):
            raise SystemExit(f'this tree holds {tree}, not {revision}')
        return tree
    out = subprocess.run(['git', '-C', str(settings.HOOVER4), 'rev-parse', '--verify', f'{revision}^{{commit}}'],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f'{revision} is not a commit of {settings.HOOVER4}')
    return out.stdout.strip()


def prepare(sha):
    """Write the source tree of one commit once. A tree with the expected stamp stays."""
    tree = settings.PRIVATE / 'build' / sha
    stamp = tree / '.hoover-build-commit'
    if stamp.exists() and stamp.read_text().strip() == sha:
        return tree
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True)
    archive = subprocess.Popen(['git', '-C', str(settings.HOOVER4), 'archive', sha], stdout=subprocess.PIPE)
    subprocess.run(['tar', '-x', '-C', str(tree)], stdin=archive.stdout, check=True)
    if archive.wait():
        raise SystemExit(f'git archive of {sha} failed')
    stamp.write_text(sha)
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # ../deploy-k3s resolves the revision once per deployment and passes it in HOOVER4_REVISION.
    parser.add_argument('--revision', default=__import__('os').environ.get('HOOVER4_REVISION') or 'HEAD')
    parser.add_argument('--gpu', action='store_true', help='build the GPU images of compose.GPU_IMAGES')
    parser.add_argument('--builder', help='a node of the site file that builds the GPU images over SSH')
    parser.add_argument('names', nargs='*')
    args = parser.parse_args()
    sha = commit(args.revision)
    tree = prepare(sha)
    images = compose.GPU_IMAGES if args.gpu else IMAGES
    env = dict(__import__('os').environ)
    if args.gpu:
        site = settings.SITE
        nodes = [n for n in site.nodes.values() if n.has('gpu')] if site else []
        if not nodes:
            raise SystemExit('the site file has no node with the role gpu.')
        architectures = {n.architecture for n in nodes}
        if len(architectures) > 1:
            raise SystemExit(f'the GPU nodes have the architectures {sorted(architectures)}. Build each architecture on its own site.')
        env['PLATFORM'] = f'linux/{architectures.pop()}'
        deploy = compose.deploy_module(tree)
        base = deploy.QWEN_FLASH_BASE_IMAGE
    for name in args.names or list(images):
        dockerfile, context = images[name]
        step_env = dict(env)
        if args.gpu and name == 'vllm' and base:
            step_env['BUILD_ARGS'] = f'BASE_IMAGE={base}'
        if args.builder:
            remote_build(settings.SITE.nodes[args.builder], tree, sha, name, context, dockerfile, step_env)
        subprocess.run(['bash', str(HERE / 'build-image.sh'), str(tree / context), f'hoover/hoover-{name}:{sha[:12]}',
                        str(tree / dockerfile)], check=True, env=step_env)
    print(sha)


def remote_build(node, tree, sha, name, context, dockerfile, env):
    """Build one image on a node over SSH and load it into the local Podman store, unless the registry has it.

    build-image.sh then finds the local image and pushes it without a build.
    """
    local_name = f'registry.hoover.internal/hoover/hoover-{name}:{sha[:12]}'
    endpoint = settings.HOST['registry_endpoint']
    present = subprocess.run(['curl', '-fs', '-o', '/dev/null', '-I', '-H',
                              'Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json',
                              f'http://{endpoint}/v2/hoover/hoover-{name}/manifests/{sha[:12]}']).returncode == 0
    if present or subprocess.run(['podman', 'image', 'exists', local_name]).returncode == 0:
        return
    ssh = ['ssh', '-o', 'BatchMode=yes', node.ssh_address, '--']
    folder = f'hoover4-build/{sha}'
    if subprocess.run(ssh + [f'test -f {folder}/.hoover-build-commit']).returncode:
        pack = subprocess.Popen(['tar', '-C', str(tree), '--exclude=./k3s/private', '-cf', '-', '.'], stdout=subprocess.PIPE)
        subprocess.run(ssh + [f'mkdir -p {folder}.partial && tar -C {folder}.partial -xf - && mv {folder}.partial {folder}'],
                       stdin=pack.stdout, check=True)
        pack.stdout.close()
        if pack.wait():
            raise SystemExit(f'the copy of the tree to {node.name} failed')
    args = ' '.join(f'--build-arg {shlex.quote(a)}' for a in env.get('BUILD_ARGS', '').split())
    build = (f'engine=$(command -v podman || command -v docker) && cd {folder} && '
             f'$engine build -q {args} -t {shlex.quote(local_name)} -f {shlex.quote(dockerfile)} {shlex.quote(context)} >&2 && '
             f'$engine save {shlex.quote(local_name)}')
    save = subprocess.Popen(ssh + [build], stdout=subprocess.PIPE)
    subprocess.run(['podman', 'load', '-q'], stdin=save.stdout, check=True)
    save.stdout.close()
    if save.wait():
        raise SystemExit(f'the build of {name} on {node.name} failed')


if __name__ == '__main__':
    main()
