# Text detection models

The `/detect` route loads these local files. The service makes no model download.

| file | source | licence | SHA-256 |
|---|---|---|---|
| `PP-OCRv6_det_tiny.onnx` | PaddleOCR PP-OCRv6 tiny text detector, as packaged by RapidOCR 3.10.0 | Apache-2.0 | `f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5` |
| `osd_lstm.onnx` | [ogkalu/image-script-identification](https://huggingface.co/ogkalu/image-script-identification), revision `82c21077f798b80def944eec379b06569c7d48e7` | Apache-2.0 tag | `b18e0c1479d9eb67394993098f7e1079c9a93ef6f7b0416ee333fccb865c6e72` |
| `osd_labels.json` | same revision | Apache-2.0 tag | `a1888156b005065039c356e13a7bbef1ec454b45bf6aaf18c11f4a59b1ee35c5` |

The model card of the script model does not state its training data.
Its labels match the Tesseract script models.
