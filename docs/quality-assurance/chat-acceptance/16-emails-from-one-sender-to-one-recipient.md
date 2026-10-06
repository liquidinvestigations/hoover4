# 16. Every email from one sender to one recipient

| field | value |
|---|---|
| mode | deep research, internet tools off |
| collections in scope | every collection |
| data needed | `enron`, datasets `maildir` and `mann_k` |

## Prompt

```text
List all emails sent by kay.mann@enron.com to sara.shackleton@enron.com and arrange them in chronological order starting with the newest one.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 32 distinct documents have kay.mann@enron.com as sender and sara.shackleton@enron.com in To or Cc. 20 of them have her in To. The website filters for sender and recipient give the same 32. | `enron` | `email_addresses` by role |
| The 32 documents hold 12 distinct messages. The same message is in more than one mailbox, for example "ISDA documents" of 2000-10-05 in both `maildir` and `mann_k`. | `enron` | `email_headers`, grouped by date and subject |
| The newest is "Out of Office AutoReply: non-terminated financial and physical trading contracts" of 2002-03-20, `/shackleton-s/deleted_items/617.` (`1df1e0748709`). It is an automatic reply. | `enron` | `email_headers` |
| The oldest is "Re: Midwest Energy Hub LLC ("Midwest")" of 2000-08-29, `/mann-k/_sent_mail/3654.` (`1519977673ef`). | `enron` | `email_headers` |

## Expected tool calls

1. The planner sees that one filtered search answers the request. It answers without sections, or writes a plan with one section.
2. It calls `search_collections` with the filters `email_from` `["kay.mann@enron.com"]` and `email_to` `["sara.shackleton@enron.com"]`, no query words, and the date sort descending.
3. It calls `read_more` until it has every row.
4. It calls `doc_email` or `doc_metadata` with a list of hashes when it needs a header that the rows do not give.
5. It calls `cite_documents` with one copy of each message.

## Expected result

A table of the 12 distinct messages, newest first, with date, subject and a card. The answer says that the 32 documents hold copies of the same messages, and how it grouped them. It marks the automatic reply as such. It says whether it counted Cc recipients.

## Requirements exercised

The story exercises these requirements and optional behavior: filters by sender and recipient, a complete list, copies of one message grouped, a sort by date, document cards shown to the user, a task completed.
