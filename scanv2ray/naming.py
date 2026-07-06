"""Pure helpers for renaming scanned config links.

The client shows the name from a share link's ``#fragment``; renaming a
config therefore means rewriting that fragment.  This module is intentionally
dependency-free (stdlib only) and never raises for malformed input.
"""

from urllib.parse import quote, urlsplit, urlunsplit


def country_flag(code):
    """Convert a 2-letter ISO country code to a regional-indicator flag emoji.

    Empty / falsy input -> '' ; anything that is not two ASCII letters -> ''.
    """
    if not code:
        return ''
    code = code.strip().upper()
    if len(code) != 2 or not code.isalpha() or not code.isascii():
        return ''
    return ''.join(chr(ord(c) - ord('A') + 0x1F1E6) for c in code)


def set_link_fragment(link, name):
    """Return ``link`` with its ``#fragment`` replaced by ``name`` (url-quoted).

    Never raises; on any failure the original link is returned unchanged.
    """
    try:
        parts = urlsplit(link)
        fragment = quote(name, safe='')
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           parts.query, fragment))
    except Exception:
        return link


def apply_naming(results, remark_override, show_country):
    """Rename each result's remark and link fragment in place.

    ``results`` is a list of result dicts (each may have 'link', 'remark',
    'exit_country').  Mutates each dict and also returns the list.  Never
    raises: if a link can't be rewritten the remark is still updated.
    """
    for i, item in enumerate(results):
        try:
            if remark_override:
                base = "{0}-{1}".format(remark_override, i + 1)
            else:
                base = item.get('remark') or 'config'

            if show_country:
                cc = (item.get('exit_country') or '').strip()
                prefix = (country_flag(cc) or '\U0001F310') if cc else '\U0001F310'
                name = "{0} {1}".format(prefix, base)
            else:
                name = base

            item['remark'] = name
            link = item.get('link')
            if link:
                item['link'] = set_link_fragment(link, name)
        except Exception:
            # Best-effort: never let one bad item abort the batch.
            continue
    return results
