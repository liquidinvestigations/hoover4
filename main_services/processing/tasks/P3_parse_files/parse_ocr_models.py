"""Model loader for EasyOCR configurations used by parsing tasks."""

import logging
log = logging.getLogger(__name__)
import easyocr
log.info("[P3] Loading EasyOCR model for English")
OCR_MODEL_EN = easyocr.Reader(['en'], gpu=True)