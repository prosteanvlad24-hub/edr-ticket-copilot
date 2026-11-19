"""Extract candidate indicators without treating account names as DNS names."""

import ipaddress
import re
from urllib.parse import urlsplit

import tldextract

# The bundled public suffix snapshot keeps extraction offline and reproducible.
_SUFFIXES = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
_LOCAL_SUFFIXES = {"example", "test", "invalid", "local", "localhost", "internal", "lan", "corp"}
_URL = re.compile(r"https?://[^\s<>'\"]+", re.I)
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w|\.\d)")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"(?<![\w.-])(?:{_LABEL}\.)+[a-z]{{2,63}}(?![\w-]|\.[a-z0-9-])", re.I)
_ACCOUNT_OR_PATH = re.compile(
    r"""["'](?:[a-z]:[\\/]|\\\\)[^"'\r\n]+["']|(?:[a-z]:[\\/]|\\\\)[^\s<>"']+|[\w.-]+\\[\w.-]+""",
    re.I,
)
_ACCOUNT_FIELD = re.compile(
    r"^\s*(?:user(?:name|\s+name)?|account(?:\s+name)?)\s*:\s*(?:[\w.-]+\\)?[\w.@-]+",
    re.I | re.M,
)
_PARTIAL_HASH = re.compile(
    r"(?:(?P<algorithm>MD5|SHA-?1|SHA-?256)[ \t]*[:=][ \t]*)?"
    r"(?<![a-f0-9])(?P<prefix>[a-f0-9]{4,64})[ \t]*(?:…|\.{3})[ \t]*"
    r"(?P<suffix>[a-f0-9]{4,64})(?![a-f0-9])", re.I,
)
_FULL_HASH = re.compile(r"(?<![a-f0-9])(?:[a-f0-9]{64}|[a-f0-9]{40}|[a-f0-9]{32})(?![a-f0-9])", re.I)
_LABELED_HASH = re.compile(r"\b(MD5|SHA-?1|SHA-?256)[ \t]*[:=][ \t]*([a-f0-9]{4,128})(?![a-f0-9])", re.I)
_HASH_TYPES = {32: "MD5", 40: "SHA1", 64: "SHA256"}
_HASH_LENGTHS = {kind: size for size, kind in _HASH_TYPES.items()}


def _is_domain(candidate: str) -> bool:
    if len(candidate) > 253 or not _DOMAIN.fullmatch(candidate):
        return False
    suffix = candidate.rsplit(".", 1)[-1]
    if suffix in _LOCAL_SUFFIXES:
        return True
    parts = _SUFFIXES(candidate)
    return bool(parts.domain and parts.suffix)


def extract_iocs(description: str) -> dict:
    """Return candidate IPs, URLs, domains, complete hashes, and partial hashes."""
    urls = sorted({match.rstrip(".,);]") for match in _URL.findall(description)})

    ips = set()
    for candidate in _IPV4.findall(description):
        try:
            ips.add(str(ipaddress.IPv4Address(candidate)))
        except ipaddress.AddressValueError:
            pass

    standalone = _ACCOUNT_OR_PATH.sub(" ", _ACCOUNT_FIELD.sub(" ", _URL.sub(" ", description)))
    domains = {candidate for candidate in _DOMAIN.findall(standalone.lower()) if _is_domain(candidate)}
    for url in urls:
        try:
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if _is_domain(host):
            domains.add(host)

    partials = set()
    for match in _PARTIAL_HASH.finditer(description):
        algorithm = (match.group("algorithm") or "").upper().replace("-", "") or None
        fragment = match.group("prefix").lower() + "…" + match.group("suffix").lower()
        partials.add((fragment, algorithm))

    hashes = {kind: set() for kind in _HASH_TYPES.values()}
    without_fragments = _PARTIAL_HASH.sub(" ", description)
    for label, value in _LABELED_HASH.findall(without_fragments):
        algorithm = label.upper().replace("-", "")
        if len(value) == _HASH_LENGTHS[algorithm]:
            hashes[algorithm].add(value.lower())
        elif len(value) < _HASH_LENGTHS[algorithm]:
            partials.add((value.lower(), algorithm))
    for candidate in _FULL_HASH.findall(_LABELED_HASH.sub(" ", without_fragments)):
        hashes[_HASH_TYPES[len(candidate)]].add(candidate.lower())

    return {
        "ipv4": sorted(ips),
        "domains": sorted(domains),
        "urls": urls,
        "hashes": {key: sorted(values) for key, values in hashes.items()},
        "partial_hashes": [
            {"value": value, "algorithm": algorithm}
            for value, algorithm in sorted(partials, key=lambda item: (item[0], item[1] or ""))
        ],
    }
