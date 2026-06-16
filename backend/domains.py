"""Domain (tag) facet helpers — typed/namespaced domains.

A ``domains`` entry is an optional ``namespace:value`` string. A bare value
(no colon) means the default namespace ``domain``. This lets the SAME flat
``List[str]`` field carry typed tags (e.g. ``"system:Integration"``,
``"phase:Onboarding"``) without a schema change, while existing bare values keep
working unchanged.

Recommended namespaces (a convention, not enforced — curate in the approved
vocabulary): ``domain`` (business/org area, the default), ``system`` (functional
component/standard), ``phase`` (process phase). Bare values are treated as
``domain``.

Matching is namespace-tolerant:
- a BARE query matches by value across any namespace
  (``"Integration"`` matches both ``"Integration"`` and ``"system:Integration"``);
- a NAMESPACED query requires both namespace and value to match
  (``"system:Integration"`` matches only ``"system:Integration"``).
"""
from __future__ import annotations

from typing import Tuple

DEFAULT_NAMESPACE = "domain"


def parse_domain(entry: str) -> Tuple[str, str]:
    """Split a domain entry into (namespace, value). Bare -> (DEFAULT, value)."""
    text = str(entry).strip()
    namespace, sep, value = text.partition(":")
    if sep and namespace.strip() and value.strip():
        return namespace.strip(), value.strip()
    return DEFAULT_NAMESPACE, text


def domain_value(entry: str) -> str:
    """The value part of a domain entry, ignoring any namespace."""
    return parse_domain(entry)[1]


def domain_matches(query: str, entry: str) -> bool:
    """True when ``query`` selects ``entry`` (see module docstring)."""
    if ":" in str(query):
        return parse_domain(query) == parse_domain(entry)
    return domain_value(query) == domain_value(entry)
