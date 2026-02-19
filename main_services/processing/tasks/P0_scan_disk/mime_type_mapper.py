"""Utility for mapping MIME types to coarse file categories."""


def coarse_file_type(mime_type: str) -> str:

    if mime_type in (
        'text/html', 'text/xhtml+xml', 'application/xhtml+xml', 'application/xaml+xml',
        'application/x-hush-pgp-encrypted-html-body', 'application/x-hush-pgp-encrypted-html-body-multipart',
    ):
        return 'html'

    if mime_type in (
        "application/zip", "application/x-tar", "application/x-7z-compressed", "application/x-rar-compressed", "application/x-rar",
        "application/x-bzip2", "application/x-gzip", "application/x-lzma",
        "application/x-lzip", "application/x-xz", "application/x-zstd",
        "application/zip", "application/rar", "application/x-7z-compressed", "application/x-tar",
        "application/x-bzip2", "application/x-zip", "application/x-gzip", "application/x-zip-compressed",
        "application/x-rar-compressed", "application/vnd.rar",
    ) or mime_type.startswith("application/x-zip"):
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

    if mime_type in (
        "message/rfc822", "application/vnd.ms-outlook", "application/vnd.ms-exchange", "application/mbox",
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
