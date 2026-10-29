//! The upload pages: the upload page, the batch list and the batch detail.
//!
//! The transfer runs in `assets/uploads.js` with the vendored tus-js-client. The pages read
//! through the server functions of `api::uploads_api`.

pub mod batch_detail;
pub mod batch_list;
mod driver;
mod folder_tree;
pub mod upload_page;
pub mod upload_button;

pub use batch_detail::UploadBatchPage;
pub use batch_list::UploadsPage;
pub use upload_page::UploadPage;
