"""Manticore Search connection helpers and schema migrations."""

from contextlib import contextmanager
import logging

log = logging.getLogger(__name__)


@contextmanager
def get_manticore_client():
    import mysql.connector
    cnx = mysql.connector.connect(
        host="manticore",
        port=9306,
        user="manticore",
        password="manticore", database='Manticore')
    try:
        yield cnx
    finally:
        try:
            cnx.close()
        except Exception as e:
            log.error(f"Error closing Manticore connection: {e}")
            pass


def check_manticore_health():
    log.info("Checking ManticoreSearch health...")
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        cur.execute("SELECT CURDATE()")
        row = cur.fetchone()
        log.info("MANTICORE OK - Current date is: {0}".format(row[0]))
        return row[0]

def _execute_migration_sql(sql):
    with get_manticore_client() as cnx:
        log.info("Manticore Execute Migration SQL: {}".format(sql))
        cur = cnx.cursor()
        cur.execute(sql)
        cnx.commit()
        log.info("SQL Executed OK.")

def create_manticore_doc_tables():
    # doc_text_pages - many rows for single document, each with about 300k of text. To be joined with doc_metadata on file_hash and collection_dataset.
    _execute_migration_sql("""
        create table if not exists doc_text_pages(
            collection_dataset string,
            file_hash string,
            extracted_by string,
            page_id int,
            page_text text,
            ner_per multi64,
            ner_org multi64,
            ner_loc multi64,
            ner_misc multi64
        ) engine='columnar'
    """)

    # doc_metadata - one row per document, with metadata about the document. To be joined with doc_text_pages on file_hash and collection_dataset.
    _execute_migration_sql("""
        create table if not exists doc_metadata(
            collection_dataset string,
            file_hash string,
            file_types multi64,
            file_mime_types multi64,
            file_extensions multi64,
            file_paths multi64,
            filenames text,
            metadata_values text
        ) engine='columnar'
    """)


def manticore_migrate():
    check_manticore_health()
    log.info("Starting ManticoreSearch migration....")
    create_manticore_doc_tables()
    log.info("ManticoreSearch migration OK.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manticore_migrate()