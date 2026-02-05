log = logging.getLogger(__name__)
MAX_PDF_PAGES_PER_CHUNK = 6000


def run_script(script, timeout='120s', kill='130s'):
    """Call the script and return the stdout; add 2min timeout"""
    # vandalize script so we drop very long STDERR messages from the logs
    # qpdf is sometimes very spammy with content warnings
    with TemporaryDirectory(prefix='pdf-tools-pwd-') as pwd:
        # script = script + ' 2> >(head -c2000 >&2)'
        script = f"cd '{pwd}'; " + script
        cmd = ['/usr/bin/timeout', '-k', kill, timeout, '/bin/bash', '-exo', 'pipefail', '-c', script]
        log.warning('+ %s', script)
        return subprocess.check_output(cmd, cwd=pwd)


def get_pdf_info(path):
    """streaming wrapper to extract pdf info json (page count, chunks)"""
#    script = "export JAVA_TOOL_OPTIONS='-Xmx3g'; pdftk - dump_data | grep NumberOfPages | head -n1"
    # script = "pdfinfo -  | grep Pages | head -n1"
    script = f"qpdf --show-npages '{path}'"
    page_count = int(run_script(script).decode('ascii'))
    size_mb = round(os.stat(path).st_size / 2**20, 3)
    if size_mb > 100:
        DESIRED_CHUNK_MB = 25
    else:
        DESIRED_CHUNK_MB = 100
    chunk_count = max(1, int(math.ceil(size_mb / DESIRED_CHUNK_MB)))
    pages_per_chunk = int(math.ceil((page_count + 1) / chunk_count))
    pages_per_chunk = min(pages_per_chunk, MAX_PDF_PAGES_PER_CHUNK)
    expected_chunk_size_mb = round(size_mb / chunk_count, 3)
    chunks = []
    for i in range(0, chunk_count):
        a = 1 + i * pages_per_chunk
        b = a + pages_per_chunk - 1
        b = min(b, page_count)
        chunks.append(f'{a}-{b}')

    return {
        'size_mb': size_mb,
        'expected_chunk_size_mb': expected_chunk_size_mb,
        'page_count': page_count,
        'chunks': chunks,
    }


def split_pdf_file(path, _range, dest_path):
    """streaming wrapper to split pdf file into a page range."""
    script = (
        " qpdf --empty --no-warn --warning-exit-0 --deterministic-id "
        " --object-streams=generate  --remove-unreferenced-resources=yes "
        " --no-original-object-ids "
        f" --pages '{path}' {_range}  -- '{dest_path}'"
    )
    run_script(script)