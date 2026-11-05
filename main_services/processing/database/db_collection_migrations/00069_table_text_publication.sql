ALTER TABLE table_documents ADD COLUMN IF NOT EXISTS text_digest String DEFAULT '' COMMENT 'Complete SQLite table text digest';
ALTER TABLE table_documents ADD COLUMN IF NOT EXISTS text_page_count UInt32 DEFAULT 0 COMMENT 'Expected SQLite text page count';
ALTER TABLE table_documents ADD COLUMN IF NOT EXISTS text_complete UInt8 DEFAULT 0 COMMENT 'Complete SQLite text manifest is published';
CREATE TABLE IF NOT EXISTS table_text_publication_ready (ok UInt8) ENGINE = TinyLog
