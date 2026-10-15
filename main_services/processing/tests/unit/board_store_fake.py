"""An in-memory board database for the board command and activity tests.

`FakeBoardStore.install` replaces the readers and writers of `database.boards` and
`database.board_commands` with the semantics of the real tables: a row replaces the earlier
row of its key, a receipt keeps its highest version, and every read sees the final rows. The
clock advances one millisecond on each read of `now`, so every write has its own time.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from database import board_commands as bc
from database import boards

T0 = datetime(2026, 10, 14, 8, 0, 0)


class FakeBoardStore:
    def __init__(self):
        self.boards: dict[str, boards.BoardRow] = {}
        self.events: dict[tuple, boards.EventRow] = {}
        self.facts: dict[tuple, boards.FactRow] = {}
        self.citations: dict[tuple, boards.CitationRow] = {}
        self.labels: dict[tuple, boards.LabelRow] = {}
        self.inputs: dict[tuple, bc.CommandInput] = {}
        self.receipts: dict[tuple, bc.Receipt] = {}
        self.assessments: list[tuple] = []
        self.settings: dict[str, str] = {}
        self.ticks = 0
        #: Raise from the next writer of this name, once. A test sets it to cut a command.
        self.fail_on = ""

    # ------------------------------------------------------------------ the clock

    def now(self) -> datetime:
        self.ticks += 1
        return T0 + timedelta(milliseconds=self.ticks)

    def _check(self, name: str) -> None:
        if self.fail_on == name:
            self.fail_on = ""
            raise RuntimeError(f"the test cut the write of {name}")

    # ------------------------------------------------------------------- boards

    def add_board(self, board_id: str, owner: str = "admin", **kw) -> boards.BoardRow:
        values = dict(owner=owner, title="t", goal="g", collections=["enron"], created_at=T0)
        values.update(kw)
        self.boards[board_id] = boards.BoardRow(board_id=board_id, **values)
        return self.boards[board_id]

    def read_live_boards(self):
        return sorted((b for b in self.boards.values() if not b.is_deleted), key=lambda b: b.created_at)

    def read_board(self, board_id):
        return self.boards.get(board_id)

    def board_is_live(self, board_id):
        board = self.boards.get(board_id)
        return board is not None and not board.is_deleted

    # ------------------------------------------------------------------- events

    def read_events(self, board_id):
        rows = [e for (b, _), e in self.events.items() if b == board_id]
        return sorted(rows, key=lambda e: (e.created_at, e.event_id))

    def write_events(self, rows):
        self._check("write_events")
        for e in rows:
            self.events[(e.board_id, e.event_id)] = replace(e, created_at=e.created_at or self.now())

    def write_event(self, event):
        self.write_events([event])

    def write_assessment(self, *args):
        self.assessments.append(args)

    # -------------------------------------------------------------------- facts

    def read_facts(self, board_id):
        rows = [f for (b, _), f in self.facts.items() if b == board_id]
        return sorted(rows, key=lambda f: (f.created_at or T0, f.fact_id))

    def publish_facts(self, facts, citations):
        self._check("publish_facts")
        for c in citations:
            self.citations[(c.board_id, c.fact_id, c.label)] = c
        for f in facts:
            self.facts[(f.board_id, f.fact_id)] = replace(f, created_at=f.created_at or self.now())

    def facts_of_intent(self, board_id, intent_id):
        return [f for f in self.read_facts(board_id) if f.intent_id == intent_id]

    def read_citations(self, board_id):
        return sorted((c for (b, _, _), c in self.citations.items() if b == board_id),
                      key=lambda c: (c.fact_id, c.label))

    # ------------------------------------------------------------------- labels

    def read_labels(self, board_ids):
        return sorted((r for (b, _), r in self.labels.items() if b in board_ids),
                      key=lambda r: (r.board_id, r.node_id))

    def write_labels(self, rows):
        self._check("write_labels")
        for r in rows:
            stamp = r.updated_at or self.now()
            old = self.labels.get((r.board_id, r.node_id))
            if old is not None and old.updated_at and old.updated_at > stamp:
                continue
            self.labels[(r.board_id, r.node_id)] = replace(r, created_at=r.created_at or stamp, updated_at=stamp)

    # ------------------------------------------------------------------ commands

    def submit(self, board_id, request_id, kind, actor, body):
        value = bc.digest(body)
        key = (board_id, request_id, value)
        if key not in self.inputs:
            self.inputs[key] = bc.CommandInput(board_id, request_id, value, actor, kind,
                                               dict(body), self.now())
        return value

    def read_inputs(self, board_id):
        rows = [i for (b, _, _), i in self.inputs.items() if b == board_id]
        return sorted(rows, key=lambda i: (i.submitted_at, i.request_id, i.payload_digest))

    def read_receipts(self, board_id):
        return {r: rec for (b, r), rec in self.receipts.items() if b == board_id}

    def write_receipt(self, receipt):
        self._check(f"receipt_{receipt.state}")
        key = (receipt.board_id, receipt.request_id)
        old = self.receipts.get(key)
        version = bc.PHASE[receipt.state]
        if old is not None and old.version > version:
            return
        self.receipts[key] = replace(receipt, version=version, prepared=dict(receipt.prepared),
                                     result=dict(receipt.result), created_at=receipt.created_at or self.now(),
                                     updated_at=self.now())

    def pending_commands(self, board_ids):
        decided = {k for k, r in self.receipts.items() if r.state in (bc.COMMITTED, bc.REJECTED)}
        out = {}
        for (b, r, _), i in self.inputs.items():
            if b in board_ids and (b, r) not in decided:
                out.setdefault((b, r), i.kind)
        return [(b, r, kind) for (b, r), kind in out.items()]

    def states(self, requests):
        submitted = {(b, r) for (b, r, _) in self.inputs}
        out = {}
        for key in requests:
            receipt = self.receipts.get(key)
            out[key] = receipt.state if receipt else (bc.PENDING if key in submitted else bc.UNKNOWN)
        return out

    # ------------------------------------------------------------------- install

    def install(self, monkeypatch):
        from database import clickhouse

        for name in ("read_live_boards", "read_board", "board_is_live", "read_events", "write_events",
                     "write_event", "write_assessment", "read_facts", "publish_facts", "facts_of_intent",
                     "read_citations", "read_labels", "write_labels", "now"):
            monkeypatch.setattr(boards, name, getattr(self, name))
        monkeypatch.setattr(boards, "read_state_rows", lambda b: (None, {}))
        monkeypatch.setattr(boards, "write_state", lambda s, i: None)
        for name in ("submit", "read_inputs", "read_receipts", "write_receipt", "pending_commands", "states"):
            monkeypatch.setattr(bc, name, getattr(self, name))
        monkeypatch.setattr(clickhouse, "get_server_setting", lambda key: self.settings.get(key))
        return self

    def run_commands(self, board_id: str, limit: int = 100) -> int:
        """Run the command writer of a board until it has no command left."""
        from tasks.P_board.commands import step

        handled = 0
        while handled < limit and step(board_id):
            handled += 1
        return handled
