"""Wikidata lookup for a track's earliest publication date (P577).

Deliberately loose: matches rdfs:label OR skos:altLabel by prefix, and applies
no entity-type constraint, because tracks are typed inconsistently as song
(Q7366) or single (Q134556). A strict query found 1 of 5 test tracks; this one
found 7 of 8.

Wikidata fails safe: when it has no data it returns nothing rather than a
wrong year, so it can never silently poison the pool.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "Chronotune/0.1 (pishias92@gmail.com)"

QUERY_TEMPLATE = """
SELECT ?song (MIN(?date) AS ?first) WHERE {
  ?artist rdfs:label|skos:altLabel "%(artist)s"@en .
  ?song wdt:P175 ?artist ;
        wdt:P577 ?date ;
        rdfs:label|skos:altLabel ?name .
  FILTER(LANG(?name) = "en" && STRSTARTS(LCASE(STR(?name)), LCASE("%(title)s")))
}
GROUP BY ?song
ORDER BY ?first
LIMIT 5
"""


def _escape(value: str) -> str:
    """Escape backslashes and quotes for a SPARQL string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_query(artist: str, title: str) -> str:
    return QUERY_TEMPLATE % {"artist": _escape(artist), "title": _escape(title)}


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def first_publication_year(artist: str, title: str, *, fetch_json=_fetch_json) -> int | None:
    """Earliest P577 year for a song by this performer, or None."""
    query = build_query(artist, title)
    url = SPARQL_URL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    payload = fetch_json(url)

    years = []
    for binding in payload.get("results", {}).get("bindings", []):
        raw = binding.get("first", {}).get("value", "")
        if len(raw) >= 4 and raw[:4].isdigit():
            years.append(int(raw[:4]))

    return min(years) if years else None
