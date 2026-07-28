"""EasyOCR activity for extracting text from images."""

from temporalio import activity
from typing import Dict, Any, List
from dataclasses import dataclass
import json
import time
import logging
log = logging.getLogger(__name__)


def _to_json_compatible(obj: Any) -> Any:
    try:
        # Fast-path primitives
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        # Numpy scalar
        if hasattr(obj, "item") and hasattr(getattr(obj, "dtype", None), "name"):
            try:
                return obj.item()
            except Exception:
                pass
        # Sequence
        if isinstance(obj, (list, tuple)):
            return [_to_json_compatible(x) for x in obj]
        # Mapping
        if isinstance(obj, dict):
            return {str(k): _to_json_compatible(v) for k, v in obj.items()}
    except Exception:
        pass
    # Fallback
    try:
        return str(obj)
    except Exception:
        return None

@dataclass
class RunEasyOCRParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


def _record_undecodable_skip(params: RunEasyOCRParams, run_time_ms: int) -> None:
	"""Record an undecodable-image skip in processing_errors (same path as
	record_errors_from_results uses), without failing the activity."""
	from tasks.P2_execute_plan.activities import (
		record_processing_errors,
		RecordProcessingErrorsParams,
	)

	record_processing_errors(RecordProcessingErrorsParams(collectionname=params.collectionname, errors=[{
		"collection_dataset": params.collection_dataset,
		"hash": params.file_hash,
		"task_name": "run_easyocr_and_store",
		"run_time_ms": run_time_ms,
		"error_logs": (
			"ocr_skipped_undecodable: image could not be decoded by OpenCV or "
			f"Pillow: {params.file_path}"
		),
	}]))


@activity.defn
def run_easyocr_and_store(params: RunEasyOCRParams) -> str:
	from database.clickhouse import get_collection_client
	import pyarrow as pa
	from tasks.P3_parse_files.parse_ocr_models import OCR_MODEL_EN
	from tasks.P3_parse_files.image_loader import load_image_rgb

	# Run OCR
	log.info("[P3] Running EasyOCR for %s", params.file_path)
	started = time.time()
	model = OCR_MODEL_EN

	# Preflight decode: OpenCV first, Pillow fallback. An image OCR cannot read
	# is a data fact, not a pipeline failure: record it and succeed so it does
	# not consume retries or halt the plan.
	image_array = load_image_rgb(params.file_path)
	if image_array is None:
		run_time_ms = max(int((time.time() - started) * 1000), 0)
		log.warning("[P3] OCR skipped, image undecodable: %s", params.file_path)
		_record_undecodable_skip(params, run_time_ms)
		return "ocr_skipped_undecodable"

	results: List = model.readtext(image_array)
	run_time_ms = int((time.time() - started) * 1000)
	if run_time_ms < 0:
		run_time_ms = 0

	# Concatenate recognized text
	texts: List[str] = []
	for item in results:
		try:
			text_val = item[1]
			if isinstance(text_val, str) and text_val:
				texts.append(text_val)
		except Exception:
			continue
	joined_text = "\n".join(texts)

	# Serialize raw results (convert numpy types to JSON-serializable)
	sanitized = _to_json_compatible(results)
	raw_json = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
	with get_collection_client(params.collectionname) as client:
		tbl_ocr = pa.table({
			"collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
			"image_hash": pa.array([params.file_hash], type=pa.string()),
			"run_time_ms": pa.array([run_time_ms], type=pa.uint32()),
			"raw_json": pa.array([raw_json], type=pa.string()),
		})
		client.insert_arrow("raw_ocr_results", tbl_ocr)

	# Insert extracted text into text_content
	from tasks.P3_parse_files.parse_common import insert_text_chunks
	if joined_text:
		insert_text_chunks(params.collectionname, params.collection_dataset, params.file_hash, "easyocr", joined_text)

	return "ocr_ok"


