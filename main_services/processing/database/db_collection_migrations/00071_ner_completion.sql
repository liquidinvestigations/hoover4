ALTER TABLE nlp_processed ADD COLUMN IF NOT EXISTS stage_version UInt16 DEFAULT 1;
ALTER TABLE nlp_processed ADD COLUMN IF NOT EXISTS text_version UInt64 DEFAULT 0;
ALTER TABLE nlp_processed ADD COLUMN IF NOT EXISTS text_digest String DEFAULT '';
CREATE TABLE IF NOT EXISTS ner_completion_ready (ready UInt8) ENGINE = TinyLog;
