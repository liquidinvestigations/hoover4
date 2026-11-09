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


def test_ocr_stages_need_only_an_endpoint(monkeypatch):
    import tasks.dataset_config as dataset_config

    def no_settings_read(*_args, **_kwargs):
        raise AssertionError("an OCR language setting was read")

    monkeypatch.setattr(dataset_config, "get_dataset_settings", no_settings_read)
    monkeypatch.setattr(stage_eligibility, "engine_configured", lambda engine: engine == "tesseract")
    monkeypatch.setattr(stage_eligibility, "service_configured", lambda: True)
    monkeypatch.setattr(stage_eligibility, "engines_for_provider", lambda: ["tesseract"])

    assert not stage_eligibility.stage_is_off("run_ocr_and_store[tesseract]", "dataset")
    assert stage_eligibility.stage_is_off("run_ocr_and_store[easyocr]", "dataset")
    assert not stage_eligibility.stage_is_off("make_image_pdf[tesseract]", "dataset")
    assert stage_eligibility.stage_is_off("make_image_pdf[easyocr]", "dataset")
    assert not stage_eligibility.stage_is_off("run_ocr_pdf_and_store[tesseract]", "dataset")
    assert stage_eligibility.stage_is_off("run_ocr_pdf_and_store[easyocr]", "dataset")


def test_embeddings_stages_follow_the_endpoint(monkeypatch):
    import tasks.dataset_config as dataset_config
    monkeypatch.setattr(dataset_config, "get_dataset_settings", lambda _key: {})
    monkeypatch.setattr(dataset_config, "collection_of_dataset", lambda _cd: "")
    monkeypatch.delenv("EMBEDDINGS_URL", raising=False)
    assert stage_eligibility.stage_is_off("P5_ChunkEmbed", "dataset")
    assert stage_eligibility.stage_is_off("P6_IndexVectors", "dataset")

    monkeypatch.setenv("EMBEDDINGS_URL", "http://embeddings")
    assert not stage_eligibility.stage_is_off("P5_ChunkEmbed", "dataset")
    assert not stage_eligibility.stage_is_off("P6_IndexVectors", "dataset")
