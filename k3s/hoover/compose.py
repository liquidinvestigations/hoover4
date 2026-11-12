#!/usr/bin/env python3
"""Read the Compose services of one Hoover installation from its hoover4.ini, the way deploy.py starts them.

The source is a Hoover4 tree: by default the repository that holds k3s/, or the tree that ../images/build-hoover.py
exported for one revision. The loader imports deploy.py of that tree, reads the ini with deploy.Config, and renders the
.env values with deploy.render_main_env, which also runs the checks of the values. It merges the Compose files that
deploy.compose_files selects for the ini, in their order, and replaces each ${NAME}, ${NAME:-default}, ${NAME-default},
${NAME:?message} and $$ like Compose. A !override value replaces the merged value, and a !reset value removes it.
The dataset mounts overlay of deploy.py is left out, because manifests.py mounts the data directories itself.
manifests.py translates the services into Kubernetes objects. The Compose files stay the single source of truth for
the commands, the environment and the limits of each service.
Usage: compose.py <ini> [service]    prints the merged services as JSON
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

TREE = settings.HOOVER4
# The images that ../images/build-hoover.py builds from the tree: (Containerfile, context), relative to the tree. Each
# image is <registry>/hoover/hoover-<key>. manifests.py names the image of each service.
IMAGES = {
    'website': ('website/Dockerfile.release', 'website'),
    'processing': ('main_services/processing/Dockerfile', 'main_services/processing'),
    'regex': ('main_services/regex_entity_scanner/Dockerfile.release', 'main_services/regex_entity_scanner'),
    'tesseract': ('main_services/ocr_tesseract/Dockerfile', 'main_services/ocr_tesseract'),
    'ocr-pdf': ('main_services/ocr_pdf/Dockerfile', 'main_services/ocr_pdf'),
    'clamav': ('main_services/clamav/Dockerfile', 'main_services/clamav'),
    'pdf-search': ('main_services/pdf_search/Dockerfile', 'main_services/pdf_search'),
    'garage-init': ('main_services/ops/docker/garage/Dockerfile', 'main_services/ops/docker/garage'),
    'mcp-collections': ('main_services/agents/collection_search_server/Dockerfile', 'main_services/agents'),
    'mcp-todo': ('main_services/agents/agent_todo_server/Dockerfile', 'main_services'),
    'mcp-whois': ('main_services/agents/whois_search_server/Dockerfile', 'main_services/agents'),
    'mcp-metasearch': ('main_services/agents/metasearch_server/Dockerfile', 'main_services/agents'),
    'mcp-browser': ('main_services/agents/browser_use_server/Dockerfile', 'main_services/agents'),
    'web-tor': ('main_services/ops/docker/web-tor/Dockerfile', 'main_services/ops/docker/web-tor'),
    'research-agent': ('main_services/agents/research_agent/Dockerfile', 'main_services/agents'),
}
# The images of the GPU services (../platform/gpu/gpu_pool.py). They run on the GPU nodes, so build-hoover.py --gpu
# builds them for the architecture of those nodes. The model server image takes its base image as a build argument.
GPU_IMAGES = {
    'ai-server': ('ai_services/hoover4_ai_server/Dockerfile', 'ai_services'),
    'easyocr': ('ai_services/easyocr_server/Dockerfile', 'ai_services/easyocr_server'),
    'vllm': ('ai_services/qwen_flash/Dockerfile', 'ai_services/qwen_flash'),
}
VARIABLE = re.compile(r'\$(?:\$|\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*))')


class Override:
    """A Compose !override value. It replaces the merged value of its key."""

    def __init__(self, value):
        self.value = value


class Reset:
    """A Compose !reset value. It removes the merged value of its key."""


class Loader(yaml.SafeLoader):
    pass


def _override(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return Override(loader.construct_sequence(node, deep=True))
    if isinstance(node, yaml.MappingNode):
        return Override(loader.construct_mapping(node, deep=True))
    return Override(loader.construct_scalar(node))


Loader.add_constructor('!override', _override)
Loader.add_constructor('!reset', lambda loader, node: Reset())


def deploy_module(tree=TREE):
    spec = importlib.util.spec_from_file_location('hoover_deploy', Path(tree) / 'deploy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def substitute(value, env):
    if isinstance(value, dict):
        return {k: substitute(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, env) for v in value]
    if not isinstance(value, str):
        return value

    def one(m):
        if m.group(0) == '$$':
            return '$'
        name = m.group(1) or m.group(4)
        op, arg = m.group(2), m.group(3)
        present = name in env and (env[name] != '' or not (op or '').startswith(':'))
        if op and op.endswith('?') and not present:
            raise SystemExit(f'{name} is not set: {arg}')
        if op and op.endswith('-') and not present:
            return substitute(arg, env)
        return str(env.get(name, ''))
    return VARIABLE.sub(one, value)


def environment(value):
    """A Compose environment list or mapping as a mapping."""
    if isinstance(value, dict):
        return {k: '' if v is None else str(v) for k, v in value.items()}
    out = {}
    for item in value or []:
        key, _, val = item.partition('=')
        out[key] = val
    return out


def volume_target(spec):
    """The container path of a short or long Compose volume entry."""
    if isinstance(spec, dict):
        return spec.get('target')
    parts = str(spec).split(':')
    return parts[1] if len(parts) > 1 else parts[0]


def volume_parts(spec):
    """(source, target, read_only) of a short or long Compose volume entry."""
    if isinstance(spec, dict):
        return str(spec.get('source', '')), spec.get('target'), bool(spec.get('read_only'))
    parts = str(spec).split(':')
    if len(parts) == 1:
        return '', parts[0], False
    return parts[0], parts[1], len(parts) > 2 and 'ro' in parts[2].split(',')


def merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, Reset):
            base.pop(key, None)
        elif isinstance(value, Override):
            base[key] = value.value
        elif key == 'environment':
            base[key] = {**environment(base.get(key)), **environment(value)}
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        elif key == 'volumes' and isinstance(value, list) and isinstance(base.get(key), list):
            # Compose merges volumes by their container path. A later entry replaces an entry with the same path.
            targets = {volume_target(v) for v in value}
            base[key] = [v for v in base[key] if volume_target(v) not in targets] + list(value)
        elif isinstance(value, list) and isinstance(base.get(key), list) and key in ('ports', 'tmpfs', 'cap_add'):
            base[key] = base[key] + [v for v in value if v not in base[key]]
        else:
            base[key] = value
    return base


def load(ini, tree=TREE):
    """Return the deploy module, the Config, the .env values and the merged services of an ini file."""
    deploy = deploy_module(tree)
    cfg = deploy.Config(Path(ini))
    # The identity function keeps [ai_services] host as written, so the render runs no host command.
    env = deploy.render_main_env(cfg, reachable_host=lambda host: host)
    services = {}
    for path in deploy.compose_files(cfg, 'main'):
        if path == str(deploy.DATASET_MOUNTS_OVERLAY):
            continue
        for name, service in (yaml.load(Path(path).read_text(), Loader=Loader).get('services') or {}).items():
            merge(services.setdefault(name, {}), service)
    rendered = substitute(services, env)
    for service in rendered.values():
        service['environment'] = environment(service.get('environment'))
    return deploy, cfg, env, rendered


def load_ai(ini, tree=TREE):
    """Return the deploy module, the Config, the .env values and the merged GPU services of an ini file.

    The GPU side uses the Compose files that deploy.py starts on a GPU host (`./deploy --ai-services`).
    ../platform/gpu/gpu_pool.py translates them for the GPU nodes of a site.
    """
    deploy = deploy_module(tree)
    cfg = deploy.Config(Path(ini))
    env = deploy.render_ai_env(cfg)
    services = {}
    for path in deploy.compose_files(cfg, 'ai'):
        for name, service in (yaml.load(Path(path).read_text(), Loader=Loader).get('services') or {}).items():
            merge(services.setdefault(name, {}), service)
    rendered = substitute(services, env)
    for service in rendered.values():
        service['environment'] = environment(service.get('environment'))
    return deploy, cfg, env, rendered


def compose_service_names(tree=TREE):
    """Every service name of every Compose file of the tree, on both sides, with the file that names it."""
    found = {}
    for pattern in ('main_services/ops/docker/docker-compose.yaml', 'main_services/ops/docker/compose/*.yaml',
                    'ai_services/docker-compose.yaml', 'ai_services/compose/*.yaml'):
        for path in sorted(Path(tree).glob(pattern)):
            if path.name == 'generated-dataset-mounts.yaml':
                continue
            for name in (yaml.load(path.read_text(), Loader=Loader) or {}).get('services') or {}:
                found.setdefault(name, []).append(str(path.relative_to(tree)))
    return found


if __name__ == '__main__':
    _, _, _, found = load(sys.argv[1])
    print(json.dumps(found[sys.argv[2]] if len(sys.argv) > 2 else found, indent=1, default=str))
