"""The inline transfer of the searchable-PDF client (OCR_PDF_TRANSFER=inline)."""
import base64
import hashlib

import pytest

from tasks import ocr_pdf_client


class FakeObject:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeStore:
    def __init__(self, objects, short=False):
        self.objects, self.put, self.short = objects, {}, short

    def stat_object(self, bucket, key):
        return type("Stat", (), {"size": len(self.objects[(bucket, key)])})()

    def get_object(self, bucket, key):
        data = self.objects[(bucket, key)]
        return FakeObject(data[:-1] if self.short else data)

    def put_object(self, bucket, key, stream, length, content_type):
        assert content_type == "application/pdf"
        self.put[(bucket, key)] = stream.read()
        assert len(self.put[(bucket, key)]) == length


def answer(pdf, **extra):
    return type("Result", (), {"provider": "ocr-pdf", "data": {
        "dest_key": extra.get("dest_key", "derived/ocr-pdf/x.pdf"), "blob_hash": hashlib.sha3_256(pdf).hexdigest(),
        "page_count": 2, "pages_with_text": 1, "size_bytes": len(pdf), "engine": "tesseract", "languages": "eng",
        "run_time_ms": 5, "pages": [], "pdf_b64": base64.b64encode(pdf).decode(), **extra}})()


@pytest.fixture
def inline(monkeypatch):
    monkeypatch.setattr(ocr_pdf_client, "INLINE", True)
    monkeypatch.setenv("OCR_PDF_URL", "http://hoover4-ocr-pdf:8000/ocr-pdf")


def test_inline_sends_the_source_and_writes_the_answer(inline, monkeypatch):
    store = FakeStore({("source-bucket", "source.pdf"): b"%PDF-source"})
    monkeypatch.setattr("database.s3.get_s3_client", lambda: store)
    sent = {}

    def post(endpoints, payload, **kwargs):
        sent.update(payload)
        return answer(b"%PDF-result")
    monkeypatch.setattr(ocr_pdf_client, "post_json", post)
    outcome = ocr_pdf_client.build_ocr_pdf(collectionname="demo", collection_dataset="demo", pdf_hash="h",
                                           engine="tesseract", languages="eng", source_key="source.pdf",
                                           source_bucket="source-bucket", bucket="owned", dest_key="derived/ocr-pdf/x.pdf")
    assert sent["inline"] is True and "source_key" not in sent
    assert base64.b64decode(sent["source_b64"]) == b"%PDF-source"
    assert store.put == {("owned", "derived/ocr-pdf/x.pdf"): b"%PDF-result"}
    assert outcome.dest_key == "derived/ocr-pdf/x.pdf" and outcome.size_bytes == len(b"%PDF-result")


def test_inline_refuses_an_answer_with_another_hash(inline, monkeypatch):
    store = FakeStore({})
    monkeypatch.setattr("database.s3.get_s3_client", lambda: store)
    monkeypatch.setattr(ocr_pdf_client, "post_json",
                        lambda *a, **k: answer(b"%PDF-result", blob_hash="0" * 64))
    with pytest.raises(RuntimeError, match="incomplete PDF"):
        ocr_pdf_client.build_ocr_pdf(collectionname="demo", collection_dataset="demo", pdf_hash="h",
                                     engine="tesseract", languages="eng", source_b64="JVBERg==", bucket="owned")
    assert store.put == {}


def test_inline_refuses_a_short_source_read(inline, monkeypatch):
    store = FakeStore({("owned", "source.pdf"): b"%PDF-source"}, short=True)
    monkeypatch.setattr("database.s3.get_s3_client", lambda: store)
    monkeypatch.setattr(ocr_pdf_client, "post_json", lambda *a, **k: pytest.fail("no request after a short read"))
    with pytest.raises(RuntimeError, match="gave 10 of 11 bytes"):
        ocr_pdf_client.build_ocr_pdf(collectionname="demo", collection_dataset="demo", pdf_hash="h",
                                     engine="tesseract", languages="eng", source_key="source.pdf", bucket="owned")


def test_store_mode_keeps_the_object_contract(monkeypatch):
    monkeypatch.setattr(ocr_pdf_client, "INLINE", False)
    sent = {}

    def post(endpoints, payload, **kwargs):
        sent.update(payload)
        return answer(b"%PDF-result", pdf_b64="")
    monkeypatch.setattr(ocr_pdf_client, "post_json", post)
    monkeypatch.setattr("database.s3.get_s3_client", lambda: pytest.fail("store mode opens no client"))
    ocr_pdf_client.build_ocr_pdf(collectionname="demo", collection_dataset="demo", pdf_hash="h", engine="tesseract",
                                 languages="eng", source_key="source.pdf", bucket="owned")
    assert sent["source_key"] == "source.pdf" and "inline" not in sent
