"""The email graph's normalisers and the three guards on its inferred edges.

The guards are the reason this file exists. Every one of them is tested with a fixture
that crosses its threshold by exactly one, because a guard that is off by one is a guard
that looks implemented and is not.
"""

from tasks.P6_index_data.email_graph import (
    INFERRED_CONFIDENCE,
    INFERRED_WINDOW_SECONDS,
    KIND_ATTACHMENT,
    KIND_FORWARD,
    KIND_IDENTITY,
    KIND_REPLY,
    MAX_MESSAGES_PER_SUBJECT,
    MIN_SUBJECT_NORM_LENGTH,
    EmailIdentity,
    build_all_edges,
    build_attachment_edges,
    build_identity_edges,
    build_inferred_edges,
    build_rfc_edges,
    connected_components,
    normalise_message_id,
    normalise_subject,
    split_message_ids,
    subject_prefix_kind,
)

DAY = 24 * 3600


def identity(
    email_hash,
    subject="Quarterly numbers",
    dataset="ds",
    message_id="",
    date_sent=1_000_000,
    date_sent_known=1,
    participants=("a@x.com", "b@x.com"),
):
    return EmailIdentity(
        collection_dataset=dataset,
        email_hash=email_hash,
        message_id=message_id,
        subject_norm=normalise_subject(subject),
        subject_prefix=subject_prefix_kind(subject),
        date_sent=date_sent,
        date_sent_known=date_sent_known,
        from_address=participants[0] if participants else "",
        participants=tuple(sorted(participants)),
    )


def test_subject_norm():
    assert normalise_subject("RE: Gingrich view") == "gingrich view"
    assert normalise_subject("Re: Gingrich view") == "gingrich view"
    assert normalise_subject("FW: Gingrich view") == "gingrich view"
    assert normalise_subject("Fwd: Gingrich view") == "gingrich view"
    assert normalise_subject("AW: Gingrich view") == "gingrich view"
    assert normalise_subject("WG: Gingrich view") == "gingrich view"
    # Repeated runs, mixed, with the spacing mail clients actually produce.
    assert normalise_subject("RE: FW: RE: x") == "x"
    assert normalise_subject("Re:Re:  FWD:   Deal  sheet ") == "deal sheet"
    assert normalise_subject("Re[2]: Deal sheet") == "deal sheet"
    # The colon is required: a subject that merely STARTS with the letters of a prefix
    # keeps its first word.
    assert normalise_subject("Reply requested by Friday") == "reply requested by friday"
    assert normalise_subject("Award ceremony") == "award ceremony"
    assert normalise_subject("Regarding the deal") == "regarding the deal"
    assert normalise_subject("") == ""
    assert normalise_subject("RE:") == ""


def test_subject_prefix_kind_reads_the_outermost_prefix():
    assert subject_prefix_kind("FW: RE: x") == KIND_FORWARD
    assert subject_prefix_kind("RE: FW: x") == KIND_REPLY
    assert subject_prefix_kind("Fwd: x") == KIND_FORWARD
    assert subject_prefix_kind("AW: x") == KIND_REPLY
    assert subject_prefix_kind("Reply requested") == ""
    assert subject_prefix_kind("") == ""


def test_normalise_message_id_and_splitting():
    assert normalise_message_id("<ABC@Enron.COM>") == "abc@enron.com"
    assert normalise_message_id("  abc@enron.com ") == "abc@enron.com"
    assert normalise_message_id("<>") == ""
    assert split_message_ids("<a@x> <B@Y>") == ["a@x", "b@y"]
    assert split_message_ids("bare@x") == ["bare@x"]
    assert split_message_ids("") == []


def test_identity_edges_connect_renditions_across_datasets():
    edges, _ = build_identity_edges([
        identity("h1", dataset="ds_a", message_id="m1"),
        identity("h2", dataset="ds_b", message_id="m1"),
        identity("h3", dataset="ds_c", message_id="other"),
        identity("h4", dataset="ds_d", message_id=""),
    ])
    assert [(e.src_dataset, e.dst_dataset, e.kind, e.confidence) for e in edges] == [
        ("ds_a", "ds_b", KIND_IDENTITY, 1.0)
    ]


def test_rfc_edges_point_from_the_referenced_message():
    child = identity("h2", message_id="m2", subject="RE: Quarterly numbers")
    edges, _ = build_rfc_edges(
        [identity("h1", message_id="m1"), child],
        {("ds", "h2"): [("In-Reply-To", "<M1>"), ("References", "<m1>")]},
    )
    kinds = {(e.src_hash, e.dst_hash, e.kind) for e in edges}
    assert kinds == {("h1", "h2", KIND_REPLY), ("h1", "h2", "reference")}


def test_attachment_edges_only_between_two_known_emails():
    edges, _ = build_attachment_edges(
        [identity("container"), identity("member")],
        [("ds", "container", "member"), ("ds", "container", "a-pdf"), ("ds", "container", "container")],
    )
    assert [(e.src_hash, e.dst_hash, e.kind) for e in edges] == [
        ("container", "member", KIND_ATTACHMENT)
    ]


class TestEmailEdgesGuards:
    """Each guard, with a fixture that crosses its threshold by exactly one."""

    def test_the_subject_cap_drops_the_whole_group_at_one_over(self):
        under = [
            identity(f"h{i}", subject="RE: Weekly report" if i else "Weekly report",
                     date_sent=1_000_000 + i)
            for i in range(MAX_MESSAGES_PER_SUBJECT)
        ]
        edges, stats = build_inferred_edges(under)
        assert edges, "a group exactly at the cap is kept"
        assert stats.dropped_busy_subjects == 0

        over = under + [identity("h_extra", subject="RE: Weekly report",
                                 date_sent=1_000_000 + MAX_MESSAGES_PER_SUBJECT)]
        edges, stats = build_inferred_edges(over)
        assert edges == [], "one message over the cap drops the entire subject"
        assert stats.dropped_busy_subjects == 1
        assert stats.dropped_busy_subject_messages == MAX_MESSAGES_PER_SUBJECT + 1

    def test_the_ninety_day_window_at_one_second_over(self):
        base = identity("h1", subject="Quarterly numbers", date_sent=1_000_000)
        inside = identity("h2", subject="RE: Quarterly numbers",
                          date_sent=1_000_000 + INFERRED_WINDOW_SECONDS)
        outside = identity("h3", subject="RE: Quarterly numbers",
                           date_sent=1_000_000 + INFERRED_WINDOW_SECONDS + 1)

        edges, _ = build_inferred_edges([base, inside])
        assert [(e.src_hash, e.dst_hash, e.kind, e.confidence) for e in edges] == [
            ("h1", "h2", KIND_REPLY, INFERRED_CONFIDENCE)
        ]

        edges, stats = build_inferred_edges([base, outside])
        assert edges == []
        assert stats.dropped_out_of_window == 1

    def test_the_empty_and_too_short_subject_rejection(self):
        short = "x" * MIN_SUBJECT_NORM_LENGTH
        long_enough = "x" * (MIN_SUBJECT_NORM_LENGTH + 1)

        edges, stats = build_inferred_edges([
            identity("h1", subject=short, date_sent=1_000_000),
            identity("h2", subject=f"RE: {short}", date_sent=1_000_100),
        ])
        assert edges == []
        assert stats.dropped_short_subject == 2

        edges, _ = build_inferred_edges([
            identity("h1", subject=long_enough, date_sent=1_000_000),
            identity("h2", subject=f"RE: {long_enough}", date_sent=1_000_100),
        ])
        assert len(edges) == 1

        # An empty subject is the same rejection, and it is the common case: a whole
        # corpus of subject-less autoreplies would otherwise be one component.
        edges, _ = build_inferred_edges([
            identity("h1", subject="", date_sent=1_000_000),
            identity("h2", subject="RE:", date_sent=1_000_100),
        ])
        assert edges == []

    def test_an_undated_message_never_gets_an_inferred_edge(self):
        edges, stats = build_inferred_edges([
            identity("h1", date_sent=0, date_sent_known=0),
            identity("h2", subject="RE: Quarterly numbers", date_sent=1_000_100),
        ])
        assert edges == []
        assert stats.dropped_undated == 1

    def test_participants_must_overlap(self):
        edges, stats = build_inferred_edges([
            identity("h1", participants=("a@x.com",), date_sent=1_000_000),
            identity("h2", subject="RE: Quarterly numbers", participants=("z@y.com",),
                     date_sent=1_000_100),
        ])
        assert edges == []
        assert stats.dropped_no_overlap == 1

    def test_the_later_message_must_carry_a_prefix(self):
        edges, stats = build_inferred_edges([
            identity("h1", date_sent=1_000_000),
            identity("h2", subject="Quarterly numbers", date_sent=1_000_100),
        ])
        assert edges == []
        assert stats.dropped_no_direction == 1

    def test_the_prefix_decides_the_kind(self):
        edges, _ = build_inferred_edges([
            identity("h1", date_sent=1_000_000),
            identity("h2", subject="FW: Quarterly numbers", date_sent=1_000_100),
        ])
        assert [e.kind for e in edges] == [KIND_FORWARD]

    def test_the_thresholds_are_tunable_rather_than_inlined(self):
        pair = [
            identity("h1", date_sent=1_000_000),
            identity("h2", subject="RE: Quarterly numbers", date_sent=1_000_000 + 10 * DAY),
        ]
        assert build_inferred_edges(pair)[0]
        assert build_inferred_edges(pair, window_seconds=DAY)[0] == []


def test_build_all_edges_deduplicates_and_reports_every_kind():
    child = identity("h2", dataset="ds_a", message_id="m2", subject="RE: Quarterly numbers",
                     date_sent=1_000_100)
    parent = identity("h1", dataset="ds_a", message_id="m1", date_sent=1_000_000)
    copy = identity("h1b", dataset="ds_b", message_id="m1", date_sent=1_000_000)
    edges, stats = build_all_edges(
        [parent, child, copy],
        # In-Reply-To twice: the same edge, stored once.
        {("ds_a", "h2"): [("In-Reply-To", "<m1>"), ("In-Reply-To", "<m1>")]},
        [],
    )
    keys = [(e.src_hash, e.dst_hash, e.kind) for e in edges]
    assert len(keys) == len(set(keys))
    assert stats.per_kind[KIND_IDENTITY] == 1


def test_connected_components_ignores_direction_and_skips_isolated_nodes():
    edges, _ = build_identity_edges([
        identity("h1", dataset="ds_a", message_id="m1"),
        identity("h2", dataset="ds_b", message_id="m1"),
    ])
    components = connected_components(edges)
    assert components[("ds_a", "h1")] == {("ds_a", "h1"), ("ds_b", "h2")}
    assert ("ds_c", "lonely") not in components


def test_connected_components_terminates_on_a_self_containing_email():
    """`eml-7-recursive` is an email that contains itself; a containment row from a hash
    to itself is therefore real input, not a hypothetical."""
    edges, _ = build_attachment_edges(
        [identity("self")], [("ds", "self", "self")],
    )
    assert edges == []
    assert connected_components(edges) == {}
