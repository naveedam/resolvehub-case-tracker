"""Regression test for the backfill's 'JSON could not be generated (400)'
failure: a large case_ids list passed straight to .in_() built a request
large enough for PostgREST/the transport in front of it to reject
outright. This uses a fake postgrest-like client (not InMemoryStore,
which has no URL-size constraint at all) that itself rejects any single
.in_() call over 200 ids — so this test would fail exactly the way
production did if IN_FILTER_CHUNK_SIZE chunking regressed.
"""

from __future__ import annotations

from ingestion.common.store import SupabaseStore


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows, calls_log):
        self._rows = rows
        self._calls_log = calls_log
        self._in_values = None

    def select(self, *_a, **_k):
        return self

    def in_(self, _col, values):
        if len(values) > 200:  # mirrors the real-world PostgREST/transport limit
            raise Exception("simulated postgrest.exceptions.APIError: JSON could not be generated (400 Bad Request)")
        self._calls_log.append(list(values))
        self._in_values = set(values)
        return self

    def is_(self, *_a, **_k):
        return self

    def execute(self):
        rows = [r for r in self._rows if r["case_id"] in self._in_values]
        return FakeResult(rows)


class FakeClient:
    def __init__(self, table_rows: dict[str, list[dict]]):
        self.calls_log: list[list[str]] = []
        self._table_rows = table_rows

    def table(self, name):
        return FakeQuery(self._table_rows.get(name, []), self.calls_log)


def test_list_liabilities_for_cases_chunks_large_id_lists():
    liabilities = [
        {"id": f"l{i}", "case_id": f"c{i}", "loan_type": "x", "account_number": None, "outstanding_amount": 1}
        for i in range(450)
    ]
    client = FakeClient({"liabilities": liabilities})
    store = SupabaseStore(client, retries=1)

    rows = store.list_liabilities_for_cases([f"c{i}" for i in range(450)])

    assert len(rows) == 450  # every row still retrieved despite chunking
    assert len(client.calls_log) == 3  # 200 + 200 + 50, not one call of 450
    assert all(len(chunk) <= 200 for chunk in client.calls_log)


def test_list_assets_and_documents_for_cases_also_chunk():
    assets = [{"id": f"a{i}", "case_id": f"c{i}", "description": None, "auction_date": None, "auction_status": None} for i in range(300)]
    documents = [{"id": f"d{i}", "case_id": f"c{i}"} for i in range(300)]
    client = FakeClient({"assets": assets, "documents": documents})
    store = SupabaseStore(client, retries=1)
    case_ids = [f"c{i}" for i in range(300)]

    asset_rows = store.list_assets_for_cases(case_ids)
    assert len(asset_rows) == 300
    assert all(len(chunk) <= 200 for chunk in client.calls_log)

    client.calls_log.clear()
    doc_rows = store.list_documents_for_cases(case_ids)
    assert len(doc_rows) == 300
    assert all(len(chunk) <= 200 for chunk in client.calls_log)


def test_empty_case_id_list_makes_no_request():
    client = FakeClient({"liabilities": []})
    store = SupabaseStore(client, retries=1)

    assert store.list_liabilities_for_cases([]) == []
    assert client.calls_log == []
