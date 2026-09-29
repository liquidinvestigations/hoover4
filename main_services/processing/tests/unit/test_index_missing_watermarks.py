"""The page indexer records one warning for missing NER watermarks."""

import logging

from tasks.P6_index_data import activities


def test_missing_ner_watermarks_write_one_activity_warning(monkeypatch, caplog):
    monkeypatch.setenv("NER_PROVIDER", "gpu")
    with caplog.at_level(logging.WARNING, logger=activities.log.name):
        activities.log_missing_ner_watermarks("dataset", "abcdefgh", 3, 5)
    records = [record for record in caplog.records if "no nlp_processed watermark" in record.message]
    assert len(records) == 1
    assert "3 of 5 segments" in records[0].message
