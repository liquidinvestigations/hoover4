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
#
# Empty, because OCR runs behind HTTP and no module here loads a model at import. The
# set stays because the hazard it documents is structural: a module that builds something
# like an `easyocr.Reader` at import downloads its weights the first time any worker
# process touches it, which breaks this walk and does that work inside
# an activity's first call.
_SKIP_MODULES: set[str] = set()


def _task_module_names() -> list[str]:
    names = []
    for info in pkgutil.walk_packages(tasks.__path__, prefix="tasks."):
        if info.name in _SKIP_MODULES:
            continue
        names.append(info.name)
    return names


def _params_dataclasses():
    """Every dataclass that crosses a Temporal boundary, by the ``*Params`` convention.

    The suffix is the filter because not every dataclass in a task module is a parameter:
    the derivation stages also use dataclasses as ROW MIRRORS (one instance per ClickHouse
    row, e.g. `email_graph.EmailIdentity`). A row mirror legitimately carries
    `collection_dataset` without `collectionname` -- it mirrors a table in a per-collection
    database, where naming the collection in every row would be the redundancy, and it is
    never an activity argument. `test_every_params_dataclass_uses_the_suffix` below keeps
    the convention honest so this filter cannot quietly exclude a real one.
    """
    for name in _task_module_names():
        module = importlib.import_module(name)
        for attr in vars(module).values():
            if isinstance(attr, type) and dataclasses.is_dataclass(attr):
                if not attr.__name__.endswith("Params"):
                    continue
                yield name, attr


def test_every_params_dataclass_uses_the_suffix():
    """Anything declared in a `params` module is an activity argument or an activity
    return and must say so in its name, because the walk above trusts the suffix."""
    offenders = []
    for name in _task_module_names():
        if not name.endswith(".params"):
            continue
        module = importlib.import_module(name)
        for attr in vars(module).values():
            if isinstance(attr, type) and dataclasses.is_dataclass(attr):
                if attr.__module__ == name and not attr.__name__.endswith(("Params", "Result")):
                    offenders.append(f"{name}.{attr.__name__}")
    assert not offenders, (
        "dataclasses in a params module without a Params/Result suffix: "
        + ", ".join(sorted(offenders))
    )


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
