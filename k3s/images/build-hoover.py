#!/usr/bin/env python3
"""Build the Hoover images of compose.IMAGES from one commit of this repository and push them to the cluster registry.

The script exports the commit with `git archive` into k3s/private/build/<commit>, so local changes of the checkout
stay unchanged and stay out of the images. The image tag is the first 12 characters of the commit.
../hoover/manifests.py names the images with the same tag (image_tag()).
The website image is the release Dockerfile. The processing image starts the installed interpreter.
Usage: build-hoover.py [--revision REV] [name ...]    Without names it builds every image of compose.IMAGES.
                                                      The default revision is HEAD.
       build-hoover.py --gpu [--revision REV] [name ...]
                                                      Builds the images of compose.GPU_IMAGES for the architecture
                                                      of the GPU nodes of the site file. The model server image gets
                                                      the base image of deploy.py (QWEN_FLASH_BASE_IMAGE).
"""
import argparse
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
    out = subprocess.run(['git', '-C', str(settings.HOOVER4), 'rev-parse', '--verify', f'{revision}^{{commit}}'],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f'{revision} is not a commit of {settings.HOOVER4}')
    return out.stdout.strip()


def prepare(sha):
    """Write the source tree of one commit once. A tree with the expected stamp stays."""
    tree = settings.PRIVATE / 'build' / sha
    stamp = tree / '.hoover-build-commit'
    if stamp.exists() and stamp.read_text() == sha:
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
        subprocess.run(['bash', str(HERE / 'build-image.sh'), str(tree / context), f'hoover/hoover-{name}:{sha[:12]}',
                        str(tree / dockerfile)], check=True, env=step_env)
    print(sha)


if __name__ == '__main__':
    main()
