//! Whether a new chat turn may start.
//!
//! The backend evaluates this on every send. The frontend overlay is a hint that names
//! the same reason. A control that only hides the composer is not the gate.

/// `server_settings` key that turns every new chat turn off. Absent means chat is on.
pub const CHAT_ENABLED_SETTING: &str = "chat_enabled";

/// Why a new chat turn is refused, or that it is allowed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(tag = "state", content = "reason")]
pub enum ChatGate {
    Open,
    Closed(ChatGateClosed),
}

/// One reason the composer is closed. The overlay quotes [`ChatGateClosed::overlay_text`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChatGateClosed {
    NoProvider,
    SwitchedOff,
    Unevaluable,
}

/// Inputs the gate reads. Configuration presence only: no request to the provider.
pub struct ChatGateInputs<'a> {
    pub base_url: &'a str,
    pub env_model: &'a str,
    pub default_chat_model: &'a str,
    /// `Ok(true)` chat is on, `Ok(false)` an administrator switched it off,
    /// `Err(())` the setting could not be read.
    pub chat_enabled: Result<bool, ()>,
}

impl ChatGate {
    /// An error from the server function closes the form. An open form over a broken
    /// gate is the failure this type exists to prevent.
    pub fn from_server_result<E>(result: Result<Self, E>) -> Self {
        result.unwrap_or(Self::Closed(ChatGateClosed::Unevaluable))
    }

    pub fn is_open(self) -> bool {
        matches!(self, Self::Open)
    }


}

impl ChatGateClosed {
    /// First sentence on the overlay: the reason that applies.
    pub fn overlay_lead(self) -> &'static str {
        match self {
            Self::NoProvider => "No LLM provider is configured.",
            Self::SwitchedOff => "Chat is switched off by an administrator.",
            Self::Unevaluable => "The server could not evaluate whether chat is available.",
        }
    }

    /// Second sentence: what an administrator does about it.
    pub fn overlay_action(self) -> &'static str {
        match self {
            Self::NoProvider => {
                "An administrator sets a provider under /admin/llm."
            }
            Self::SwitchedOff => {
                "An administrator turns it on under /admin/settings (chat_enabled)."
            }
            Self::Unevaluable => "An administrator checks the website logs.",
        }
    }

    /// Full overlay copy, two sentences.
    pub fn overlay_text(self) -> String {
        format!("{} {}", self.overlay_lead(), self.overlay_action())
    }

    /// Backend refusal body. Same words as the overlay so a bypass sees the same reason.
    pub fn refusal_message(self) -> String {
        format!("chat_unavailable:{}: {}", self.code(), self.overlay_text())
    }

    pub fn code(self) -> &'static str {
        match self {
            Self::NoProvider => "no_provider",
            Self::SwitchedOff => "switched_off",
            Self::Unevaluable => "unevaluable",
        }
    }
}

/// Absent means on. Only the string `true` or `false` is a known value.
pub fn chat_enabled_from_stored(value: Option<&str>) -> Result<bool, ()> {
    match value {
        None => Ok(true),
        Some(raw) => match raw.trim().to_ascii_lowercase().as_str() {
            "true" => Ok(true),
            "false" => Ok(false),
            _ => Err(()),
        },
    }
}

/// Close the gate when chat is switched off, the switch cannot be read, or no model server
/// is configured. The self-hosted model servers need no API key in the gate.
pub fn evaluate_chat_gate(inputs: ChatGateInputs<'_>) -> ChatGate {
    match inputs.chat_enabled {
        Err(()) => return ChatGate::Closed(ChatGateClosed::Unevaluable),
        Ok(false) => return ChatGate::Closed(ChatGateClosed::SwitchedOff),
        Ok(true) => {}
    }
    let base_ok = !inputs.base_url.trim().is_empty();
    let model_ok = !inputs.env_model.trim().is_empty()
        || !inputs.default_chat_model.trim().is_empty();
    if !base_ok || !model_ok {
        return ChatGate::Closed(ChatGateClosed::NoProvider);
    }
    ChatGate::Open
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inputs<'a>(base: &'a str, model: &'a str, enabled: Result<bool, ()>) -> ChatGateInputs<'a> {
        ChatGateInputs {
            base_url: base,
            env_model: model,
            default_chat_model: "",
            chat_enabled: enabled,
        }
    }

    #[test]
    fn no_base_url_closes_as_no_provider() {
        let gate = evaluate_chat_gate(inputs("", "a-model", Ok(true)));
        assert_eq!(gate, ChatGate::Closed(ChatGateClosed::NoProvider));
    }

    #[test]
    fn no_model_closes_as_no_provider() {
        let gate = evaluate_chat_gate(inputs("http://example/v1", "", Ok(true)));
        assert_eq!(gate, ChatGate::Closed(ChatGateClosed::NoProvider));
    }

    #[test]
    fn default_chat_model_counts_as_a_model() {
        let gate = evaluate_chat_gate(ChatGateInputs {
            base_url: "http://example/v1",
            env_model: "",
            default_chat_model: "stored-model",
            chat_enabled: Ok(true),
        });
        assert_eq!(gate, ChatGate::Open);
    }

    #[test]
    fn a_configured_model_server_opens_the_gate() {
        let gate = evaluate_chat_gate(inputs("http://example/v1", "a-model", Ok(true)));
        assert_eq!(gate, ChatGate::Open);
    }

    #[test]
    fn switch_off_closes_even_when_the_provider_is_complete() {
        let gate = evaluate_chat_gate(inputs("http://example/v1", "a-model", Ok(false)));
        assert_eq!(gate, ChatGate::Closed(ChatGateClosed::SwitchedOff));
    }

    #[test]
    fn a_setting_read_error_closes_as_unevaluable() {
        let gate = evaluate_chat_gate(inputs("http://example/v1", "a-model", Err(())));
        assert_eq!(gate, ChatGate::Closed(ChatGateClosed::Unevaluable));
    }

    #[test]
    fn a_server_function_error_closes_the_form() {
        let gate: Result<ChatGate, &str> = Err("server function failed");
        assert_eq!(
            ChatGate::from_server_result(gate),
            ChatGate::Closed(ChatGateClosed::Unevaluable)
        );
    }

    #[test]
    fn overlay_text_names_each_reason() {
        assert!(ChatGateClosed::NoProvider
            .overlay_text()
            .starts_with("No LLM provider is configured."));
        assert!(ChatGateClosed::SwitchedOff
            .overlay_text()
            .starts_with("Chat is switched off by an administrator."));
    }
}
