# The settings route chooses the languages of one person.

The settings route shows the interface language and the agent language of the signed-in person.
[The settings page](../../../website/frontend/src/pages/settings_page.rs), [the language rules](../../../website/common/src/language.rs) and [the settings API](../../../website/backend/src/api/settings.rs) own the contract.
The person icon at the bottom of the navigation rail opens it for every signed-in person.

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Interface language choices | Select Browser language or one of 18 languages. The page saves the choice and shows the interface in that language at once. | Browser language follows the first supported language of the browser's `Accept-Language` header, else English. Each language shows its own name, its code and its flag. |
| Agent language choices | Select Same as the interface or one of 18 languages. The page saves the choice. | The agent uses the choice from the next message. A turn that already started keeps its language. |

## States

| State | Display |
|---|---|
| Nothing saved | Browser language and Same as the interface are selected. Each one names the language that it selects now. |
| Saved | The status line says Saved. |
| Failed save | The page shows the server error, and the earlier choice stays selected. |

## Constraints

- The settings belong to one username. A guest session has its own username, so guests never share settings.
- The server renders every page in the resolved interface language, and the browser continues in the same language.
- Arabic and Hebrew show in the left-to-right layout. Inserted values keep their own direction through Unicode isolation marks.
- Document content, file names, stored processing errors and earlier model output stay in their stored language.
