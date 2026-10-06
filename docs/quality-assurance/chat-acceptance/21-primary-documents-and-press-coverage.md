# 21. Primary documents and press coverage inside a collection

| field | value |
|---|---|
| mode | deep research, internet tools off |
| collections in scope | every collection |
| data needed | `enron`, dataset `maildir` |

## Prompt

```text
find me in the Enron collection the most important communication showing the discussion of a possible criminal act according to US jurisdiction
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 31 documents in `enron` quote Sherron Watkins's letter to Kenneth Lay with the words "implode in a wave of accounting scandals". All are dated 2002-01-15 to 2002-02-14, after the letter became public. | `enron` | a text scan |
| "FW: Text of Letter to Enron's Chairman After Departure of Chief Executive", forwarded on 2002-01-16, holds the letter's text as a press copy. | `enron` | `/dorland-c/deleted_items/140.` (`24500e2d61c7`) |
| "FW: E memo", forwarded on 2002-01-16, holds the letter as well. | `enron` | `/parks-j/deleted_items/913.` (`332f98170cc9`) |
| Most of the 31 are the daily press digests "Enron Mentions", for example the issue of 2002-01-16. | `enron` | `/martin-t/inbox/103.` (`10bcea2f0ccc`) |

## Expected tool calls

1. It calls `search_collections` with `["\"implode in a wave of accounting scandals\"", "\"Watkins\" Lay letter", "\"smoking gun\""]`.
2. It reads the forward of the letter's text and one press digest.
3. It calls `cite_documents` with the letter's forward and one digest.

## Expected result

The answer names the Watkins letter as the communication, and says that the collection holds it only as copies forwarded in January 2002 and as quotes in press digests. It marks each statement that comes from a press report as such, and keeps it apart from what the forwarded letter itself says. It says that the run used no web source, because internet tools were off.

## Requirements exercised

The story exercises these requirements and optional behavior: a primary source told apart from press coverage, the date of a copy against the date of the original, the tool scope stated, document cards shown to the user, a task completed.
