"""The inputs of a Compose import: the hoover4.ini of the Compose install and the folder arguments. Standard library only.

read_ini() reads the hoover4.ini of a Compose install. It accepts each setting that deploy.py lists as removed, such
as the Serena settings, reports it and leaves it out. It refuses an unknown section or key and every other problem that
`./deploy --check` refuses. It reads the file only. The folders of the ini are host paths of the Compose host, so the
import checks them on that host (probe.py).
relative_folder() checks a folder argument: a path below the data root of the source node, without `..`.
The tools adopt-cluster.py and local-retirement.py of ../tools also read a hoover4.ini with read_ini().

Usage: source.py <hoover4.ini>    prints the values that the import reads from the file as JSON
"""
import configparser
import importlib.util
import json
import posixpath
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The Compose volume folders that the import does not copy, and why.
SKIPPED = {'hoover4-website-target': 'the build folder of the development website. The release image holds the server.',
           'easyocr_models_cache': 'a model cache. The worker downloads the models again.'}
# The store folders that every Compose install has.
REQUIRED = ('clickhouse_data', 'manticore_data_v14', 'garage_meta', 'garage_data', 'temporal_cassandra',
            'temporal_elasticsearch')
# The settings of the ini that the import reads and that no cluster setting takes. The plan reports them.
NOT_IMPORTED = (('main_services', 'chat_control_dir'), ('main_services', 'ops_backup_dir'), ('storage', 'volumes_path'))


class SourceError(ValueError):
    """The ini or a folder argument has problems. The message names each problem."""


@dataclass
class SourceInstall:
    path: str
    values: dict
    explicit: list
    dropped: list
    volumes_path: str
    # The Compose volume folders of the main side, by name. The folder names are relative to the volume folder.
    volumes: list
    dataset_mounts: list
    # The explicit values of NOT_IMPORTED, as {"[section] key": value}.
    not_imported: dict


def deploy_module():
    spec = importlib.util.spec_from_file_location('hoover_deploy_source', REPO / 'deploy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_ini(path):
    """The SourceInstall of the hoover4.ini of a Compose install."""
    deploy = deploy_module()
    parser = configparser.ConfigParser(inline_comment_prefixes=None, default_section='\n')
    try:
        with open(path, encoding='utf-8') as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as error:
        raise SourceError(f'the Compose ini {path} cannot be read: {error}') from None
    cfg = deploy.Config(None)
    problems, dropped = [], []
    for section in parser.sections():
        if (section, None) in deploy.REMOVED_SETTINGS:
            dropped.append(f'[{section}]')
            continue
        problem = deploy.Config._section_problem(section)
        if problem:
            problems.append(problem)
            continue
        cfg.values.setdefault(section, {})
        for key in parser.options(section):
            if (section, key) in deploy.REMOVED_SETTINGS:
                dropped.append(f'[{section}] {key}')
                continue
            problem = deploy.Config._key_problem(section, key)
            if problem:
                problems.append(problem)
                continue
            raw = parser.get(section, key, raw=True)
            if deploy.INLINE_COMMENT.search(raw):
                problems.append(f'[{section}] {key} has a comment after its value.')
                continue
            try:
                cfg.values[section][key] = parser.get(section, key).strip()
            except configparser.InterpolationError:
                problems.append(f'[{section}] {key} has a % sign that is not written as %%.')
                continue
            cfg.explicit.add((section, key))
    if problems:
        raise SourceError(f'the Compose ini {path} has {len(problems)} problem{"s" if len(problems) != 1 else ""}:\n    '
                          + '\n    '.join(problems))
    problem = deploy.volumes_path_problem(cfg)
    if problem:
        raise SourceError(f'the Compose ini {path}: {problem}')
    try:
        mounts = deploy.dataset_mounts(cfg)
    except deploy.DeployError as error:
        raise SourceError(f'the Compose ini {path}: {error}') from None
    values = {s: dict(k) for s, k in cfg.values.items()}
    return SourceInstall(path=str(path), values=values, explicit=sorted(f'{s}.{k}' for s, k in cfg.explicit),
                         dropped=dropped, volumes_path=cfg.get('storage', 'volumes_path').strip(),
                         volumes=[row.name for row in deploy.VOLUMES if row.side == 'main'],
                         dataset_mounts=[{'name': m.name, 'host_path': m.host_path, 'container_path': m.container_path,
                                          'writable': m.writable} for m in mounts],
                         not_imported={f'[{s}] {k}': values[s][k] for s, k in NOT_IMPORTED
                                       if (s, k) in cfg.explicit and values[s][k]})


def effective(source, section, key):
    """The value of a setting of the Compose install: its explicit value, else the deploy.py default."""
    value = source.values.get(section, {}).get(key, '')
    if value:
        return value
    return deploy_module().Config(None).get(section, key).strip()


def relative_folder(text, label='the folder'):
    """The normalized relative POSIX path of a folder argument. An absolute path, `..` or an empty path is refused."""
    text = str(text or '').strip()
    if not text:
        raise SourceError(f'{label} is empty. Give a folder below the data root of the source node.')
    if text.startswith('/'):
        raise SourceError(f'{label} {text} is an absolute path. Give a folder below the data root of the source node.')
    parts = [p for p in text.split('/') if p not in ('', '.')]
    if '..' in parts:
        raise SourceError(f'{label} {text} contains `..`. Give a folder below the data root of the source node.')
    if not parts:
        raise SourceError(f'{label} {text} names the data root itself. Give a folder below it.')
    return posixpath.join(*parts)


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    print(json.dumps(asdict(read_ini(argv[0])), indent=1))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except SourceError as error:
        raise SystemExit(str(error))
