# Legacy data processing tests

These are the tests of the older system, [hoover-snoop2](https://github.com/liquidinvestigations/hoover-snoop2).
hoover4 does not run them.
This document exists so a reader can check feature and test parity against that version.

The source is the `master` branch at revision `505adb5`.
The `testsuite/` directory holds 21 Python files.
19 of those files hold 65 test functions.
`conftest.py` and `settings.py` hold fixtures and Django settings.

Fixtures live in [hoover-testdata](https://github.com/liquidinvestigations/hoover-testdata) under `data/`.
A path in the fixture column is relative to that `data/` directory unless it says otherwise.

The tables are split by area.

## Contents

- [How to read a row](#how-to-read-a-row)
- [Emails](#emails)
- [Archives](#archives)
- [Blobs and MIME types](#blobs-and-mime-types)
- [Digest and Tika](#digest-and-tika)
- [OCR](#ocr)
- [Thumbnails](#thumbnails)
- [PDF preview](#pdf-preview)
- [Image classification](#image-classification)
- [Entities](#entities)
- [EXIF](#exif)
- [PGP](#pgp)
- [Walk](#walk)
- [API](#api)
- [Tags](#tags)
- [Tasks](#tasks)
- [Utils](#utils)
- [Integration](#integration)
- [Fixtures the tests use](#fixtures-the-tests-use)
- [Folders the tests do not use](#folders-the-tests-do-not-use)
- [Unusual formats](#unusual-formats)
- [Parity by area](#parity-by-area)

## How to read a row

Each row is one test function.
The file column links to the source on `master`.
The fixture column names the testdata path the function opens.
`none` means the test builds bytes in memory and opens no testdata file.

A skipped test still has a row.
The skip reason is in the sentence that describes the test.

## Emails

15 functions in [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_convert_msg_to_eml` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Converts an Outlook `.msg` file into an RFC 822 blob. | `msg-5-outlook/DISEARĂ-Te-așteptăm-la-discuția-despre-finanțarea-culturii.msg` |
| `test_email_header_parsing` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Parses the Subject header of an `.eml` whose attachments have long names. | `eml-5-long-names/Attachments have long file names..eml` |
| `test_subject_and_date` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Reads subject and date from a promotional Mapbox `.eml`. | `eml-1-promotional/` Mapbox message |
| `test_no_subject_or_text` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Parses an `.eml` that has no subject and no body text. | `eml-2-attachment/message-without-subject.eml` |
| `test_text` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Reads body text from two promotional `.eml` files. | `eml-1-promotional/` CodinGame and Mapbox messages |
| `test_people` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Reads From, To, and email-domains from a promotional `.eml`. | `eml-1-promotional/` Mapbox message |
| `test_email_with_byte_order_mark` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Parses subject and From on an `.eml` that starts with a UTF-8 BOM. | `eml-bom/with-bom.eml` |
| `test_attachment_children` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Lists child files under an `.eml` whose parts are labelled `octet-stream`. | `eml-2-attachment/attachments-have-octet-stream-content-type.eml` |
| `test_normal_attachments` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Counts two attachments on a Fontys invitation `.eml`. | `eml-2-attachment/` Campus Venlo message |
| `test_attachment_with_long_filename` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Counts three attachments whose names are long. | `eml-5-long-names/Attachments have long file names..eml` |
| `test_double_decoding_of_attachment_filenames` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Checks that a double-encoded attachment name is decoded once. | `eml-8-double-encoded/double-encoding.eml` |
| `test_attachment_with_octet_stream_content_type` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Infers png, msword, and zip types from `octet-stream` parts. | `eml-2-attachment/attachments-have-octet-stream-content-type.eml` |
| `test_broken_header` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Parses a Subject header that contains replacement characters. | `eml-10-broken-header/broken-subject.eml` |
| `test_emlx_reconstruction` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Rebuilds an Apple `.emlx` from a `.partial.emlx` and a `.emlxpart`. | `lists.mbox/` Apple Mail tree, message 1498 |
| `test_emlx_reconstruction_with_missing_file` | [`test_emails.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_emails.py) | Rebuilds an `.emlx` when the `.emlxpart` file is absent. | `emlx-4-missing-part/1498.partial.emlx` |

## Archives

6 functions in [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_unarchive_zip` | [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py) | Lists the directory tree inside a nested zip. | `disk-files/archives/tom/jail/jerry.zip` |
| `test_unarchive_pst` | [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py) | Unpacks an Outlook PST into a folder of messages. | `pst/flags_jane_doe.pst` |
| `test_unarchive_tar_gz` | [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py) | Unpacks a `.tar.gz` and then the inner tar, listing doc and pdf members. | `disk-files/archives/targz-with-pdf-doc-docx.tar.gz` |
| `test_unarchive_rar` | [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py) | Lists doc and pdf members of a rar archive. | `disk-files/archives/rar-with-pdf-doc-docx.rar` |
| `test_create_archive_files` | [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py) | Writes Directory and File rows for the members of a zip. | `disk-files/archives/zip-with-docx-and-doc.zip` |
| `test_unarchive_mbox` | [`test_archives.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_archives.py) | Splits an mbox into 29 message files grouped by hash prefix. | `mbox/shapelib.mbox` |

## Blobs and MIME types

3 functions in [`test_blobs.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_blobs.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_make_blob_from_jpeg_file` | [`test_blobs.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_blobs.py) | Computes SHA hashes and JPEG MIME type for one image. | `disk-files/images/bikes.jpg` |
| `test_make_blob_from_first_eml_file` | [`test_blobs.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_blobs.py) | Computes SHA-256 and `message/rfc822` for one `.eml`. | `eml-8-double-encoded/simple-encoding.eml` |
| `test_blob_mime_types` | [`test_blobs.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_blobs.py) | Asserts MIME type for many files, including ones with no extension. | Many paths under `data/` and `ocr/`. The parametrize list names each path. |

## Digest and Tika

2 functions in [`test_digest.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_digest.py) and 1 in [`test_tika.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tika.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_digest_with_broken_dependency` | [`test_digest.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_digest.py) | Skipped. A broken PDF should mark Tika HTTP 422 on the digest. | `disk-files/broken.pdf` |
| `test_digest_msg` | [`test_digest.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_digest.py) | Digests an Outlook `.msg` and checks filetype, hashes, and size. | `msg-5-outlook/DISEARĂ-Te-așteptăm-la-discuția-despre-finanțarea-culturii.msg` |
| `test_tika_digested` | [`test_tika.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tika.py) | Extracts text and dates from a Word `.doc` through Tika. | `no-extension/file_doc` |

## OCR

2 functions in [`test_ocr.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_ocr.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_pdf_ocr` | [`test_ocr.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_ocr.py) | Skipped. Overlay OCR text and a searchable PDF for one scan. | `disk-files/pdf-for-ocr/mof1_1992_233.pdf` and `ocr/one/` |
| `test_txt_ocr` | [`test_ocr.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_ocr.py) | Attaches overlay OCR text from source `two` to the same PDF. | `disk-files/pdf-for-ocr/mof1_1992_233.pdf` and `ocr/two/` |

## Thumbnails

4 functions in [`test_thumbnail.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_thumbnail.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_thumbnail_service` | [`test_thumbnail.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_thumbnail.py) | Calls the thumbnail service on a Word `.doc`. | `no-extension/file_doc` |
| `test_thumbnail_task` | [`test_thumbnail.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_thumbnail.py) | Stores a 100-pixel JPEG thumbnail of a photograph. | `disk-files/images/bikes.jpg` |
| `test_thumbnail_digested` | [`test_thumbnail.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_thumbnail.py) | Sets `has-thumbnails` on the digest of a Word `.doc`. | `no-extension/file_doc` |
| `test_thumbnail_api` | [`test_thumbnail.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_thumbnail.py) | Serves stored thumbnails for jpg, pdf, and docx over the HTTP API. | `no-extension/file_jpg`, `file_pdf`, `file_docx` |

## PDF preview

4 functions in [`test_pdf_preview.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pdf_preview.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_pdf_preview_service` | [`test_pdf_preview.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pdf_preview.py) | Calls the PDF-preview service on a Word `.doc`. | `disk-files/word/sample-doc-file-for-testing-1.doc` |
| `test_pdf_preview_task` | [`test_pdf_preview.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pdf_preview.py) | Stores a non-empty PDF preview blob for that `.doc`. | `disk-files/word/sample-doc-file-for-testing-1.doc` |
| `test_pdf_preview_digested` | [`test_pdf_preview.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pdf_preview.py) | Sets `has-pdf-preview` on the digest of that `.doc`. | `disk-files/word/sample-doc-file-for-testing-1.doc` |
| `test_pdf_preview_api` | [`test_pdf_preview.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pdf_preview.py) | Serves the PDF preview, including a ranged read. | `disk-files/word/sample-doc-file-for-testing-1.doc` |

## Image classification

7 functions in [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_classification_service_endpoint` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Calls the image-classification HTTP endpoint. | `disk-files/images/bikes.jpg` |
| `test_detection_service_endpoint` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Calls the object-detection HTTP endpoint. | `disk-files/images/bikes.jpg` |
| `test_classification_service` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Asserts the image class `unicycle` is among the predictions. | `disk-files/images/bikes.jpg` |
| `test_detection_service` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Asserts detected objects include person and bicycle. | `disk-files/images/bikes.jpg` |
| `test_detection_task` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Runs object detection as a snoop2 task and checks the JSON. | `disk-files/images/bikes.jpg` |
| `test_classification_task` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Runs image classification as a snoop2 task and checks the JSON. | `disk-files/images/bikes.jpg` |
| `test_scores_digested` | [`test_image_classification.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_image_classification.py) | Writes detected-objects and image-classes onto the digest. | `disk-files/images/bikes.jpg` |

## Entities

3 functions in [`test_entities.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_entities.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_nlp_service` | [`test_entities.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_entities.py) | Calls the NLP service on a short string that names a person. | none |
| `test_extract_entities_no_translation` | [`test_entities.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_entities.py) | Extracts person, organisation, and location from an ODT. | `disk-files/pdf-doc-txt/easychair.odt` |
| `test_extract_entities_with_translation` | [`test_entities.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_entities.py) | Same extraction with the translation service enabled. | `disk-files/pdf-doc-txt/easychair.odt` |

## EXIF

1 function in [`test_exif.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_exif.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_digest_image_exif` | [`test_exif.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_exif.py) | Reads date-created and GPS location from JPEG EXIF into the digest. | `disk-files/images/bikes.jpg` |

## PGP

3 functions in [`test_pgp.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pgp.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_decrypted_data` | [`test_pgp.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pgp.py) | Decrypts a PGP `.eml` and reads headers, body text, and a Word attachment. | `eml-9-pgp/encrypted-hushmail-knockoff.eml` |
| `test_gpg_digest` | [`test_pgp.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pgp.py) | Sets `pgp` on the digest of that encrypted message. | `eml-9-pgp/encrypted-hushmail-knockoff.eml` |
| `test_broken_if_no_gpg_home` | [`test_pgp.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_pgp.py) | Skipped. Parse should fail with `gpg_not_configured` when gpghome is missing. | `eml-9-pgp/encrypted-hushmail-knockoff.eml` |

## Walk

3 functions in [`test_walk.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_walk.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_walk` | [`test_walk.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_walk.py) | Walks a directory, hashes the one file, and queues `handle_file`. | `emlx-4-missing-part/` as the collection data directory |
| `test_smashed_filename` | [`test_walk.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_walk.py) | Walks a directory whose filenames are not valid UTF-8 and still records two files. | `disk-files/bad-filename/` as the collection data directory |
| `test_children_of_archives_in_multiple_locations` | [`test_walk.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_walk.py) | One zip at two paths yields two file rows that share the same blobs. | `zip-in-multiple-locations/` as the collection data directory |

## API

2 functions in [`test_api.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_api.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_blob_locations` | [`test_api.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_api.py) | Lists two filesystem locations for one blob created in memory. | none |
| `test_document_downloads` | [`test_api.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_api.py) | Downloads a blob, including a ranged 16-byte read. | `disk-files/images/bikes.jpg` |

## Tags

1 function in [`test_tags.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tags.py) and 1 in [`test_tagimport.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tagimport.py).
Both functions are named `test_tags_api`.

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_tags_api` | [`test_tags.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tags.py) | Posts one user tag through the HTTP API and finds it in Elasticsearch. | `no-extension/file_pdf` |
| `test_tags_api` | [`test_tagimport.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tagimport.py) | Imports tags from a CSV of MD5 hashes and finds them in Elasticsearch. | `no-extension/file_pdf` and `disk-files/images/bikes.jpg` |

## Tasks

4 functions in [`test_tasks.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tasks.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_dependent_task` | [`test_tasks.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tasks.py) | A second task receives the blob written by the first. | none |
| `test_blob_arg` | [`test_tasks.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tasks.py) | A task takes a blob argument and writes a derived blob. | none |
| `test_missing_dependency` | [`test_tasks.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tasks.py) | `require_dependency` launches the missing producer and waits for it. | none |
| `test_broken_dependency` | [`test_tasks.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_tasks.py) | A broken producer is reported to the dependent task as `SnoopTaskBroken`. | none |

## Utils

2 functions in [`test_utils.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_utils.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_read_minimum` | [`test_utils.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_utils.py) | `read_exactly` reassembles bytes from a file that returns short reads. | none |
| `test_call_once` | [`test_utils.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_utils.py) | `run_once` calls the wrapped function one time and reuses the return value. | none |

## Integration

1 function in [`test_integration.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_integration.py).

| test | file | what it exercises | fixture |
|---|---|---|---|
| `test_complete_lifecycle` | [`test_integration.py`](https://github.com/liquidinvestigations/hoover-snoop2/blob/master/testsuite/test_integration.py) | Skipped as slow. Walks the whole collection, indexes it, and checks known documents. | The whole `data/` tree. Known ids include zip members, `easychair.docx`, and a `.partial.emlx`. |

## Fixtures the tests use

The table below gives file counts and sizes.

| folder | files | size | used by | GitHub |
|---|---:|---|---|---|
| `disk-files` | 239 | 514 MB | archives, blobs, digest, entities, EXIF, image classification, OCR, PDF preview, tags, thumbnails, walk | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/disk-files) |
| `eml-1-promotional` | 3 | 72 KB | emails, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-1-promotional) |
| `eml-10-broken-header` | 1 | 4 KB | emails | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-10-broken-header) |
| `eml-2-attachment` | 5 | 3.4 MB | emails, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-2-attachment) |
| `eml-3-uppercaseheaders` | 1 | 72 KB | blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-3-uppercaseheaders) |
| `eml-5-long-names` | 1 | 416 KB | emails, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-5-long-names) |
| `eml-7-recursive` | 1 | 56 KB | blobs MIME (`d.7z`) | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-7-recursive) |
| `eml-8-double-encoded` | 2 | 4.7 MB | emails, blobs | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-8-double-encoded) |
| `eml-9-pgp` | 18 | 1.1 MB | PGP, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-9-pgp) |
| `eml-bom` | 1 | 4 KB | emails, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/eml-bom) |
| `emlx-4-missing-part` | 1 | 44 KB | emails, walk | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/emlx-4-missing-part) |
| `lists.mbox` | 4 | 204 KB | emails (emlx reconstruction), blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/lists.mbox) |
| `mbox` | 2 | 160 KB | archives, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/mbox) |
| `msg-5-outlook` | 2 | 28 KB | emails, digest, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/msg-5-outlook) |
| `no-extension` | 14 | 1.8 MB | blobs MIME, tags, tika, thumbnails | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/no-extension) |
| `pst` | 1 | 172 KB | archives, blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/pst) |
| `words` | 1 | 920 KB | blobs MIME | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/words) |
| `zip-in-multiple-locations` | 2 | 8 KB | walk | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/zip-in-multiple-locations) |
| `ocr/` (testdata root, not under `data/`) | 6 | 5.4 MB | blobs MIME, OCR overlay sources | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/ocr) |

`disk-files` subfolders the tests open:

| subfolder | files | size | used by |
|---|---:|---|---|
| `archives` | 96 | 1.4 MB | unarchive zip, tar.gz, rar, create_archive_files, blobs MIME |
| `images` | 1 | 612 KB | blobs, API download, EXIF, image classification, tags, thumbnails |
| `pdf-doc-txt` | 6 | 900 KB | entities, blobs MIME |
| `pdf-for-ocr` | 1 | 2.4 MB | OCR |
| `word` | 3 | 41 MB | PDF preview |
| `long-filenames` | 3 | 308 KB | blobs MIME |
| `duplicates` | 4 | 1.8 MB | blobs MIME |
| `bad-filename`, `bad-html`, `html-encodings` | 7 | 28 KB | walk smashed filename, blobs MIME |

`disk-files/broken.pdf` is a single file used by the skipped digest test.
It is not a subfolder.

The testdata root also holds `gpghome/` (8 files, 16 KB).
PGP tests do not open it by path.
snoop2 collection settings point at it when decryption runs.

## Folders the tests do not use

These sit under `data/` and no test function opens them.

| folder | files | size | GitHub |
|---|---:|---|---|
| `many-children` | 669 | 2.9 MB | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/many-children) |
| `www.learningcontainer.com` | 40 | 54 MB | [folder](https://github.com/liquidinvestigations/hoover-testdata/tree/master/data/www.learningcontainer.com) |

Inside `disk-files`, these subfolders are also unused by the snoop2 tests:

| subfolder | files | size |
|---|---:|---|
| `img` | 84 | 456 MB |
| `pdf-scans` | 15 | 9.7 MB |
| `entity-fixtures` | 17 | 92 KB |

These folders may still serve website QA datasets, which are a different contract.

## Unusual formats

What each folder would exercise, and whether hoover4 handles it.
"Handles" here means the ingest pipeline detects the type and extracts members or text.
Where that is not established from the code, the cell says not determined.

| folder or format | what it would exercise | hoover4 today |
|---|---|---|
| `pst` | Unpack an Outlook personal folder into messages. | MIME type `application/x-hoover-pst` and coarse type `email`. The email parser is Python `BytesParser` on RFC 822 bytes. It does not unpack a PST folder tree. |
| Apple `emlx` (`lists.mbox`) | Join a `.partial.emlx` with sibling `.emlxpart` files and parse the result. | The sniff names `message/x-emlx` and strips the byte-count prefix. `parse_email.py` does not join `.emlxpart` siblings. |
| `emlx-4-missing-part` | Reconstruct when a part file is absent, leaving a zero-length attachment. | Same as `emlx`. No reconstruction step exists. |
| `mbox` | Split a Unix mailbox into one document per message. | The sniff names `application/mbox`. The email parser reads the file as one RFC 822 message. It does not split the spool. |
| `msg-5-outlook` | Convert an Outlook `.msg` (OLE) into RFC 822. | MIME type `application/vnd.ms-outlook` and coarse type `email`. There is no `msg_to_eml` converter. `BytesParser` does not read OLE. |
| `eml-9-pgp` | Decrypt PGP-encrypted mail and index the clear text. | The files are sniffed as email. No GPG decrypt step was found in the processing tree. `application/x-hush-pgp-encrypted-html-body` maps to coarse type `html`. |
| `eml-8-double-encoded` | Decode an attachment filename that was encoded twice. | Attachment names come from the Python email library. Whether a double-encoded name is decoded once is not determined. |
| `eml-bom` | Parse headers that follow a UTF-8 BOM. | `strip_email_envelope` removes a leading BOM before parse. The sniff unit test covers this shape. |
| `no-extension` | Detect type from bytes when the name has no suffix. | `parse_mime.py` combines `file`, Magika, Tika/Extractous, and the email sniff. Partial coverage exists in sniff and zip-container tests. |
| `disk-files/bad-filename` | Walk a tree whose names are not valid UTF-8. | not determined |
| `disk-files/bad-html` | Extract text from HTML that is not well formed. | not determined |
| `disk-files/html-encodings` | Read HTML declared as latin-1 by a meta tag or an XML declaration. | not determined |
| `disk-files/long-filenames` | Store and search names that exceed ordinary path limits. | not determined |
| `disk-files/duplicates` | The same PDF bytes at several paths share one blob. | Ingest deduplicates by content hash. No test uses these four PDFs. |
| `disk-files/archives` rar, tar.gz, password zip, smashed zip | Extract members, including a passworded or truncated zip. | Archives go through `7z`. Passworded and truncated zips are not determined. |
| `eml-7-recursive` | A 7z archive that holds further archives. | Archive descent exists. This file is only in the snoop2 MIME table. |
| `eml-10-broken-header` | A Subject header that is not valid UTF-8. | The sniff lists this file as email. Replacement-character handling is not determined. |
| `disk-files/pdf-for-ocr` and `pdf-scans` | OCR on scanned PDFs. | OCR for images and searchable PDFs exists. These fixtures are not used by the hoover4 OCR tests. |

## Parity by area

Observations from reading hoover4 tests and parsers.
Neither system was run for this catalogue.

| area | snoop2 | hoover4 equivalent | notes |
|---|---|---|---|
| Email sniff and MIME | `test_blob_mime_types`, header tests | `test_sniff_email.py`, `test_email_sniff_corpus.py` | The mixed-corpus test names 22 of the same testdata mail files. |
| Email headers, people, body | `test_emails.py` subject, date, people, text | parse_email writes `email_headers` and `email_addresses` | No hoover4 test was found that asserts Mapbox subject, date, or From on these fixtures. |
| `.msg` conversion | `test_convert_msg_to_eml`, `test_digest_msg` | none found | Type is detected. Conversion is not. |
| `.emlx` reconstruction | two reconstruction tests | none found | Prefix strip exists. Part joining does not. |
| PST unpack | `test_unarchive_pst` | none found | Type is detected. Unpack is not. |
| mbox split | `test_unarchive_mbox` | none found | Type is detected. Split is not. |
| Zip, tar.gz, rar | `test_archives.py` | `parse_archives.py` (`7z`), `test_zip_document_containers.py` | hoover4 tests the document-versus-archive decision. It does not assert member lists of `jerry.zip`, the rar, or the tar.gz. |
| Same zip at two paths | `test_children_of_archives_in_multiple_locations` | `test_ancestor_closure.py` comments name this fixture | Closest match. Not a walk of the testdata folder. |
| Smashed filename walk | `test_smashed_filename` | none found | not determined whether P0 records the two files |
| Blob hashes | `test_make_blob_from_jpeg_file` | P0 stores content hashes | No golden SHA for `bikes.jpg` was found. |
| Tika text from `.doc` | `test_tika_digested` | Extractous/Tika path in P3, `test_extractous_*` | No test asserts "Colors and Lines to choose" on `file_doc`. |
| OCR overlay sources | `test_ocr.py` | `parse_ocr.py`, `parse_ocr_pdf.py`, OCR-PDF suite | hoover4 OCRs live. It does not attach the `ocr/one/` overlay tree. |
| Thumbnails | `test_thumbnail.py` | none found | Chat cards store a capture thumbnail. That is not a document thumbnail service. |
| PDF preview of `.doc` | `test_pdf_preview.py` | PDF viewer for PDF documents | No convert-office-to-PDF service was found. |
| Image classification | `test_image_classification.py` | none found | No object-detection or image-class field was found in processing. |
| Named entities | `test_entities.py` | P4 NER, `test_nlp_success_stubbed.py`, entity stoplist tests | Different fixtures and a different service. |
| EXIF date and GPS | `test_digest_image_exif` | `document_dates.py` reads `exif:DateTimeOriginal` | No test asserts the `bikes.jpg` timestamp or GPS pair. |
| PGP decrypt | `test_pgp.py` | none found | Encrypted `.eml` files are sniffed as mail. Decrypt is not. |
| User tags | `test_tags.py`, `test_tagimport.py` | none found | No document-tag API was found. |
| Task dependencies | `test_tasks.py` | Temporal workflows | Different machinery. No equivalent unit tests of `require_dependency`. |
| Utils | `test_utils.py` | not determined | `read_exactly` / `run_once` may exist under another name. |
| Full collection lifecycle | `test_complete_lifecycle` (skipped) | `verify-stack.sh`, pipeline integration tests | Different corpus and assertions. |
| Download and locations API | `test_api.py` | document download and VFS locations | Website stack tests cover download and locations. They do not use these snoop2 fixtures. |
