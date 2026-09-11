# Chat observer run

## conversations

| name | profile | submitted | turn started | completed | verdict | generating |
|---|---|---|---|---|---|---|
| collection-exploration | chat | True | True | True | ok | 16.0-901.4s |
| document-evidence | chat | True | True | False | application_error | 16.7-976.7s |
| comparison-across-documents | chat | True | True | False | application_error | 16.1-976.2s |
| chronology-from-evidence | chat | True | True | False | application_error | 16.8-976.9s |
| public-source-research | chat | True | True | False | application_error | 17.0-977.1s |
| open-source-project-research | chat | True | True | False | application_error | 17.1-977.2s |
| public-organization-research | chat | True | True | False | application_error | 17.2-977.3s |
| conflicting-claims | chat | True | True | False | application_error | 19.5-979.6s |

## concurrency: the generating interval of every conversation
Overlap in the table above is the evidence eight windows showing a spinner does not give: two rows whose `generating` ranges intersect were actually producing tokens at the same time, not merely queued.

exit status: 1