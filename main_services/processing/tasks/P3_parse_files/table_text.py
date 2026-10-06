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
