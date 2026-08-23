//! AI Chat UI building blocks: composer, transcript, tool disclosure, doc cards.
//!
//! Document cards reuse [`SearchResultItemCard`](crate::components::search_components::search_result_item_card::SearchResultItemCard)
//! via a `SearchResultsState` context provided by the session page. The document pane
//! reuses [`DocumentPreviewForSearchRoot`](crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot)
//! unchanged (including `NoDocumentSelected`).

pub mod composer;
pub mod conversation_find;
pub mod doc_ref_card;
pub mod locked_options;
pub mod markdown_text;
pub mod model_selector;
pub mod session_card;
pub mod tool_cards;
pub mod tool_disclosure;
pub mod transcript;

pub use composer::ChatComposer;
pub use conversation_find::ConversationFindBar;
pub use doc_ref_card::ChatDocRefCard;
pub use locked_options::LockedOptionsBar;
pub use model_selector::ModelSelector;
pub use session_card::ChatSessionCard;
pub use tool_cards::ToolCard;
pub use tool_disclosure::ToolCallDisclosure;
pub use transcript::ChatTranscript;
