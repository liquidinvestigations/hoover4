"""Build bounded text segments from accepted SQLite cells."""


class TableText:
    """Keep sheet and source row labels while omitting binary cell values."""

    def __init__(self, max_characters: int = 20_000_000, segment_bytes: int = 256 * 1024):
        self.max_characters = max_characters
        self.segment_bytes = segment_bytes
        self.characters = 0
        self.truncated = False
        self.segments = []
        self.buffer = ""
        self.sheet_id = None
        self.source_row = None
        self.row_cells = []

    def _append(self, text: str) -> None:
        room = self.max_characters - self.characters
        if len(text) > room:
            text = text[:room]
            self.truncated = True
        self.characters += len(text)
        data = (self.buffer + text).encode("utf-8")
        while len(data) >= self.segment_bytes:
            segment = data[:self.segment_bytes].decode("utf-8", errors="ignore")
            self.segments.append(segment)
            data = data[len(segment.encode("utf-8")):]
        self.buffer = data.decode("utf-8")

    def _flush_row(self) -> None:
        if self.row_cells:
            self._append(f"{self.source_row}\t" + "\t".join(self.row_cells) + "\n")
            self.row_cells = []

    def add(self, sheet_id: int, sheet_name: str, cell, text: str) -> None:
        if self.characters >= self.max_characters:
            self.truncated = True
            return
        if sheet_id != self.sheet_id:
            self._flush_row()
            self.sheet_id = sheet_id
            self.source_row = None
            self._append("[" + sheet_name.replace("\n", " ").replace("\r", " ") + "]\n")
        if cell.source_row != self.source_row:
            self._flush_row()
            self.source_row = cell.source_row
        value = "" if cell.is_blob else text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
        self.row_cells.append(value)

    def pages(self) -> list[tuple[int, str]]:
        self._flush_row()
        if self.buffer:
            self.segments.append(self.buffer)
            self.buffer = ""
        return list(enumerate(self.segments, start=1))


def text_identity(pages) -> tuple[int, str]:
    """Identify the complete normalized table text, including an empty source."""
    import hashlib
    from tasks.P3_parse_files.parse_common import stored_page_bodies
    rows = sorted(stored_page_bodies(pages))
    digest = hashlib.sha256()
    for page, text in rows:
        body = text.encode("utf-8")
        digest.update(f"{page}:{len(body)}:".encode())
        digest.update(body)
    return len(rows), digest.hexdigest()


def stored_text_identity(client, dataset: str, file_hash: str) -> tuple[int, str]:
    """Read the complete stored page identity without returning text bodies."""
    from tasks.text_sources import TABLE_TEXT
    rows = client.query(
        "SELECT count(), lower(hex(SHA256(arrayStringConcat(arrayMap(item -> "
        "concat(toString(item.1), ':', toString(length(item.2)), ':', item.2), "
        "arraySort(groupArray((page_id, body)))), '')))) FROM ("
        "SELECT page_id, argMax(text, version) AS body FROM text_content "
        "WHERE collection_dataset = {dataset:String} AND file_hash = {hash:String} "
        "AND extracted_by = {source:String} GROUP BY page_id)",
        parameters={"dataset": dataset, "hash": file_hash, "source": TABLE_TEXT}).result_rows
    return int(rows[0][0]), str(rows[0][1])


def complete_table_text(client, dataset: str, file_hash: str, generation: int) -> bool:
    """Verify the required text manifest of a published SQLite reading."""
    rows = client.query(
        "SELECT reader, text_complete, text_page_count, text_digest FROM table_documents FINAL "
        "WHERE collection_dataset = {dataset:String} AND hash = {hash:String} "
        "AND generation = {generation:UInt32} AND status IN ('ok', 'empty') LIMIT 1",
        parameters={"dataset": dataset, "hash": file_hash, "generation": generation}).result_rows
    if not rows:
        return False
    reader, complete, count, digest = rows[0]
    return reader != "sqlite" or (bool(complete) and stored_text_identity(client, dataset, file_hash) == (int(count), digest))
