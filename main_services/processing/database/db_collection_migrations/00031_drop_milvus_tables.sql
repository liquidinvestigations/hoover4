-- Drop the Milvus alignment tables. Nothing ever wrote them: the pipeline has no
-- chunk+embed stage, so these three have been empty since 00023/00024 created them and
-- the Milvus tier that would have read them is gone (see ai_services/README.md).
--
-- 00023 and 00024 are left untouched on purpose. The migration runner stores an md5 per
-- applied file, so editing history breaks every deployment that already ran it. The
-- CREATEs stay and this DROP undoes them.
--
-- No semicolons above this line. The runner splits the file on the statement separator
-- without parsing SQL, so one inside a comment cuts the file in half and the leading
-- half reaches ClickHouse as an empty query.

DROP TABLE IF EXISTS text_chunks_milvus;
DROP TABLE IF EXISTS entity_hits_milvus;
DROP TABLE IF EXISTS entity_hits_milvus_unique;
