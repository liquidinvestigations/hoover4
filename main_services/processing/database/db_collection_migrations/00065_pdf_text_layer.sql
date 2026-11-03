-- The version of the invisible text layer in each searchable PDF part.
-- 1 is the Helvetica layer, which wrote a black square for each character outside Windows-1252.
-- 2 is the layer with a ToUnicode map, which keeps every character.
-- 0 marks a tombstone that the pdf_text update step wrote to build the part again.
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that character.
ALTER TABLE pdf_ocr_parts ADD COLUMN IF NOT EXISTS text_layer UInt8 DEFAULT 1
    COMMENT 'Text layer version: 1 Helvetica, 2 ToUnicode, 0 tombstone of a rebuild'
