//! What the email viewer and the connection graph exchange with the server.
//!
//! Two shapes, and they answer different questions:
//!
//! * [`EmailEnvelope`] is everything above the message body in the viewer (the parent
//!   banner, the participant lines, the attachment cards) assembled in ONE round trip
//!   because they all describe the same message and four resources would mean four
//!   loading states on one card.
//! * [`EmailGraph`] is a bounded neighbourhood of one message: the nodes a page can draw
//!   and the edges between them, already truncated to the render budget server-side.
//!
//! Both carry provenance rather than a verdict. An edge keeps its `kind` and its
//! `confidence` all the way to the browser, because the interface has to draw a guess
//! differently from a fact, an interface that draws wrong connections confidently is
//! worse than no interface.

use serde::{Deserialize, Serialize};

use crate::search_result::DocumentIdentifier;

/// One person on a message.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EmailParty {
    /// Lower-cased `local@domain`, empty when the header carried a display name only.
    pub address: String,
    /// As written in the header; empty when absent.
    pub display_name: String,
}

impl EmailParty {
    /// `Terry Kafka <t.kafka@example.com>`, or the bare address when there is no name.
    pub fn full(&self) -> String {
        if self.display_name.is_empty() {
            self.address.clone()
        } else {
            format!("{} <{}>", self.display_name, self.address)
        }
    }

    /// The compact form for the collapsed recipient line: the first word of the display
    /// name, or the address' local part when there is no display name.
    ///
    /// First word rather than the whole name because the collapsed line shows six of
    /// them and the mockup reads `to jeffrey E., Trump, Hilary, John, Dave, Steve`.
    pub fn short(&self) -> String {
        if !self.display_name.is_empty() {
            let first = self.display_name.split_whitespace().next().unwrap_or("");
            if !first.is_empty() {
                return first.trim_matches(['"', '\'']).to_string();
            }
        }
        self.address
            .split_once('@')
            .map_or(self.address.clone(), |(local, _)| local.to_string())
    }
}

/// One attachment card.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EmailAttachment {
    pub file_name: String,
    pub size_bytes: u64,
    pub document_identifier: DocumentIdentifier,
    /// A coarse label for the icon: `pdf`, `image`, `email`, `archive`, `text`, or empty.
    pub coarse_type: String,
}

impl EmailAttachment {
    /// `310 KB`. Binary-free and deliberately coarse: the card has one grey line for it.
    pub fn size_label(&self) -> String {
        const UNITS: [(&str, u64); 4] =
            [("GB", 1_000_000_000), ("MB", 1_000_000), ("KB", 1_000), ("B", 1)];
        for (unit, scale) in UNITS {
            if self.size_bytes >= scale {
                let whole = self.size_bytes / scale;
                return format!("{whole} {unit}");
            }
        }
        "0 B".to_string()
    }
}

/// The message this one answers or forwards, for the banner above the envelope.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EmailRelation {
    pub document_identifier: DocumentIdentifier,
    pub subject: String,
    pub from_display: String,
    pub date_sent: Option<i64>,
    /// `reply`, `forward`, `reference`, `identity` or `attachment`.
    pub kind: String,
    /// 1.0 when an exact key produced this, below 1 when it was inferred.
    pub confidence: f32,
}

impl EmailRelation {
    /// `Forward of` / `Reply to` / `Attached to`, matching the banner in the mockup.
    pub fn banner_verb(&self) -> &'static str {
        match self.kind.as_str() {
            "forward" => "Forward of",
            "reply" => "Reply to",
            "attachment" => "Attached to",
            "identity" => "Same message as",
            _ => "In reference to",
        }
    }

    pub fn is_inferred(&self) -> bool {
        self.confidence < 1.0
    }
}

/// Everything the viewer draws above the message body.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct EmailEnvelope {
    pub subject: String,
    /// `None` when the `Date:` header never parsed, never the epoch.
    pub date_sent: Option<i64>,
    pub from: Vec<EmailParty>,
    pub to: Vec<EmailParty>,
    pub cc: Vec<EmailParty>,
    pub bcc: Vec<EmailParty>,
    pub attachments: Vec<EmailAttachment>,
    /// The banner. `None` when nothing points at this message.
    pub parent: Option<EmailRelation>,
    /// The TRUE size of this message's connected component, not the render budget.
    /// 0 or 1 hides the connection graph button.
    pub cluster_size: u32,
}

/// How many recipients the collapsed line names before it says `and N more.`
pub const COLLAPSED_RECIPIENT_LIMIT: usize = 6;

impl EmailEnvelope {
    pub fn has_connections(&self) -> bool {
        self.cluster_size > 1
    }

    /// `jeffrey E., Trump, Hilary, John, Dave, Steve, and 2 more.`
    ///
    /// Returns `None` when there are no recipients at all, so the caller renders nothing
    /// rather than an empty `to `.
    pub fn collapsed_recipients(&self) -> Option<String> {
        let everyone: Vec<&EmailParty> =
            self.to.iter().chain(self.cc.iter()).chain(self.bcc.iter()).collect();
        if everyone.is_empty() {
            return None;
        }
        let shown: Vec<String> =
            everyone.iter().take(COLLAPSED_RECIPIENT_LIMIT).map(|p| p.short()).collect();
        let hidden = everyone.len().saturating_sub(shown.len());
        if hidden == 0 {
            Some(format!("{}.", shown.join(", ")))
        } else {
            Some(format!("{}, and {hidden} more.", shown.join(", ")))
        }
    }

    /// `cc 1, bcc 2`, counts for the non-empty secondary roles only, so a message with
    /// no Cc does not render `cc 0`.
    pub fn secondary_counts(&self) -> String {
        let mut parts = Vec::new();
        if !self.cc.is_empty() {
            parts.push(format!("cc {}", self.cc.len()));
        }
        if !self.bcc.is_empty() {
            parts.push(format!("bcc {}", self.bcc.len()));
        }
        parts.join(", ")
    }
}

/// One message in the graph.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EmailGraphNode {
    pub document_identifier: DocumentIdentifier,
    pub subject: String,
    pub from_display: String,
    /// Epoch seconds. Meaningless unless `date_sent_known`.
    pub date_sent: i64,
    /// 0 means the `Date:` header never parsed. Such a node is pinned at the centre of
    /// the time axis and drawn dimmed: "we do not know when" has to be visible, not
    /// silently placed in 1970.
    pub date_sent_known: bool,
    /// The budget stopped this node from being expanded, so it has neighbours the graph
    /// is not showing.
    pub truncated: bool,
    /// The message the graph was opened on.
    pub is_centre: bool,
}

/// One edge in the graph, in the direction it is drawn.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EmailGraphEdge {
    pub src: DocumentIdentifier,
    pub dst: DocumentIdentifier,
    /// `identity`, `reply`, `forward`, `attachment` or `reference`.
    pub kind: String,
    pub confidence: f32,
    pub evidence: String,
}

impl EmailGraphEdge {
    /// Inferred edges are drawn dashed. That difference is the entire reason confidence
    /// is stored rather than discarded at write time.
    pub fn is_inferred(&self) -> bool {
        self.confidence < 1.0
    }
}

/// A bounded neighbourhood of one message.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct EmailGraph {
    pub nodes: Vec<EmailGraphNode>,
    pub edges: Vec<EmailGraphEdge>,
    /// The true size of the component, so the page can say how much it is not showing.
    pub cluster_size: u32,
    /// The budget stopped the walk before the component was exhausted.
    pub truncated: bool,
}

/// Node budget for one graph page. Clamped server-side: a client asking for more gets
/// this.
pub const MAX_GRAPH_NODES: u32 = 50;
/// Hops from the centre. Clamped server-side for the same reason.
pub const MAX_GRAPH_DEPTH: u32 = 3;

#[cfg(test)]
mod tests {
    use super::*;

    fn party(display_name: &str, address: &str) -> EmailParty {
        EmailParty { address: address.to_string(), display_name: display_name.to_string() }
    }

    #[test]
    fn a_party_shortens_to_a_first_name_or_a_local_part() {
        assert_eq!(party("Terry Kafka", "t@x.com").short(), "Terry");
        assert_eq!(party("", "e.brandt@blakelaw.net").short(), "e.brandt");
        assert_eq!(party("\"Jeffrey E\"", "j@x.com").short(), "Jeffrey");
        assert_eq!(party("", "nodomain").short(), "nodomain");
    }

    #[test]
    fn the_collapsed_line_caps_at_six_and_counts_the_rest() {
        let mut envelope = EmailEnvelope::default();
        envelope.to = (0..8).map(|i| party("", &format!("p{i}@x.com"))).collect();
        assert_eq!(
            envelope.collapsed_recipients().unwrap(),
            "p0, p1, p2, p3, p4, p5, and 2 more."
        );

        envelope.to.truncate(2);
        assert_eq!(envelope.collapsed_recipients().unwrap(), "p0, p1.");

        envelope.to.clear();
        assert_eq!(envelope.collapsed_recipients(), None);
    }

    #[test]
    fn secondary_counts_omit_empty_roles() {
        let mut envelope = EmailEnvelope::default();
        assert_eq!(envelope.secondary_counts(), "");
        envelope.bcc = vec![party("", "a@x.com"), party("", "b@x.com")];
        assert_eq!(envelope.secondary_counts(), "bcc 2");
        envelope.cc = vec![party("", "c@x.com")];
        assert_eq!(envelope.secondary_counts(), "cc 1, bcc 2");
    }

    #[test]
    fn attachment_sizes_read_as_the_mockup_does() {
        let mut attachment = EmailAttachment {
            file_name: "ExamplePDF1.pdf".to_string(),
            size_bytes: 310_000,
            document_identifier: DocumentIdentifier {
                collection_dataset: "ds".to_string(),
                file_hash: "h".to_string(),
            },
            coarse_type: "pdf".to_string(),
        };
        assert_eq!(attachment.size_label(), "310 KB");
        attachment.size_bytes = 0;
        assert_eq!(attachment.size_label(), "0 B");
        attachment.size_bytes = 999;
        assert_eq!(attachment.size_label(), "999 B");
    }

    #[test]
    fn an_inferred_edge_says_so() {
        let exact = EmailGraphEdge {
            src: DocumentIdentifier { collection_dataset: "a".into(), file_hash: "1".into() },
            dst: DocumentIdentifier { collection_dataset: "a".into(), file_hash: "2".into() },
            kind: "identity".into(),
            confidence: 1.0,
            evidence: String::new(),
        };
        assert!(!exact.is_inferred());
        let guessed = EmailGraphEdge { confidence: 0.5, ..exact };
        assert!(guessed.is_inferred());
    }
}
