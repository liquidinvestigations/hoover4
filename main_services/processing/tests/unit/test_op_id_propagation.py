"""The operation id reaches every workflow parameter that can write an Error."""

import ast
import dataclasses
import importlib
from pathlib import Path


PROCESSING_ROOT = Path(__file__).parents[2]

PARAMS = (
    ("tasks.P0_scan_disk.workflows", "IngestDiskDatasetParams"),
    ("tasks.P2_execute_plan.workflows", "ExecutePlansParams"),
    ("tasks.P2_execute_plan.workflows", "ExecuteSinglePlanParams"),
    ("tasks.P2_execute_plan.workflows", "ProcessItemsBatchedParams"),
    ("tasks.P2_execute_plan.activities", "ListPendingPlansParams"),
    ("tasks.P3_parse_files.batch_runner", "StageBatchParams"),
    ("tasks.P3_parse_files.batch_runner", "ScanContainerFoldersParams"),
    ("tasks.P3_parse_files.parse_ocr", "RunOcrParams"),
    ("tasks.P3_parse_files.parse_ocr_pdf", "RunOcrPdfParams"),
    ("tasks.P3_parse_files.parse_table", "ParseTableParams"),
    ("tasks.P3_parse_files.parse_office_xml", "ParseOfficeXmlParams"),
    ("tasks.P4_extract_entities.params", "ExtractEntitiesForPlanParams"),
    ("tasks.P4_extract_entities.params", "ScanRegexEntitiesForPlanParams"),
    ("tasks.P5_chunk_embed.params", "ChunkEmbedForPlanParams"),
    ("tasks.P6_index_data.params", "IndexDatasetPlanParams"),
)

SOURCE_FILES = (
    "tasks/P0_scan_disk/workflows.py",
    "tasks/P2_execute_plan/workflows.py",
    "tasks/P3_parse_files/workflows.py",
    "tasks/P3_parse_files/parse_pdf.py",
    "tasks/P_ops/workflows.py",
    "tasks/P_admin/workflows.py",
)

EXEMPT_COLLECTION_DATASET_DICTS = {
    "ComputePlans", "RefreshDocumentLocations", "PurgeDataset",
}



def _called_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _dict_keys(node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def test_error_writer_params_have_an_operation_id_field():
    for module_name, class_name in PARAMS:
        cls = getattr(importlib.import_module(module_name), class_name)
        field = next(field for field in dataclasses.fields(cls) if field.name == "op_id")
        assert field.type in (str, "str")
        assert field.default == ""


def test_operation_inputs_pass_op_id_to_error_writer_workflows():
    names = {class_name for _, class_name in PARAMS}
    missing = []
    for relative_path in SOURCE_FILES:
        tree = ast.parse((PROCESSING_ROOT / relative_path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called_name(node.func) in names:
                keywords = {keyword.arg for keyword in node.keywords}
                if "op_id" not in keywords:
                    missing.append(f"{relative_path}:{node.lineno}:{_called_name(node.func)}")
    assert not missing, "workflow params without op_id: " + ", ".join(missing)


def test_collection_dataset_dicts_are_operation_inputs_or_listed_exceptions():
    missing = []
    for relative_path in SOURCE_FILES:
        tree = ast.parse((PROCESSING_ROOT / relative_path).read_text())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = _dict_keys(node)
            if "collection_dataset" not in keys or "op_id" in keys:
                continue
            parent = parents.get(node)
            if isinstance(parent, ast.Call):
                if _called_name(parent.func) == "table":
                    continue
                target = parent.args[0] if parent.args else None
                name = target.value if isinstance(target, ast.Constant) else (
                    _called_name(target.value) if isinstance(target, ast.Attribute) else "")
                if name in EXEMPT_COLLECTION_DATASET_DICTS:
                    continue
            missing.append(f"{relative_path}:{node.lineno}")
    assert not missing, "collection dataset dicts without op_id: " + ", ".join(missing)
