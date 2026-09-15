from tasks.P_admin import stage_eligibility


def test_ner_stage_follows_its_endpoint(monkeypatch):
    monkeypatch.delenv("NER_URL", raising=False)
    assert stage_eligibility.stage_is_off("P4_ExtractEntities", "dataset")

    monkeypatch.setenv("NER_URL", " http://ner ")
    assert not stage_eligibility.stage_is_off("P4_ExtractEntities", "dataset")


def test_unknown_task_is_never_off(monkeypatch):
    monkeypatch.delenv("NER_URL", raising=False)
    assert not stage_eligibility.stage_is_off("unknown_task", "dataset")
    assert not stage_eligibility.stage_is_off("run_ocr_and_store[unknown]", "dataset")


def test_ocr_stages_need_an_endpoint_and_languages(monkeypatch):
    monkeypatch.setattr(stage_eligibility, "engine_configured", lambda _engine: True)
    monkeypatch.setattr(stage_eligibility, "tesseract_languages", lambda _dataset: "eng")
    monkeypatch.setattr(stage_eligibility, "easyocr_passes", lambda _dataset: [])
    monkeypatch.setattr(stage_eligibility, "service_configured", lambda: True)
    monkeypatch.setattr(
        stage_eligibility, "engines_for_provider", lambda: ["tesseract", "easyocr"]
    )

    assert not stage_eligibility.stage_is_off(
        "run_ocr_and_store[tesseract]", "dataset"
    )
    assert stage_eligibility.stage_is_off("run_ocr_and_store[easyocr]", "dataset")
    assert not stage_eligibility.stage_is_off(
        "run_ocr_pdf_and_store[tesseract]", "dataset"
    )


def test_embeddings_stages_follow_the_endpoint(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_URL", raising=False)
    assert stage_eligibility.stage_is_off("P5_ChunkEmbed", "dataset")
    assert stage_eligibility.stage_is_off("P6_IndexVectors", "dataset")

    monkeypatch.setenv("EMBEDDINGS_URL", "http://embeddings")
    assert not stage_eligibility.stage_is_off("P5_ChunkEmbed", "dataset")
    assert not stage_eligibility.stage_is_off("P6_IndexVectors", "dataset")
