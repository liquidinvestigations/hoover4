"""Structural test: every params dataclass that has ``collection_dataset`` must also
have ``collectionname``.

``collectionname`` travels with ``collection_dataset`` through every workflow and
activity parameter; it is resolved once at the workflow entry point and never
re-derived inside an activity. A half-done conversion (field added to some params
dataclasses but not others) is the one thing plan part 3 can get wrong, and this
test catches it cheaply.
"""

import dataclasses
import importlib
import pkgutil

import tasks

# Modules excluded from the walk: import-time side effects (model loading) and no
# params dataclasses.
_SKIP_MODULES = {
    "tasks.P3_parse_files.parse_ocr_models",  # loads the EasyOCR model at import time
}


def _task_module_names() -> list[str]:
    names = []
    for info in pkgutil.walk_packages(tasks.__path__, prefix="tasks."):
        if info.name in _SKIP_MODULES:
            continue
        names.append(info.name)
    return names


def _params_dataclasses():
    for name in _task_module_names():
        module = importlib.import_module(name)
        for attr in vars(module).values():
            if isinstance(attr, type) and dataclasses.is_dataclass(attr):
                yield name, attr


def test_every_task_module_imports():
    """Guard the walk itself: a module that fails to import would silently drop
    its params dataclasses from the structural check below."""
    failures = {}
    for name in _task_module_names():
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 - report every failure at once
            failures[name] = repr(e)
    assert not failures, f"task modules failed to import: {failures}"


def test_params_with_collection_dataset_carry_collectionname():
    offenders = []
    for module_name, cls in _params_dataclasses():
        field_names = {f.name for f in dataclasses.fields(cls)}
        if "collection_dataset" in field_names and "collectionname" not in field_names:
            offenders.append(f"{module_name}.{cls.__name__}")
    assert not offenders, (
        "params dataclasses with collection_dataset but no collectionname: "
        + ", ".join(sorted(offenders))
    )


def test_sanity_some_params_dataclasses_found():
    """The test above is vacuous if the walk finds nothing."""
    found = [
        cls
        for _, cls in _params_dataclasses()
        if "collection_dataset" in {f.name for f in dataclasses.fields(cls)}
    ]
    assert len(found) >= 20
