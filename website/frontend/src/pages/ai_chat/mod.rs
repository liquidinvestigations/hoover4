//! AI Chat pages: homepage with the board overview, history list, conversation with document
//! preview, and the investigation board pages.

mod board_create_page;
mod board_page;
mod history_page;
mod homepage;
mod session_page;

pub use board_create_page::AiBoardCreatePage;
pub use board_page::AiBoardPage;
pub use history_page::AiChatHistoryPage;
pub use homepage::AiChatPage;
pub use session_page::AiChatSessionPage;
