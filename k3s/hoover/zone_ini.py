#!/usr/bin/env python3
"""Write the hoover4.ini of one cluster installation from its operator settings.

The operator settings (../platform/operator/settings.py) hold every Hoover ini tuning and switch. Their effective
values give the [main_services], [ai_services], [operations], [processing_updates] and [uploads] keys of the ini.
The cluster sets the other keys itself (FIXED), because Kubernetes owns ports, volumes and identity there.
deploy.py of the source tree then checks the ini, when compose.py renders the services.

The Hoover budget of an installation is a group of operator settings (BUDGET names them). derive() turns it into
suggested values of other keys, by the rules of the configuration reference:
- Memory sets the number of common processes in a worker pod, and CPU sets their slots. The processes times the slots
  are at most 1.5 times the CPUs of the pod, and the processes need PROCESS_MIB and SLOT_MIB each.
- Tika has one parser process for each of its CPUs, a heap of 1 GiB each, and a limit of the heaps plus 1 GiB.
- Tesseract has one slot for each of its CPUs, and 4096 MiB plus 1024 MiB for each slot. OCR PDF has the larger of
  8000 MiB and 2048 MiB for each slot, with at most 5 slots for each Tesseract slot.
- The browser has 500 MiB for each context and 1 GiB for the template.
An explicit operator value of a key replaces its derived value.
The ini points every GPU service and the LLM at the forwarder gpu in the Hoover namespace (gpu.py), and names the
placeholder volumes folder, which manifests.py maps to volumes.
Usage: zone_ini.py <site.ini> <installation>    prints the ini of the installation with its saved settings
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The budget keys and their defaults. The operator settings hold them as hoover.budget.<key>.
BUDGET = {
    'worker_pods': 1,          # worker replicas of the installation, spread over the nodes
    'worker_memory_mib': 6144,  # memory of one worker pod
    'worker_cpus': 4,          # CPUs of one worker pod
    'tika_cpus': 2,
    'tesseract_cpus': 2,
    'ocr_pdf_slots': 1,
    'browser_contexts': 4,
    'clamav_memory_mib': 3072,
}
# The Temporal history shards of a new installation. A migrated installation keeps its count.
SHARDS = 128
# The peak of one common process and of one more slot, with the parser tools that it starts. These are estimates until
# a corpus run measures them.
PROCESS_MIB = 1024
SLOT_MIB = 512
# The other processes of a worker pod: Tika, ClamAV, OCR, NLP, embedding and indexing clients, and the supervisor.
OTHER_MIB = 1536
# The values that the cluster sets. No operator setting changes them.
FIXED = {
    ('storage', 'volumes_path'): '/volumes',
    ('main_services', 'website_release_mode'): 'true',
    ('main_services', 'development_auth_backdoor_enabled'): 'false',
    ('main_services', 'chat_control_dir'): '',
    ('main_services', 'ops_backup_dir'): '',
    ('ai_services', 'host'): 'gpu',
}


def derive(b):
    """The suggested hoover4.ini values of a budget, as {(section, key): value}."""
    memory = b['worker_memory_mib'] - OTHER_MIB
    cpus = b['worker_cpus']
    if memory < PROCESS_MIB + SLOT_MIB:
        raise ValueError(f"a worker pod of {b['worker_memory_mib']} MiB holds no common process")
    best = (1, 1)
    for slots in (1, 2, 3):
        count = min(memory // (PROCESS_MIB + slots * SLOT_MIB), math.floor(1.5 * cpus / slots))
        if count >= 1 and count * slots > best[0] * best[1]:
            best = (count, slots)
    common, slots = best
    tika = b['tika_cpus']
    tesseract = b['tesseract_cpus']
    ocr_pdf = min(b['ocr_pdf_slots'], 5 * tesseract)
    m = 'main_services'
    return {
        (m, 'common_workers'): str(common), (m, 'common_concurrency'): str(slots),
        (m, 'indexing_workers'): '1', (m, 'indexing_concurrency'): '1',
        (m, 'worker_mem_limit'): f"{b['worker_memory_mib']}M",
        (m, 'tika_parse_processes'): str(tika), (m, 'tika_parse_heap'): '1g', (m, 'tika_concurrency'): str(tika),
        (m, 'tika_mem_limit'): f'{tika * 1024 + 1024}M',
        (m, 'tesseract_cpu_concurrency'): str(tesseract), (m, 'tesseract_cpu_cpus'): str(tesseract),
        (m, 'tesseract_cpu_mem_limit'): f'{4096 + 1024 * tesseract}M',
        (m, 'ocr_pdf_concurrency'): str(ocr_pdf), (m, 'ocr_pdf_mem_limit'): f'{max(8000, 2048 * ocr_pdf)}M',
        (m, 'browser_max_contexts'): str(b['browser_contexts']),
        (m, 'mcp_browser_mem_limit'): f"{500 * b['browser_contexts'] + 1024}M",
        (m, 'clamav_mem_limit'): f"{b['clamav_memory_mib']}M",
    }


def render(values, mounts, gpu_enabled, admin_base_url='', title='an installation'):
    """The text of the ini.

    values  {(section, key): text} of every ini setting, as the operator settings resolve them
    mounts  the dataset mounts: name, path (container path), writable
    """
    sections = {}
    merged = {**values, **FIXED, ('ai_services', 'enabled'): 'true' if gpu_enabled else 'false',
              ('main_services', 'admin_base_url'): admin_base_url}
    for (section, key), value in merged.items():
        sections.setdefault(section, {})[key] = value
    lines = [f'# The hoover4.ini of {title}, written by k3s/hoover/zone_ini.py.']
    for section in sorted(sections):
        lines += ['', f'[{section}]'] + [f'{k} = {v}' for k, v in sorted(sections[section].items())]
    # deploy.py needs a host folder for each mount. The cluster mounts the volume itself, so the host path is a
    # placeholder below the placeholder volumes folder.
    for mount in mounts:
        lines += ['', f"[dataset_mount.{mount['name']}]", f"host_path = /volumes/datasets/{mount['name']}",
                  f"container_path = {mount['path']}", f"writable = {'true' if mount['writable'] else 'false'}"]
    return '\n'.join(lines).replace('%', '%%') + '\n'


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import manifests  # noqa: E402
    target = manifests.target_from_site(sys.argv[1], sys.argv[2])
    print(manifests.zone_ini_text(target), end='')
    print(json.dumps(target.budget), file=sys.stderr)
