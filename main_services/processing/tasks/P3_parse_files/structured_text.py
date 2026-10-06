"""Read unfolded vCard and iCalendar text without binary property values."""
from __future__ import annotations
import base64
import binascii
import re
_BOMS = ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))
_PROPERTY = re.compile('^[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)?(;[^:\\r\\n]*)?:')
_B64_LINE = re.compile('^[A-Za-z0-9+/=]+$')
_MARKER = re.compile('^\\[[A-Z0-9-]+ [^\\]]*removed, \\d+ bytes\\]$')

def decode(data: bytes) -> str:
    for bom, codec in _BOMS:
        if data.startswith(bom):
            return data[len(bom):].decode(codec, errors='replace')
    if len(data) >= 4 and data[1:2] == b'\x00' and (data[3:4] == b'\x00'):
        return data.decode('utf-16-le', errors='replace')
    if len(data) >= 4 and data[0:1] == b'\x00' and data[2:3] == b'\x00':
        return data.decode('utf-16-be', errors='replace')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')

def _params(params: str) -> list[tuple[str, str]]:
    out = []
    for p in params.split(';'):
        if not p:
            continue
        k, sep, v = p.partition('=')
        out.append((k.strip().upper(), v.strip().strip('"') if sep else ''))
    return out

def _is_base64_param(params: str) -> bool:
    for k, v in _params(params):
        if k == 'ENCODING' and v.upper() in ('B', 'BASE64'):
            return True
        if k == 'BASE64' and (not v):
            return True
    return False

def _binary(params: str, value: str) -> tuple[bool, str, int]:
    """Whether the value is binary, its media type, and its decoded size in bytes."""
    media = ''
    for k, v in _params(params):
        if k in ('TYPE', 'MEDIATYPE', 'FMTTYPE') and v:
            media = v.split(',')[0]
        elif not v and k in ('JPEG', 'PNG', 'GIF', 'BMP', 'TIFF', 'WAVE', 'PCM', 'PGP', 'X509'):
            media = k
    value_binary = any((k == 'VALUE' and v.upper() == 'BINARY' for k, v in _params(params)))
    if value.lstrip()[:5].lower() == 'data:':
        header, _s, payload = value.lstrip().partition(',')
        media = header[5:].split(';')[0] or media
        if ';base64' not in header.lower():
            return (True, media, len(payload))
    elif _is_base64_param(params) or value_binary:
        payload = value
    else:
        return (False, media, 0)
    compact = re.sub('\\s+', '', payload)
    try:
        size = len(base64.b64decode(compact + '=' * (-len(compact) % 4)))
    except (binascii.Error, ValueError):
        size = len(compact) * 3 // 4
    return (True, media, size)

def _logical(lines: list[str], kind: str) -> list[list[str]]:
    groups: list[list[str]] = []
    b64_open = False
    for line in lines:
        body = line.rstrip('\r\n')
        if groups and line[:1] in (' ', '\t'):
            groups[-1].append(line)
            continue
        if groups:
            head = groups[-1][0].split(':', 1)[0].upper()
            if groups[-1][-1].rstrip('\r\n').endswith('=') and 'QUOTED-PRINTABLE' in head:
                groups[-1].append(' ' + line)
                continue
            if kind == 'vcard' and b64_open and body and _B64_LINE.match(body) and (not _PROPERTY.match(body)):
                groups[-1].append(' ' + line)
                continue
        groups.append([line])
        name_params = body.split(':', 1)[0]
        b64_open = kind == 'vcard' and ';' in name_params and _is_base64_param(name_params.split(';', 1)[1])
    return groups
_ESCAPES = re.compile('\\\\([nN,;\\\\])')

def _unescape(value: str) -> str:
    return _ESCAPES.sub(lambda m: '\n' if m.group(1) in 'nN' else m.group(1), value)

def structured_text(data: bytes, kind: str) -> str:
    """Return unfolded property lines with binary values removed."""
    text = decode(data)
    out: list[str] = []
    skip_blank = False
    for group in _logical(text.splitlines(keepends=True), kind):
        first = group[0]
        if skip_blank and (not first.strip()):
            skip_blank = False
            continue
        skip_blank = False
        unfolded = ''.join((l.rstrip('\r\n')[1:] if i else l.rstrip('\r\n') for i, l in enumerate(group)))
        if not _PROPERTY.match(unfolded):
            out.extend(group)
            continue
        head, sep, value = unfolded.partition(':')
        if sep and (not _MARKER.match(value.strip())):
            name, _s, params = head.partition(';')
            if '.' in name:
                name = name.rsplit('.', 1)[1]
            is_bin, media, size = _binary(params, value)
            if is_bin:
                skip_blank = _is_base64_param(params)
                if kind == 'vcard':
                    ending = '\r\n' if first.endswith('\r\n') else '\n'
                    media_text = f'{media} ' if media else ''
                    out.append(f'{head}:[{name.upper()} {media_text}removed, {size} bytes]{ending}')
                continue
        if sep:
            ending = '\r\n' if group[-1].endswith('\r\n') else '\n'
            params_u = head.upper()
            if 'QUOTED-PRINTABLE' in params_u:
                import quopri
                charset = 'utf-8'
                for k, v in _params(head.partition(';')[2]):
                    if k == 'CHARSET' and v:
                        charset = v
                raw = group[0].partition(':')[2] + ''.join((l[1:] for l in group[1:]))
                raw = raw.replace('\r\n', '\n').rstrip('\n').encode('latin-1', 'replace')
                try:
                    value = quopri.decodestring(raw).decode(charset, 'replace')
                except LookupError:
                    value = quopri.decodestring(raw).decode('utf-8', 'replace')
            out.append(head + ':' + _unescape(value) + ending)
            continue
        if len(group) > 1 and 'QUOTED-PRINTABLE' in first.split(':', 1)[0].upper():
            out.append(group[0])
            out.extend((l[1:] for l in group[1:]))
            continue
        out.extend(group)
    return ''.join(out)
