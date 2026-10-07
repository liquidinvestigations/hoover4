//! Chat components show messages, tool results, and document references.
//! Document cards include citation and search context.
//! The session page opens a document preview after selection.

pub mod composer;
pub mod conversation_find;
pub mod doc_ref_card;
pub mod gate_overlay;
pub mod locked_options;
pub mod markdown_text;
pub mod model_selector;
pub mod session_card;
pub mod tool_cards;
pub mod tool_disclosure;
pub mod tool_run_summary;
pub mod transcript;
pub mod web_page;

pub use composer::ChatComposer;
pub use conversation_find::ConversationFindBar;
pub use gate_overlay::ChatGateOverlay;
pub use locked_options::LockedOptionsBar;
pub use model_selector::ModelSelector;
pub use session_card::ChatSessionCard;
pub use transcript::ChatTranscript;
