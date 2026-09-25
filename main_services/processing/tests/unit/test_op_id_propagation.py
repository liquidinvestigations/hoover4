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
    ("tasks/P2_execute_plan/workflows.py", 159): "ComputePlans input writes no Error.",
    ("tasks/P2_execute_plan/workflows.py", 328): "ComputePlans input writes no Error.",
    ("tasks/P3_parse_files/parse_pdf.py", 257): "The PDF metadata Arrow row is not workflow input.",
    ("tasks/P3_parse_files/parse_pdf.py", 268): "The PDF page Arrow row is not workflow input.",
    ("tasks/P3_parse_files/parse_pdf.py", 360): "The image Arrow rows are not workflow input.",
    ("tasks/P3_parse_files/parse_pdf.py", 369): "The link Arrow rows are not workflow input.",
    ("tasks/P_ops/workflows.py", 215): "Location refresh does not write an Error.",
    ("tasks/P_ops/workflows.py", 283): "ComputePlans input writes no Error.",
    ("tasks/P_ops/workflows.py", 387): "PurgeDataset input writes no Error.",
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
    seen_exemptions = set()
    missing = []
    for relative_path in SOURCE_FILES:
        tree = ast.parse((PROCESSING_ROOT / relative_path).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = _dict_keys(node)
            if "collection_dataset" not in keys or "op_id" in keys:
                continue
            location = (relative_path, node.lineno)
            if location in EXEMPT_COLLECTION_DATASET_DICTS:
                seen_exemptions.add(location)
                continue
            missing.append(f"{relative_path}:{node.lineno}")
    assert not missing, "collection dataset dicts without op_id: " + ", ".join(missing)
    assert seen_exemptions == set(EXEMPT_COLLECTION_DATASET_DICTS)
