-- segment_version names the split rule of a text row. Version 0 rows are one PDF page, or a
-- byte cut with no overlap. Version 1 rows are a page interval, or a white space cut with overlap.
ALTER TABLE text_content ADD COLUMN IF NOT EXISTS segment_version UInt16 DEFAULT 0;
