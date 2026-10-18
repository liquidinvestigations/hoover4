"""Images in tool results: the references, the cost estimate, the request parts, the cache
check, the model without images, and the images of a compaction."""

import io
import json
from types import SimpleNamespace

import httpx
import pytest

from research_agent import compaction, images, request_size
from research_agent.run_messages import RunMessage, to_langchain
from test_thread_index import DGEMMA, EST, Thread, chars, ok

DOC = {"kind": "document", "collection": "c", "file_hash": "h" * 64, "label": "scan.png",
       "width": 3136, "height": 1568}
PAGE = {"kind": "capture", "artifact_id": "a1", "label": "Lease (https://x.org)",
        "width": 1280, "height": 720}


def _resource(uri, value):
    return SimpleNamespace(resource=SimpleNamespace(uri=uri, text=json.dumps(value)))


def test_the_references_are_read_from_the_artifact():
    other = _resource("hoover4://doc-refs", [{"file_hash": "x"}])
    assert images.image_refs_of([other, _resource(images.IMAGE_REFS_URI, [DOC, "bad"])]) == [DOC]
    assert images.image_refs_of([other]) is None
    assert images.image_refs_of(None) is None


def test_the_cost_is_the_area_after_the_side_limit():
    # 3136 x 1568 becomes 1568 x 784: 49 x 25 squares of 32 pixels.
    assert images.ref_tokens(DOC) == 49 * 25 + images.IMAGE_FRAME_TOKENS
    assert images.ref_tokens(PAGE) == 40 * 23 + images.IMAGE_FRAME_TOKENS
    assert images.ref_tokens({"kind": "capture"}) == 49 * 49 + images.IMAGE_FRAME_TOKENS


def test_an_image_only_row_counts_in_the_estimate_and_the_request_size():
    row = RunMessage(role="tool", content="", tool_call_id="c", name="read_page", image_refs=[PAGE])
    assert EST.tokens(row) == EST.tokens(row.model_copy(update={"image_refs": []})) + images.ref_tokens(PAGE)

    class Counter:
        def count(self, text):
            return 100

    size = request_size.measure("s", "[]", [row], model_id="m", window=10_000,
                                counter_for=lambda model_id: Counter())
    assert size.method == "tokenizer"
    assert size.tokens == 100 + request_size.MESSAGE_FRAME_TOKENS + images.ref_tokens(PAGE)


def test_a_model_without_images_reads_the_note_and_counts_no_image():
    row = RunMessage(role="tool", content="text", tool_call_id="c", name="read_page", image_refs=[PAGE])
    hidden = images.hide([row])[0]
    assert hidden.image_refs == []
    assert hidden.content == "text\n\n" + images.NO_VISION_TEXT
    assert images.list_tokens([hidden]) == 0


def test_the_image_parts_follow_the_text_of_the_result():
    rows = [RunMessage(role="human", content="q"),
            RunMessage(role="ai", content="", tool_calls=[{"id": "c", "name": "read_page"}]),
            RunMessage(role="tool", content="page text", tool_call_id="c", name="read_page",
                       image_refs=[PAGE, DOC])]
    parts = {2: images.parts("page text", [PAGE, DOC],
                             [images.Loaded(data_url="data:image/png;base64,AA"),
                              images.Loaded(reason="the image format cannot be decoded")])}
    message = to_langchain(rows, parts)[2]
    assert message.content == [
        {"type": "text", "text": "page text"},
        {"type": "text", "text": "Image: read_page screenshot of Lease (https://x.org)"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
        {"type": "text", "text": "Image not attached: image document scan.png: "
                                 "the image format cannot be decoded"},
    ]
    assert to_langchain(rows)[2].content == "page text"


class FakeClient:
    """Answers each image request from a list of responses and records the headers."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, json=None, headers=None):
        self.requests.append((url, json, dict(headers or {})))
        return self.responses.pop(0)


def _png(width, height, color=(200, 10, 10)):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


def test_a_cached_image_is_sent_only_after_the_website_checks_access(monkeypatch):
    pytest.importorskip("PIL")
    monkeypatch.setattr(images, "_cache", images._Cache(images.CACHE_BYTES))
    first = httpx.Response(200, content=_png(40, 20), headers={"etag": '"capture-a1"'})
    client = FakeClient(first, httpx.Response(304),
                        httpx.Response(403, json={"error": "permission_denied",
                                                  "message": "the capture belongs to another user"}))
    loaded = images.load(PAGE, username="u", collections=["c"], client=client)
    assert loaded.data_url.startswith("data:image/png;base64,")
    assert images.load(PAGE, username="u", collections=["c"], client=client) == loaded
    refused = images.load(PAGE, username="u", collections=["c"], client=client)
    assert refused == images.Loaded(reason="the image could not be read: the capture belongs to another user")
    url, body, headers = client.requests[1]
    assert url.endswith("/api/agent/v1/images/capture") and body == {"artifact_id": "a1"}
    assert headers["If-None-Match"] == '"capture-a1"' and headers["x-hoover4-user"] == "u"
    assert "If-None-Match" not in client.requests[0][2]


def test_a_document_image_is_read_with_the_collections_of_the_run(monkeypatch):
    monkeypatch.setattr(images, "_cache", images._Cache(images.CACHE_BYTES))
    client = FakeClient(httpx.Response(404, json={"message": "the document has no image"}))
    loaded = images.load(DOC, username="u", collections=["c", "d"], client=client)
    assert loaded.reason == "the image could not be read: the document has no image"
    url, body, headers = client.requests[0]
    assert url.endswith("/images/document") and body == {"collectionname": "c", "file_hash": DOC["file_hash"]}
    assert headers["X-Hoover4-Collections"] == "c,d"


def test_preparation_keeps_both_limits_and_names_an_unreadable_format():
    pytest.importorskip("PIL")
    from PIL import Image

    data, media_type = images.prepare(_png(4000, 1000))
    image = Image.open(io.BytesIO(data))
    assert media_type == "image/png" and max(image.size) == images.MAX_SIDE
    noise = Image.effect_noise((3000, 3000), 120).convert("RGB")
    buffer = io.BytesIO()
    noise.save(buffer, "BMP")
    data, media_type = images.prepare(buffer.getvalue())
    assert media_type == "image/jpeg" and len(data) <= images.MAX_BYTES
    assert max(Image.open(io.BytesIO(data)).size) <= images.MAX_SIDE
    with pytest.raises(images.ImageError, match="SVG"):
        images.prepare(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>')
    with pytest.raises(images.ImageError, match="cannot be decoded"):
        images.prepare(b"not an image")


# ------------------------------------------------------------------------ compaction


def _image_thread():
    t = Thread()
    t.human("Who signed the lease?")
    t.step(ok("read_page", {"urls": ["https://x.org"]}, chars(20_000)))
    t.rows[-1].image_refs = [PAGE]
    t.step(ok("read_documents", {"file_hash": ["h"]}, chars(150_000)))
    t.rows[-1].image_refs = [DOC]
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=230_000)
    return t


def test_the_plan_names_each_replaced_image_and_keeps_room_for_it():
    t = _image_thread()
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      username="u", collections=["c"])
    assert plan.images == [PAGE, DOC]
    assert plan.image_room == images.ref_tokens(PAGE) + images.ref_tokens(DOC)
    assert plan.index.endswith("Image 1: read_page screenshot of Lease (https://x.org)\n"
                               "Image 2: image document scan.png")
    assert (plan.username, plan.collections) == ("u", ["c"])


def test_the_summary_request_sends_the_images_after_their_labels(monkeypatch):
    t = _image_thread()
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST)
    sent = []
    monkeypatch.setattr(images, "supports_vision", lambda model: True)
    monkeypatch.setattr(images, "load_all", lambda refs, **k: [
        images.Loaded(data_url=f"data:image/png;base64,{n}") for n, _ in enumerate(refs)])
    monkeypatch.setattr(compaction, "_summary_request",
                        lambda content, **k: sent.append(content) or (200, "## Findings\nx"))
    _out, report = compaction.finish_compaction(plan)
    assert report.status == "ok" and len(sent) == 1
    content = sent[0]
    assert content[0]["text"].endswith(compaction.IMAGES_LINE)
    assert [p["type"] for p in content[1:]] == ["text", "image_url", "text", "image_url"]
    assert content[3]["text"] == "Image 2: image document scan.png"


def test_a_refusal_of_the_images_sends_the_labels_once(monkeypatch):
    t = _image_thread()
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST)
    answers = [(400, ""), (200, "## Findings\nlabels")]
    sent = []
    monkeypatch.setattr(images, "supports_vision", lambda model: True)
    monkeypatch.setattr(images, "load_all", lambda refs, **k: [
        images.Loaded(data_url="data:image/png;base64,AA") for _ in refs])
    monkeypatch.setattr(compaction, "_summary_request",
                        lambda content, **k: sent.append(content) or answers.pop(0))
    _out, report = compaction.finish_compaction(plan)
    assert report.status == "ok" and len(sent) == 2
    assert isinstance(sent[1], str) and compaction.IMAGE_LABELS_LINE in sent[1]
    assert "Image 2: image document scan.png" in sent[1]


def test_a_summary_model_without_images_reads_the_labels(monkeypatch):
    t = _image_thread()
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST)
    sent = []
    monkeypatch.setattr(images, "supports_vision", lambda model: False)
    monkeypatch.setattr(compaction, "_summary_request",
                        lambda content, **k: sent.append(content) or (200, "## Findings\nx"))
    compaction.finish_compaction(plan)
    assert len(sent) == 1 and compaction.IMAGE_LABELS_LINE in sent[0]


def test_images_that_do_not_fit_go_in_later_requests(monkeypatch):
    t = _image_thread()
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST)
    plan.image_room = images.ref_tokens(PAGE)
    sent = []
    monkeypatch.setattr(images, "supports_vision", lambda model: True)
    monkeypatch.setattr(images, "load_all", lambda refs, **k: [
        images.Loaded(data_url="data:image/png;base64,AA") for _ in refs])
    answers = [(200, "## Findings\nx"), (200, "Image 2: image document scan.png: a signature")]
    monkeypatch.setattr(compaction, "_summary_request",
                        lambda content, **k: sent.append(content) or answers.pop(0))
    _out, report = compaction.finish_compaction(plan)
    assert len(sent) == 2
    assert sent[1][1]["text"] == "Image 2: image document scan.png"
    assert report.summary.endswith("## Findings\nx\nImage 2: image document scan.png: a signature")
