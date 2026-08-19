"""Utility for mapping MIME types to coarse file categories."""

from typing import Iterable


# Container formats that are ZIP on the inside but a single document to the reader.
# `file -k` keeps going past the first match, so a .docx comes back as the OOXML type
# *and* `application/zip` *and* `application/octet-stream`; without this set the union of
# coarse types contains `archive` and the file gets 7z-exploded into one indexed document
# per internal XML part. `.jar`/`.apk` are deliberately absent: `file` names them with
# their own MIME rather than `application/zip`, so they never reached the archive branch
# in the first place and this set must not be the thing that changes their handling.
_ZIP_BASED_DOCUMENT_MIMES = frozenset({
    # OOXML: Word / Excel / PowerPoint, plus macro-enabled and template variants.
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
    'application/vnd.ms-word.document.macroEnabled.12',
    'application/vnd.ms-word.template.macroEnabled.12',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.template',
    'application/vnd.ms-excel.sheet.macroEnabled.12',
    'application/vnd.ms-excel.template.macroEnabled.12',
    'application/vnd.ms-excel.addin.macroEnabled.12',
    'application/vnd.ms-excel.sheet.binary.macroEnabled.12',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.openxmlformats-officedocument.presentationml.template',
    'application/vnd.openxmlformats-officedocument.presentationml.slideshow',
    'application/vnd.ms-powerpoint.presentation.macroEnabled.12',
    'application/vnd.ms-powerpoint.template.macroEnabled.12',
    'application/vnd.ms-powerpoint.slideshow.macroEnabled.12',
    'application/vnd.ms-powerpoint.addin.macroEnabled.12',
    # OpenDocument: text / spreadsheet / presentation / graphics, plus templates.
    'application/vnd.oasis.opendocument.text',
    'application/vnd.oasis.opendocument.text-template',
    'application/vnd.oasis.opendocument.spreadsheet',
    'application/vnd.oasis.opendocument.spreadsheet-template',
    'application/vnd.oasis.opendocument.presentation',
    'application/vnd.oasis.opendocument.presentation-template',
    'application/vnd.oasis.opendocument.graphics',
    'application/vnd.oasis.opendocument.graphics-template',
    # E-books.
    'application/epub+zip',
})

# Coarse types that make a file a document even when a detector also called it an archive.
_DOCUMENT_COARSE_TYPES = frozenset({'doc', 'xls', 'ppt'})


def is_zip_based_document_mime(mime_type: str) -> bool:
    """Whether this single MIME type names a container format that is a document."""
    return mime_type in _ZIP_BASED_DOCUMENT_MIMES


def should_expand_as_archive(coarse_types: Iterable[str], mime_types: Iterable[str]) -> bool:
    """Whether a file should be exploded into its members by the archive extractor.

    The decision is over the *whole* detected type set, not membership in the union:
    detectors disagree by design, and `file -k` alone reports a .docx four ways. One
    detector saying "archive" must not outvote another saying "document".
    """
    coarse = set(coarse_types)
    if 'archive' not in coarse:
        return False
    if any(is_zip_based_document_mime(m) for m in mime_types):
        return False
    return not (coarse & _DOCUMENT_COARSE_TYPES)


def coarse_file_type(mime_type: str) -> str:

    if mime_type in (
        'text/html', 'text/xhtml+xml', 'application/xhtml+xml', 'application/xaml+xml',
        'application/x-hush-pgp-encrypted-html-body', 'application/x-hush-pgp-encrypted-html-body-multipart',
    ):
        return 'html'

    # The document-container guard comes before the archive branch: a member of the set
    # is never an archive, whatever else the detector said about it.
    if not is_zip_based_document_mime(mime_type) and (mime_type in (
        "application/zip", "application/x-tar", "application/x-7z-compressed", "application/x-rar-compressed", "application/x-rar",
        "application/x-bzip2", "application/x-gzip", "application/x-lzma",
        "application/x-lzip", "application/x-xz", "application/x-zstd",
        "application/zip", "application/rar", "application/x-7z-compressed", "application/x-tar",
        "application/x-bzip2", "application/x-zip", "application/x-gzip", "application/x-zip-compressed",
        "application/x-rar-compressed", "application/vnd.rar",
    ) or mime_type.startswith("application/x-zip")):
        return "archive"

    if mime_type in (
        'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-word.document.macroEnabled.12', 'application/vnd.oasis.opendocument.text',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.template', 'application/rtf'
    ):
        return 'doc'

    if mime_type in (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.template', 'application/vnd.ms-excel.template.macroEnabled.12',
        'application/vnd.ms-excel.sheet.macroEnabled.12', 'application/vnd.oasis.opendocument.spreadsheet',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.template', 'application/x-excel',
        'application/x-msexcel', 'application/x-ms-excel', 'application/x-ms-excel-macro',
        'application/x-ms-excel-macroEnabled', 'application/x-ms-excel-template', 'application/x-ms-excel-template-macroEnabled',
        'application/x-ms-excel-template-macroEnabled.12', 'application/x-ms-excel-template-macroEnabled.12',
    ):
        return 'xls'

    if mime_type in (
        'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.template', 'application/vnd.ms-powerpoint.template.macroEnabled.12',
        'application/vnd.ms-powerpoint.slideshow.macroEnabled.12', 'application/vnd.oasis.opendocument.presentation',
        'application/vnd.openxmlformats-officedocument.presentationml.template', 'application/x-powerpoint',
        'application/x-mspowerpoint', 'application/x-ms-powerpoint', 'application/x-ms-powerpoint-macro',
        'application/x-ms-powerpoint-macroEnabled', 'application/x-ms-powerpoint-template', 'application/x-ms-powerpoint-template-macroEnabled',
        'application/x-ms-powerpoint-template-macroEnabled.12', 'application/x-ms-powerpoint-template-macroEnabled.12',
    ):
        return 'ppt'

    # `message/x-emlx` and `application/x-hoover-pst` come from the content sniff, which
    # is the only detector that names either: libmagic reports an Apple `.emlx` as text
    # and a PST only in its human-readable output.
    if mime_type in (
        "message/rfc822", "application/vnd.ms-outlook", "application/vnd.ms-exchange", "application/mbox",
        "message/x-emlx", "application/x-hoover-pst",
    ):
        return "email"

    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type.startswith("text/"):
        return "text"

    return "other"
