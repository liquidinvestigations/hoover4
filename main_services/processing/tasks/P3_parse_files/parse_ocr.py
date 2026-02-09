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
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
def run_easyocr_and_store(params: RunEasyOCRParams) -> str:
	from database.clickhouse import get_clickhouse_client
	import pyarrow as pa
	from tasks.P3_parse_files.parse_ocr_models import OCR_MODEL_EN

	# Run OCR
	log.info("[P3] Running EasyOCR for %s", params.file_path)
	started = time.time()
	model = OCR_MODEL_EN
	results: List = model.readtext(params.file_path)
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
	with get_clickhouse_client() as client:
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
		insert_text_chunks(params.collection_dataset, params.file_hash, "easyocr", joined_text)

	return "ocr_ok"


