"""Small streaming Turtle reader for the project's generated O*NET data.

The O*NET ABox is large (hundreds of megabytes).  Pulling it into a general
purpose RDF library is unnecessary for indexing: the files generated for this
project use a predictable Turtle shape with one named subject per block,
followed by predicate/object lists.  This module reads that shape without
loading the complete graph into memory.

It is deliberately *not* a general Turtle parser.  It handles the constructs
used by ``onet_abox.ttl``, the i18n overlay, and the project's own config
files: prefixed names, IRIs, short literals with optional language/datatype,
``a``, ``;`` and ``,``.  Blank-node and collection objects are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, Mapping, Optional, Sequence, Set, Tuple

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
XSD_DECIMAL = "http://www.w3.org/2001/XMLSchema#decimal"
XSD_DOUBLE = "http://www.w3.org/2001/XMLSchema#double"
XSD_FLOAT = "http://www.w3.org/2001/XMLSchema#float"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


@dataclass(frozen=True)
class Term:
    """A tiny RDF term representation."""

    kind: str  # "iri", "literal", or "bnode"
    value: str
    lang: Optional[str] = None
    datatype: Optional[str] = None

    @property
    def is_iri(self) -> bool:
        return self.kind == "iri"

    @property
    def is_literal(self) -> bool:
        return self.kind == "literal"

    def python_value(self) -> object:
        """Return a convenient Python value for literals."""

        if self.kind != "literal":
            return self.value
        dt = self.datatype
        if dt in (XSD_INTEGER,):
            try:
                return int(self.value)
            except ValueError:
                return self.value
        if dt in (XSD_DECIMAL, XSD_DOUBLE, XSD_FLOAT):
            try:
                return float(self.value)
            except ValueError:
                return self.value
        if dt == XSD_BOOLEAN:
            return self.value.strip().lower() in {"true", "1"}
        return self.value


def local_name(iri: str) -> str:
    """Return the local part of an IRI (best effort, no RDF dependency)."""

    if not iri:
        return ""
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[1]
    if ":" in iri:
        return iri.rsplit(":", 1)[1]
    return iri


def parse_prefixes(line: str) -> Optional[Tuple[str, str]]:
    """Parse a Turtle @prefix/PREFIX declaration.

    Returns ``(prefix, namespace)`` or ``None`` when the line is not a prefix
    declaration.
    """

    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("@prefix"):
        body = stripped[len("@prefix") :].strip()
    elif stripped.upper().startswith("PREFIX "):
        body = stripped[len("PREFIX ") :].strip()
    else:
        return None
    if not body.endswith("."):
        # Some generators omit the trailing dot.  Be forgiving.
        body = body.rstrip(".").strip()
    else:
        body = body[:-1].strip()
    if ":" not in body:
        return None
    prefix, rest = body.split(":", 1)
    prefix = prefix.strip()
    rest = rest.strip()
    if not (rest.startswith("<") and rest.endswith(">")):
        return None
    return prefix, rest[1:-1]


def _skip_balanced(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    i = start
    in_string = False
    escaped = False
    while i < len(text):
        c = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == opening:
                depth += 1
            elif c == closing:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return i


def _unescape(text: str) -> str:
    """Decode Turtle string escapes without mangling non-ASCII text."""

    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(text):
            out.append("\\")
            break
        e = text[i]
        i += 1
        if e == "n":
            out.append("\n")
        elif e == "r":
            out.append("\r")
        elif e == "t":
            out.append("\t")
        elif e == "b":
            out.append("\b")
        elif e == "f":
            out.append("\f")
        elif e in {'"', "'", "\\"}:
            out.append(e)
        elif e == "u" and i + 4 <= len(text):
            try:
                out.append(chr(int(text[i : i + 4], 16)))
                i += 4
            except ValueError:
                out.append("\\u")
        elif e == "U" and i + 8 <= len(text):
            try:
                out.append(chr(int(text[i : i + 8], 16)))
                i += 8
            except ValueError:
                out.append("\\U")
        else:
            out.append(e)
    return "".join(out)


def _expand_prefixed(raw: str, prefixes: Mapping[str, str]) -> str:
    if ":" not in raw:
        return raw
    prefix, local = raw.split(":", 1)
    namespace = prefixes.get(prefix)
    if namespace is None:
        # Unknown prefix: return the token unchanged so callers can decide.
        return raw
    return namespace + local


def _read_datatype(text: str, start: int, prefixes: Mapping[str, str]) -> Tuple[Optional[str], int]:
    """Read the datatype after ``^^``.  Returns (iri-or-raw, next index)."""

    i = start
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return None, i
    if text[i] == "<":
        end = text.find(">", i + 1)
        if end < 0:
            return None, len(text)
        return text[i + 1 : end], end + 1
    j = i
    while j < len(text) and not text[j].isspace() and text[j] not in ";,.[]()":
        j += 1
    return _expand_prefixed(text[i:j], prefixes), j


def tokenize(text: str, prefixes: Mapping[str, str]) -> Sequence[object]:
    """Tokenize one Turtle subject block.

    ``Term`` objects represent RDF terms.  The strings ``";"``, ``","`` and
    ``"."`` are punctuation.  The string ``"a"`` is the short form of
    ``rdf:type``.
    """

    tokens: list[object] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "#":
            nl = text.find("\n", i)
            if nl < 0:
                break
            i = nl + 1
            continue
        if c in ";,.":
            tokens.append(c)
            i += 1
            continue
        if c == "[":
            i = _skip_balanced(text, i, "[", "]")
            tokens.append(Term("bnode", "_anon"))
            continue
        if c == "(":
            i = _skip_balanced(text, i, "(", ")")
            tokens.append(Term("bnode", "_list"))
            continue
        if c in "])":
            i += 1
            continue
        if c == "<":
            end = text.find(">", i + 1)
            if end < 0:
                raise ValueError("unterminated IRI in Turtle block")
            tokens.append(Term("iri", text[i + 1 : end]))
            i = end + 1
            continue
        if c == '"':
            i += 1
            buf: list[str] = []
            escaped = False
            while i < n:
                ch = text[i]
                if escaped:
                    buf.append("\\")
                    buf.append(ch)
                    escaped = False
                    i += 1
                    continue
                if ch == "\\":
                    escaped = True
                    i += 1
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.append(ch)
                i += 1
            value = _unescape("".join(buf))
            lang: Optional[str] = None
            datatype: Optional[str] = None
            if i < n and text[i] == "@":
                j = i + 1
                while j < n and (text[j].isalnum() or text[j] in "-_"):
                    j += 1
                lang = text[i + 1 : j]
                i = j
            elif i + 1 < n and text[i : i + 2] == "^^":
                datatype, i = _read_datatype(text, i + 2, prefixes)
            tokens.append(Term("literal", value, lang=lang, datatype=datatype))
            continue

        j = i
        while j < n and not text[j].isspace() and text[j] not in ";,.[]()":
            j += 1
        raw = text[i:j]
        if not raw:
            i += 1
            continue
        if raw == "a":
            tokens.append("a")
        elif raw.startswith("_:"):
            tokens.append(Term("bnode", raw))
        elif ":" in raw:
            tokens.append(Term("iri", _expand_prefixed(raw, prefixes)))
        elif raw.lower() in {"true", "false"}:
            tokens.append(Term("literal", raw, datatype=XSD_BOOLEAN))
        else:
            # Bare numeric or unquoted token; keep it usable.
            try:
                if "." in raw:
                    float(raw)
                    datatype = XSD_DECIMAL
                else:
                    int(raw)
                    datatype = XSD_INTEGER
            except ValueError:
                datatype = None
            tokens.append(Term("literal", raw, datatype=datatype))
        i = j
    return tokens


def parse_block(
    text: str,
    prefixes: Mapping[str, str],
    drop_predicates: Optional[Set[str]] = None,
) -> Optional[Tuple[Term, Dict[str, list[Term]]]]:
    """Parse one subject block into ``(subject, {predicate: [objects]})``."""

    tokens = tokenize(text, prefixes)
    if not tokens:
        return None
    subject = tokens[0]
    if not isinstance(subject, Term) or subject.kind != "iri":
        # Blank-node-heavy schema blocks are not needed by the indexer.
        return None
    idx = 1
    predicates: Dict[str, list[Term]] = {}
    drop = drop_predicates or set()
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok == ";":
            idx += 1
            continue
        if tok == ".":
            break
        if tok == "a":
            pred = RDF_TYPE
            idx += 1
        elif isinstance(tok, Term) and tok.kind == "iri":
            pred = tok.value
            idx += 1
        else:
            # Unknown construct; move on defensively.
            idx += 1
            continue

        objects: list[Term] = []
        while idx < n:
            obj = tokens[idx]
            if obj == ",":
                idx += 1
                continue
            if obj == ";" or obj == ".":
                break
            if isinstance(obj, Term):
                if obj.kind == "iri" or obj.kind == "literal":
                    objects.append(obj)
                idx += 1
            else:
                idx += 1
        if pred not in drop and objects:
            predicates.setdefault(pred, []).extend(objects)
        if idx < n and tokens[idx] == ";":
            idx += 1
            continue
        if idx < n and tokens[idx] == ".":
            break
    return subject, predicates


def iter_blocks(
    path: str | Path,
    drop_predicates: Optional[Set[str]] = None,
    prefixes: Optional[Dict[str, str]] = None,
) -> Iterator[Tuple[Term, Dict[str, list[Term]]]]:
    """Yield named-subject blocks from a Turtle file.

    ``prefixes`` is updated in place as declarations are encountered.  Callers
    can pass a shared dictionary when processing several files with a common
    vocabulary.
    """

    path = Path(path)
    prefixes = prefixes if prefixes is not None else {}
    drop = drop_predicates or set()
    lines: list[str] = []

    def flush() -> Optional[Tuple[Term, Dict[str, list[Term]]]]:
        if not lines:
            return None
        text = "\n".join(lines)
        lines.clear()
        return parse_block(text, prefixes, drop)

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                block = flush()
                if block is not None:
                    yield block
                continue
            if stripped.startswith("@prefix") or stripped.upper().startswith("PREFIX "):
                # Prefix declarations should not be inside a block; flush first
                # if a generator omitted a separating blank line.
                if lines:
                    block = flush()
                    if block is not None:
                        yield block
                parsed = parse_prefixes(line)
                if parsed:
                    prefixes[parsed[0]] = parsed[1]
                continue
            if stripped.startswith("@base") or stripped.upper().startswith("BASE "):
                continue
            # Some validation samples use one complete triple per line rather
            # than indented blocks.  A top-level line ending in "." is such a
            # triple; flush the current block first.
            if line and not line[0].isspace() and stripped.endswith("."):
                if lines:
                    block = flush()
                    if block is not None:
                        yield block
                parsed = parse_block(stripped, prefixes, drop)
                if parsed is not None:
                    yield parsed
                continue
            lines.append(line)

    block = flush()
    if block is not None:
        yield block


def first(predicates: Mapping[str, list[Term]], predicate: str) -> Optional[Term]:
    values = predicates.get(predicate)
    return values[0] if values else None


def literal_value(
    predicates: Mapping[str, list[Term]],
    predicate: str,
    default: Optional[str] = None,
) -> Optional[str]:
    term = first(predicates, predicate)
    if term is None or term.kind != "literal":
        return default
    return term.value


def numeric_value(
    predicates: Mapping[str, list[Term]],
    predicate: str,
    default: Optional[float] = None,
) -> Optional[float]:
    term = first(predicates, predicate)
    if term is None:
        return default
    value = term.python_value()
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def iri_value(
    predicates: Mapping[str, list[Term]],
    predicate: str,
    default: Optional[str] = None,
) -> Optional[str]:
    term = first(predicates, predicate)
    if term is None or term.kind != "iri":
        return default
    return term.value


def iri_values(predicates: Mapping[str, list[Term]], predicate: str) -> list[str]:
    return [t.value for t in predicates.get(predicate, []) if t.kind == "iri"]


def literal_values(
    predicates: Mapping[str, list[Term]],
    predicate: str,
    lang: Optional[str] = None,
) -> list[Term]:
    values = [t for t in predicates.get(predicate, []) if t.kind == "literal"]
    if lang is None:
        return values
    return [t for t in values if (t.lang or "").lower() == lang.lower()]


def types(predicates: Mapping[str, list[Term]]) -> list[str]:
    return iri_values(predicates, RDF_TYPE)
