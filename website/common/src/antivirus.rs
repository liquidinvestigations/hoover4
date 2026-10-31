//! The antivirus state of a document, as the website shows it.
//!
//! The worker stores every scan attempt in `virus_scan_results`. The effective verdict of
//! a hash is its latest completed attempt. A later failed, incomplete, skipped or
//! disabled attempt never replaces it, so a positive verdict stays until a later
//! completed scan says otherwise. [`VirusScanStatus::state`] is the effective verdict
//! when one exists, and otherwise the status of the latest attempt.

use serde::{Deserialize, Serialize};

/// The antivirus state of one document.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct VirusScanStatus {
    /// `clean`, `infected`, `incomplete`, `failed`, `skipped_size`, `skipped_disabled`
    /// or `not_scanned`.
    pub state: String,
    /// The signature of an infected or incomplete result, else empty.
    pub signature: String,
    pub engine_version: String,
    pub database_version: String,
    /// The write time of the attempt that the state comes from, `YYYY-MM-DD hh:mm:ss` UTC.
    pub scanned_at: String,
}

impl VirusScanStatus {
    pub fn is_infected(&self) -> bool {
        self.state == "infected"
    }

    /// The sentence of the metadata tab.
    pub fn label(&self) -> String {
        match self.state.as_str() {
            "clean" => "No virus found.".to_string(),
            "infected" => format!("Virus found: {}.", self.signature),
            "incomplete" => format!("The scan stopped at a scanner limit ({}). No verdict.", self.signature),
            "failed" => "The scan failed. No verdict.".to_string(),
            "skipped_size" => "The file is larger than 500 MB and was not scanned.".to_string(),
            "skipped_disabled" => "The antivirus scan was off when this file was processed.".to_string(),
            _ => "Not scanned.".to_string(),
        }
    }
}

/// The tooltip of a refused download button.
pub fn refused_download_tooltip(signature: &str) -> String {
    format!("Download refused. The antivirus scan found {signature}. The viewer can still show the file.")
}

/// The body of a 403 answer to a refused download.
pub fn refused_download_message(signature: &str) -> String {
    format!("forbidden: the antivirus scan found {signature} in this file, so its download is refused. The viewer can still show it.")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn labels_name_the_state() {
        let infected = VirusScanStatus { state: "infected".into(), signature: "Eicar-Test-Signature".into(), ..Default::default() };
        assert!(infected.is_infected());
        assert_eq!(infected.label(), "Virus found: Eicar-Test-Signature.");
        assert_eq!(VirusScanStatus::default().label(), "Not scanned.");
        assert!(refused_download_message("X").starts_with("forbidden"));
    }
}
