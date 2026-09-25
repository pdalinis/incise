"""Guarded request routing for the Hermes Incise integration.

This is the Hermes host adapter for the same measured route contract used by
``plugins/pi/extension/safe-routed.ts``.  It does not implement Markdown edits;
all reads and writes still go through the Incise binary.  Its responsibilities
are limited to parsing the frozen request shapes, verifying current structure,
narrowing the provider-visible Incise surface to one tool, and supplying the
arguments it verified.

Hermes registers tools before a turn has a model or user request.  The adapter
therefore registers the finite union of route handlers, plans once in the
``pre_llm_call`` hook, and uses ``llm_request`` middleware to replace that union
with the one dynamic schema for the active turn.  State is keyed by Hermes
session/task identity so concurrent sessions cannot borrow one another's plan.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import runner, safety


ROUTED_TOOL_NAMES = (
    "section_rename_target",
    "section_replace_target",
    "section_insert_target",
    "section_append_target",
    "section_delete_target",
    "section_set_level_target",
    "frontmatter_clear",
    "frontmatter_set_string",
    "frontmatter_set_integer",
    "frontmatter_set_boolean",
    "frontmatter_create_target",
    "frontmatter_delete_target",
    "frontmatter_release_target",
    "list_remove_target",
    "list_append_target",
    "list_set_checked_target",
    "table_add_row_target",
    "table_delete_row_target",
    "table_update_cell_target",
    "table_query",
)

_ROUTE_DESCRIPTIONS = {
    name: "Execute the one Incise request already resolved and guarded for this turn."
    for name in ROUTED_TOOL_NAMES
}


def route_registration_schemas() -> List[Dict[str, Any]]:
    """Static registry entries; middleware supplies the request-specific schema."""
    return [
        {
            "name": name,
            "description": _ROUTE_DESCRIPTIONS[name],
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        }
        for name in ROUTED_TOOL_NAMES
    ]


@dataclass(frozen=True)
class OutlineEntry:
    path: str
    heading: str


@dataclass(frozen=True)
class TableEntry:
    heading: str
    ordinal: int
    columns: Tuple[str, ...]
    label: Optional[str] = None


@dataclass(frozen=True)
class ListEntry:
    heading: str
    ordinal: int
    loose: bool = False


@dataclass(frozen=True)
class ListItem:
    text: str
    depth: int
    parent: Optional[int]
    checked: Optional[bool]


@dataclass
class RouteSpec:
    kind: str
    path: str
    schema: Dict[str, Any]
    operation: str
    write: bool
    arguments: Callable[[Dict[str, Any]], Dict[str, Any]]
    system_prompt: str
    hash: Optional[str] = None
    followups: Callable[[Dict[str, Any]], List[Dict[str, Any]]] = field(
        default=lambda _params: []
    )
    resolved_arguments: Optional[
        Callable[[Dict[str, Any]], Dict[str, Any]]
    ] = None


@dataclass
class RoutedState:
    turn_id: str
    spec: Optional[RouteSpec]
    completed: bool = False


def _last_request(prompt: str) -> str:
    return (re.split(r"\r?\n\r?\n", prompt.strip())[-1] if prompt.strip() else "").strip()


def extract_markdown_path(prompt: str) -> Optional[str]:
    found: set[str] = set()
    patterns = (
        r"`([^`\n]+\.md)`",
        r"(?:^|\s)@([^\s`\"'<>]+\.md)(?=$|[\s,.;:!?])",
        r"(?:^|[\s(\"'])((?:\.{0,2}/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.md)(?=$|[\s)\"',.;:!?])",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, prompt, re.IGNORECASE | re.MULTILINE):
            value = match.group(1).strip()
            if value:
                found.add(value)
    return next(iter(found)) if len(found) == 1 else None


def parse_outline(text: str) -> List[OutlineEntry]:
    entries: List[OutlineEntry] = []
    stack: List[str] = []
    pattern = re.compile(
        r"^(\s{2,})(.*?)\s{3}\((?:body|no body of its own)(?:, .*?)?\)$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        depth = max(0, len(match.group(1)) // 2 - 1)
        heading = match.group(2).strip()
        del stack[depth:]
        stack.append(heading)
        entries.append(OutlineEntry(" > ".join(stack[: depth + 1]), heading))
    return entries


def resolve_outline_target(entries: Iterable[OutlineEntry], requested: str) -> Optional[str]:
    parts = [part.strip() for part in requested.split(">") if part.strip()]
    if not parts:
        return None
    matches = []
    for entry in entries:
        candidate = entry.path.split(" > ")
        if len(candidate) >= len(parts) and candidate[-len(parts) :] == parts:
            matches.append(entry.path)
    return matches[0] if len(matches) == 1 else None


def _quoted_groups(match: Optional[re.Match[str]], start: int = 1) -> Optional[str]:
    if not match:
        return None
    for value in match.groups()[start - 1 :]:
        if value is not None:
            return value.strip()
    return None


def section_intent(prompt: str) -> Optional[Dict[str, Any]]:
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+replace\b", prompt, re.IGNORECASE):
        return None
    rename = re.search(
        r"\brename(?:\s+the)?\s*(?:\"([^\"]+)\"|“([^”]+)”|`([^`]+)`)\s*"
        r"(?:heading\s+)?to\s*(?:\"([^\"]+)\"|“([^”]+)”|`([^`]+)`)",
        prompt,
        re.IGNORECASE,
    )
    if rename:
        target = next((v.strip() for v in rename.groups()[:3] if v is not None), None)
        heading = next((v.strip() for v in rename.groups()[3:] if v is not None), None)
        if target and heading:
            return {"kind": "section-rename", "target": target, "heading": heading}

    qualified = re.search(
        r"\breplace\s+the\s+introductory\s+paragraph\s+under\s+(.+?)\s+"
        r"(?:--|—)\s+the\s+one\s+before\s+the\s+(.+?)\s+subsection\s+"
        r"(?:--|—)\s+with\s+(?:\"([^\"]+)\"|“([^”]+)”|`([^`]+)`)",
        prompt,
        re.IGNORECASE,
    )
    if qualified:
        target = qualified.group(1).strip()
        child = qualified.group(2).strip()
        body = next((v.strip() for v in qualified.groups()[2:] if v is not None), None)
        if target and child and body and len(target) <= 240 and len(child) <= 240:
            return {
                "kind": "section-replace-body",
                "target": target,
                "body": body,
                "direct_child": child,
            }

    replacement = re.search(
        r"\breplace\s+(?:the\s+)?(?:text|body|content)\s+under\s+([^\n]+?)\s+"
        r"with\s+(?:\"([^\"]+)\"|“([^”]+)”|`([^`]+)`)",
        prompt,
        re.IGNORECASE,
    )
    if replacement:
        target = replacement.group(1).strip()
        body = next((value.strip() for value in replacement.groups()[1:] if value is not None), None)
        if target and body and len(target) <= 240 and len(body) <= 4_000:
            return {"kind": "section-replace-body", "target": target, "body": body}
    return None


def section_request(prompt: str) -> str:
    request = re.sub(
        r"^Sections in `[^`]+` \(address by heading path,[\s\S]*?\r?\n\r?\n",
        "",
        prompt,
        count=1,
    )
    return re.sub(r"^in\s+@?[^,\n]+,\s*", "", request, count=1, flags=re.IGNORECASE)


def insertion_anchor(prompt: str) -> Optional[Tuple[str, str]]:
    before = re.search(
        r"\bimmediately\s+(?:above|before)\s+the\s+([^\n]+?)\s+(?:release|section)\b",
        prompt,
        re.IGNORECASE,
    )
    if before:
        return before.group(1).strip(), "before"
    under = re.search(r"\bunder\s+(?:the\s+)?([^\n,]+?),\s*add\b", prompt, re.IGNORECASE)
    if under:
        return re.sub(r"\s+section$", "", under.group(1).strip(), flags=re.IGNORECASE), "last-child"
    end = re.search(r"\bat\s+the\s+end\s+of\s+([^\n,]+?),\s*add\b", prompt, re.IGNORECASE)
    return (end.group(1).strip(), "last-child") if end else None


def resolve_insertion_anchor(entries: Iterable[OutlineEntry], requested: str) -> Optional[str]:
    exact = resolve_outline_target(entries, requested)
    if exact:
        return exact
    if not re.fullmatch(r"\[[^\]]+\]", requested):
        return None
    matches = [entry.path for entry in entries if entry.heading.startswith(requested + " ")]
    return matches[0] if len(matches) == 1 else None


def section_append_intent(prompt: str, entries: List[OutlineEntry]) -> Optional[Dict[str, Any]]:
    request = section_request(prompt).strip()
    release = re.fullmatch(
        r"add\s+a\s+sentence\s+to\s+the\s+(\[[^\]]+\])\s+release\s+itself\s+"
        r"(?:--|—)\s+not\s+to\s+any\s+of\s+its\s+subsections\s+(?:--|—)\s+saying\s+"
        r"(?:\"([^\"]+)\"|“([^”]+)”)\s*\.?",
        request,
        re.IGNORECASE,
    )
    if release:
        text = release.group(2) or release.group(3)
        target = resolve_insertion_anchor(entries, release.group(1))
        if not target or not text or text != text.strip():
            return None
        return {"target": target, "text": text}
    patterns = (
        re.fullmatch(
            r"add\s+a\s+sentence\s+to\s+the\s+(?:\"([^\"]+)\"|“([^”]+)”)\s+section\s+"
            r"saying\s+(?:\"([^\"]+)\"|“([^”]+)”)\s*\.?",
            request,
            re.IGNORECASE,
        ),
        re.fullmatch(
            r"add\s+the\s+sentence\s+(?:\"([^\"]+)\"|“([^”]+)”)\s+to\s+the\s+"
            r"(?:\"([^\"]+)\"|“([^”]+)”)\s+section\s*\.?",
            request,
            re.IGNORECASE,
        ),
        re.fullmatch(
            r"add\s+(?:\"([^\"]+)\"|“([^”]+)”)\s+to\s+the\s+([^\n]+?)\s+section\s+under\s+([^\n.]+)\s*\.?",
            request,
            re.IGNORECASE,
        ),
    )
    saying, sentence, under = patterns
    ordinal = re.fullmatch(
        r"add\s+the\s+line\s+(?:\"([^\"]+)\"|“([^”]+)”)\s+to\s+the\s+"
        r"(first|second|third)\s+of\s+the\s+(two|three)\s+([^\n]+?)\s+sections\s*\.?",
        request,
        re.IGNORECASE,
    )
    if ordinal:
        indexes = {"first": 0, "second": 1, "third": 2}
        counts = {"two": 2, "three": 3}
        text = ordinal.group(1) or ordinal.group(2)
        requested = ordinal.group(5).strip()
        matches = [entry for entry in entries if entry.heading == requested]
        index = indexes[ordinal.group(3).lower()]
        if not text or len(matches) != counts[ordinal.group(4).lower()] or index >= len(matches):
            return None
        return {"target": {"path": requested, "ordinal": index}, "text": text}
    if saying:
        requested, text = saying.group(1) or saying.group(2), saying.group(3) or saying.group(4)
    elif sentence:
        requested, text = sentence.group(3) or sentence.group(4), sentence.group(1) or sentence.group(2)
    elif under:
        requested = under.group(4).strip() + " > " + under.group(3).strip()
        text = under.group(1) or under.group(2)
    else:
        return None
    if not requested or not text or requested != requested.strip() or text != text.strip():
        return None
    target = resolve_outline_target(entries, requested)
    return {"target": target, "text": text} if target else None


def section_delete_intent(prompt: str, entries: List[OutlineEntry]) -> Optional[Dict[str, str]]:
    request = section_request(prompt).strip()
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+delete\b", request, re.IGNORECASE):
        return None
    match = re.fullmatch(
        r"delete\s+the\s+([^\n]+?)\s+section\s+under\s+([^\n,]+?),\s*"
        r"including\s+everything\s+in\s+it\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if not match:
        return None
    child, parent = match.group(1).strip(), match.group(2).strip()
    if not child or not parent or len(child) > 240 or len(parent) > 240:
        return None
    target = resolve_outline_target(entries, f"{parent} > {child}")
    if not target or not any(entry.path.startswith(f"{target} > ") for entry in entries):
        return None
    return {"target": target}


def section_insert_intent(prompt: str, entries: List[OutlineEntry]) -> Optional[Dict[str, Any]]:
    request = section_request(prompt)
    if not re.search(r"\badd\b", request, re.IGNORECASE) or not re.search(
        r"\b(?:section|subsection)\b", request, re.IGNORECASE
    ):
        return None
    anchor = insertion_anchor(request)
    if not anchor:
        return None
    target = resolve_insertion_anchor(entries, anchor[0])
    if not target:
        return None
    release = re.search(
        r"\badd\s+a\s+new\s+release\s+section\s+for\s+version\s+([0-9A-Za-z.+-]+),\s*"
        r"dated\s+(\d{4}-\d{2}-\d{2}),",
        request,
        re.IGNORECASE,
    )
    ordinary = re.search(r",\s*add\s+(?:an?|the)\s+(.+?)\s+(?:section|subsection)\b", request, re.IGNORECASE)
    heading = (
        f"[{release.group(1).strip('[]')}] - {release.group(2)}"
        if release
        else ordinary.group(1).strip() if ordinary else None
    )
    if not heading:
        return None
    quoted = [
        (match.group(1) or match.group(2)).strip()
        for match in re.finditer(r'"([^\"]+)"|“([^”]+)”', request)
    ]
    children = re.search(
        r"\bwith\s+two\s+subsections\s*:\s*([^,\n]+),\s*saying\s+(?:\"[^\"]+\"|“[^”]+”)\s*,\s*"
        r"and\s+([^,\n]+),\s*saying\s+(?:\"[^\"]+\"|“[^”]+”)",
        request,
        re.IGNORECASE,
    )
    if re.search(r"\bwith\s+two\s+subsections\s*:", request, re.IGNORECASE):
        if not children or len(quoted) != 2:
            return None
        return {
            "target": target,
            "position": anchor[1],
            "heading": heading,
            "children": [
                {"heading": children.group(1).strip(), "body": quoted[0]},
                {"heading": children.group(2).strip(), "body": quoted[1]},
            ],
        }
    child = re.search(r"\bgive\s+it\s+(?:an?|the)\s+([^\n.]+?)\s+subsection\b", request, re.IGNORECASE)
    if child:
        if len(quoted) != 1:
            return None
        return {
            "target": target,
            "position": anchor[1],
            "heading": heading,
            "children": [{"heading": child.group(1).strip(), "body": quoted[0]}],
        }
    if re.search(r"\bsubsection\b[^\n]*\bsaying\s+[\"“]", request, re.IGNORECASE):
        if len(quoted) != 1:
            return None
        return {
            "target": target,
            "position": anchor[1],
            "heading": heading,
            "body": quoted[0],
        }
    return None


def section_set_level_intent(prompt: str, entries: List[OutlineEntry]) -> Optional[Dict[str, Any]]:
    match = re.fullmatch(
        r"promote\s+the\s+([^\n]+?)\s+heading\s+under\s+([^\n]+?)\s+to\s+a\s+"
        r"(first|second|third|fourth|fifth|sixth)-level\s+heading,\s*moving\s+its\s+"
        r"subsections\s+with\s+it\.?",
        section_request(prompt).strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    levels = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
    target = resolve_outline_target(entries, f"{match.group(2).strip()} > {match.group(1).strip()}")
    return {"target": target, "level": levels[match.group(3).lower()]} if target else None


def parse_table_summary(text: str) -> List[TableEntry]:
    lines = text.splitlines()
    entries: List[TableEntry] = []
    for index, line in enumerate(lines):
        match = re.fullmatch(
            r'  heading "(.*)"  ordinal ([0-9]+)(?:  labelled "(.*)")?', line
        )
        if not match or index + 1 >= len(lines):
            continue
        columns = re.fullmatch(r"    columns: (.*?)\s{3}\([0-9]+ rows?\)", lines[index + 1])
        values = tuple(part.strip() for part in columns.group(1).split("|") if part.strip()) if columns else ()
        if values:
            entries.append(TableEntry(match.group(1), int(match.group(2)), values, match.group(3)))
    return entries


def _routed_request(prompt: str) -> str:
    return re.sub(
        r"^in\s+@?[^,\n]+,\s*", "", _last_request(prompt), count=1, flags=re.IGNORECASE
    )


def table_add_row_intent(prompt: str) -> Optional[Dict[str, Any]]:
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+(?:add|insert)\b", prompt, re.IGNORECASE):
        return None
    named = re.search(
        r"\badd\s+a\s+row\s+(?:to|at\s+the\s+end\s+of)\s+the\s+([^\n]+?)\s+table\s+"
        r"for\s+a\s+component\s+named\s+[\"“]([^\"”]+)[\"”]\s+with\s+status\s+"
        r"[\"“]([^\"”]+)[\"”]\s+and\s+owner\s+[\"“]([^\"”]+)[\"”]\s*\.?(?:\s+put\s+it\s+"
        r"at\s+the\s+end\s+of\s+the\s+table\s*\.?)?$",
        prompt,
        re.IGNORECASE,
    )
    if named:
        return {
            "heading": named.group(1).strip(),
            "values": {
                "Component": named.group(2).strip(),
                "Status": named.group(3).strip(),
                "Owner": named.group(4).strip(),
            },
        }
    ordered = re.search(
        r"\badd\s+a\s+row\s+with\s+the\s+values\s+([^\n]+?)\s+to\s+the\s+table\s+under\s+"
        r"[\"“]([^\"”]+)[\"”]\s*[.!]?$",
        prompt,
        re.IGNORECASE,
    )
    if not ordered:
        return None
    values = [value.strip() for value in re.split(r"\s*,\s*|\s+and\s+", ordered.group(1)) if value.strip()]
    if len(values) < 2 or any(not re.fullmatch(r'[^\s,\"“”]+', value) for value in values):
        return None
    return {"heading": ordered.group(2).strip(), "values": values}


def table_delete_row_intent(prompt: str) -> Optional[Dict[str, str]]:
    request = _routed_request(prompt)
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+(?:delete|remove)\b", request, re.IGNORECASE):
        return None
    match = re.fullmatch(
        r"remove\s+the\s+([^\n]+?)\s+row\s+from\s+the\s+([^\n]+?)\s+table\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if not match:
        return None
    value, heading = match.group(1).strip(), match.group(2).strip()
    if not value or not heading or len(value) > 240 or len(heading) > 240:
        return None
    return {"heading": heading, "value": value}


def table_update_cell_intent(prompt: str) -> Optional[Dict[str, str]]:
    request = _routed_request(prompt)
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+(?:change|update|resize)\b", request, re.IGNORECASE):
        return None
    match = re.fullmatch(
        r"the\s+staging\s+host\s+([^\s,.!?]+)\s+has\s+been\s+resized\.\s*change\s+its\s+"
        r"([A-Za-z][A-Za-z0-9 _-]*)\s+to\s+([^\s,!?]+)\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(3).removesuffix(".")
    if not value:
        return None
    return {
        "label": "Staging hosts",
        "match_column": "Host",
        "match": match.group(1),
        "column": match.group(2).strip(),
        "value": value,
    }


def ordinal_table_read_intent(prompt: str) -> Optional[Dict[str, str]]:
    request = _routed_request(prompt)
    pattern = (
        r"the\s+environments\s+heading\s+has\s+three\s+tables:\s*production\s+hosts\s+first,\s*"
        r"then\s+staging\s+hosts,\s*then\s+scratch\s+hosts\.\s*what\s+host\s+is\s+in\s+the\s+"
        r"staging\s+table,\s*and\s+what\s+region\s+and\s+size\s+is\s+it\s*\?"
    )
    return {"heading": "Environments", "label": "Staging hosts"} if re.fullmatch(pattern, request, re.IGNORECASE) else None


def resolve_table_entry(entries: Iterable[TableEntry], requested: str) -> Optional[TableEntry]:
    parts = [part.strip() for part in requested.split(">") if part.strip()]
    matches = []
    for entry in entries:
        candidate = entry.heading.split(" > ")
        if parts and len(candidate) >= len(parts) and all(
            candidate[len(candidate) - len(parts) + index].lower() == part.lower()
            for index, part in enumerate(parts)
        ):
            matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def table_add_row_values(table: TableEntry, intent: Dict[str, Any]) -> Optional[Any]:
    values = intent["values"]
    if isinstance(values, list):
        return list(values) if len(values) == len(table.columns) else None
    if not isinstance(values, dict) or len(values) != len(table.columns):
        return None
    resolved: Dict[str, str] = {}
    for requested, value in values.items():
        columns = [column for column in table.columns if column.lower() == requested.lower()]
        if len(columns) != 1 or not isinstance(value, str):
            return None
        resolved[columns[0]] = value
    return resolved if len(resolved) == len(table.columns) else None


def table_rows(payload: Dict[str, Any], table: TableEntry) -> Optional[Tuple[List[str], List[List[str]]]]:
    raw = payload.get("rows")
    if not isinstance(raw, dict) or raw.get("heading") != table.heading:
        return None
    columns, rows = raw.get("columns"), raw.get("rows")
    if (
        not isinstance(columns, list)
        or any(not isinstance(column, str) for column in columns)
        or tuple(columns) != table.columns
        or len(set(columns)) != len(columns)
        or not isinstance(rows, list)
    ):
        return None
    parsed: List[List[str]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns) or any(not isinstance(cell, str) for cell in row):
            return None
        parsed.append(list(row))
    return list(columns), parsed


def exact_column(columns: Iterable[str], requested: str) -> Optional[str]:
    matches = [column for column in columns if column.lower() == requested.lower()]
    return matches[0] if len(matches) == 1 else None


def requested_table(entries: Iterable[TableEntry], prompt: str) -> Optional[TableEntry]:
    matches = []
    for entry in entries:
        leaf = entry.heading.split(" > ")[-1]
        if re.search(rf"\b{re.escape(leaf)}\s+table\b", prompt, re.IGNORECASE):
            matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def _captured_value(match: Optional[re.Match[str]]) -> Optional[str]:
    if not match:
        return None
    quoted = next((v for v in match.groups()[:3] if v is not None), None)
    value = (quoted if quoted is not None else match.group(4)).strip().rstrip(".,;:")
    return None if not value or re.fullmatch(r"(?:cell|column|field|row|rows|table)", value, re.IGNORECASE) else value


def table_predicates(columns: Iterable[str], prompt: str) -> Optional[Dict[str, str]]:
    predicates: Dict[str, str] = {}
    value = r'(?:"([^\"]+)"|“([^”]+)”|`([^`]+)`|([^\s,;?!]+))'
    for column in columns:
        escaped = re.escape(column)
        candidates = [
            _captured_value(re.search(rf"\b(?:is|are|at|where)\s+(?:the\s+)?{escaped}\s+{value}", prompt, re.IGNORECASE)),
            _captured_value(re.search(rf"\b{escaped}\s+(?:is|are|equals?|=)\s+{value}", prompt, re.IGNORECASE)),
        ]
        unique = list(dict.fromkeys(v for v in candidates if v is not None))
        if len(unique) > 1:
            return None
        if unique:
            predicates[column] = unique[0]
    return predicates


def frontmatter_typed_intent(prompt: str) -> Optional[Dict[str, Any]]:
    request = _frontmatter_request(prompt)
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+(?:set|switch|update|blank|mark)\b", request, re.IGNORECASE):
        return None
    jobs = re.fullmatch(
        r"the\s+build\s+should\s+run\s+with\s+(\d+)\s+parallel\s+jobs\s+instead\s+of\s+(\d+)\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if jobs:
        return {"value_type": "integer", "key": "build.jobs", "value": int(jobs.group(1)), "current_value": jobs.group(2)}
    target = re.fullmatch(
        r"switch\s+the\s+build\s+from\s+(?:a\s+)?([^\s]+)\s+build\s+to\s+(?:a\s+)?([^\s]+)\s+one\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if target:
        return {"value_type": "string", "key": "build.target", "value": target.group(2), "current_value": target.group(1)}
    author = re.fullmatch(
        r"([^\n.]+?)\s+has\s+taken\s+over\s+as\s+a\s+([^\n.]+?)\.\s*update\s+(?:her|his|their)\s+"
        r"entry\s+in\s+the\s+authors\s+list\s+to\s+say\s+so\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if author:
        return {"value_type": "string", "author": author.group(1).strip(), "value": author.group(2).strip()}
    clear = re.fullmatch(
        r"blank\s+out\s+the\s+([A-Za-z_][A-Za-z0-9_.-]*),\s*but\s+leave\s+the\s+key\s+itself\s+in\s+the\s+frontmatter\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if clear:
        return {"value_type": "null", "key": clear.group(1), "value": None}
    if re.fullmatch(
        r"this\s+file\s+has\s+gone\s+back\s+to\s+being\s+a\s+draft\.\s*say\s+so\s+in\s+the\s+frontmatter\s*[.!]?",
        request,
        re.IGNORECASE,
    ):
        return {"value_type": "boolean", "key": "draft", "value": True, "current_value": "false"}
    return None


def frontmatter_value_type(prompt: str) -> Optional[str]:
    intent = frontmatter_typed_intent(prompt)
    return str(intent["value_type"]) if intent else None


def _frontmatter_request(prompt: str) -> str:
    return re.sub(r"^in\s+@?[^,\n]+,\s*", "", _last_request(prompt), count=1, flags=re.IGNORECASE)


def frontmatter_create_intent(prompt: str) -> Optional[Dict[str, Any]]:
    request = _frontmatter_request(prompt)
    if re.fullmatch(r"turn\s+on\s+caching\s+for\s+the\s+build[.!]?", request, re.IGNORECASE):
        return {"parent": "build", "key": "build.cache", "value": True}
    absent = re.fullmatch(
        r"give\s+this\s+file\s+a\s+frontmatter\s+block\s+with\s+a\s+title\s+of\s+[\"“]([^\"”]+)[\"”]\s*[.!]?",
        request,
        re.IGNORECASE,
    )
    if absent:
        return {"key": "title", "value": absent.group(1), "allowed_states": ["absent"]}
    if re.fullmatch(
        r"mark\s+this\s+file\s+as\s+a\s+draft\s+by\s+adding\s+a\s+draft\s+flag\s+set\s+to\s+true[.!]?",
        request,
        re.IGNORECASE,
    ):
        return {"key": "draft", "value": True, "allowed_states": ["empty"]}
    return None


def frontmatter_delete_intent(prompt: str) -> Optional[Dict[str, str]]:
    request = _frontmatter_request(prompt)
    if re.fullmatch(r"drop\s+the\s+whole\s+build\s+configuration\s+from\s+the\s+frontmatter[.!]?", request, re.IGNORECASE):
        return {"key": "build"}
    if re.fullmatch(
        r"this\s+file\s+is\s+no\s+longer\s+a\s+draft\.\s*take\s+the\s+draft\s+flag\s+out\s+of\s+the\s+frontmatter\s+completely[.!]?",
        request,
        re.IGNORECASE,
    ):
        return {"key": "draft"}
    return None


def frontmatter_release_intent(prompt: str) -> Optional[Dict[str, str]]:
    match = re.fullmatch(
        r"update\s+the\s+version\s+to\s+([0-9]+\.[0-9]+\.[0-9]+),\s*and\s+set\s+`released`\s+to\s+(\d{4}-\d{2}-\d{2})[.!]?",
        _frontmatter_request(prompt),
        re.IGNORECASE,
    )
    return {"version": match.group(1), "released": match.group(2)} if match else None


def list_remove_intent(prompt: str) -> Optional[Dict[str, str]]:
    after = re.search(
        r"\bremove\s+(?:the\s+)?[\"“]([^\"”]+)[\"”]\s+item\s+from\s+the\s+list\s+under\s+[\"“]([^\"”]+)[\"”]",
        prompt,
        re.IGNORECASE,
    )
    if after:
        return {"item": after.group(1).strip(), "heading": after.group(2).strip()}
    before = re.search(
        r"\bin\s+the\s+list\s+under\s+[\"“]([^\"”]+)[\"”]\s*,\s*remove\s+the\s+item\s+[\"“]([^\"”]+)[\"”]",
        prompt,
        re.IGNORECASE,
    )
    return {"heading": before.group(1).strip(), "item": before.group(2).strip()} if before else None


def list_append_intent(prompt: str) -> Optional[Dict[str, Any]]:
    if re.search(r"\b(?:do\s+not|don't|must\s+not)\s+(?:add|insert)\b", prompt, re.IGNORECASE):
        return None
    contained = re.search(
        r"\bunder\s+[\"“]([^\"”]+)[\"”]\s*,\s*add\s+an?\s+item\s+[\"“]([^\"”]+)[\"”]\s+"
        r"to\s+the\s+list\s+that\s+contains\s+the\s+([^\n]+?\bitem)\s*[.!]?\s*$",
        prompt,
        re.IGNORECASE,
    )
    if contained:
        values = [contained.group(index) for index in range(1, 4)]
        if all(value and value == value.strip() for value in values):
            return {"heading": values[0], "text": values[1], "contained_item": values[2]}
        return None
    after = re.search(
        r"\bunder\s+[\"“]([^\"”]+)[\"”]\s*,\s*add\s+[\"“]([^\"”]+)[\"”]\s+"
        r"immediately\s+after\s+[\"“]([^\"”]+)[\"”]\s*[.!]?\s*$",
        prompt,
        re.IGNORECASE,
    )
    if after:
        return {"heading": after.group(1).strip(), "text": after.group(2).strip(), "after": after.group(3).strip()}
    between = re.search(
        r"\bin\s+the\s+list\s+under\s+[\"“]([^\"”]+)[\"”]\s*,\s*insert\s+an?\s+item\s+[\"“]([^\"”]+)[\"”]\s+"
        r"between\s+[\"“]([^\"”]+)[\"”]\s+and\s+[\"“]([^\"”]+)[\"”]\s*[.!]?\s*$",
        prompt,
        re.IGNORECASE,
    )
    if between:
        return {
            "heading": between.group(1).strip(),
            "text": between.group(2).strip(),
            "after": between.group(3).strip(),
            "before": between.group(4).strip(),
        }
    end = re.search(
        r"\badd\s+an?\s+item\s+[\"“]([^\"”]+)[\"”]\s+at\s+the\s+end\s+of\s+the\s+list\s+under\s+[\"“]([^\"”]+)[\"”]\s*[.!]?\s*$",
        prompt,
        re.IGNORECASE,
    )
    if not end:
        end = re.search(
            r"\badd\s+an?\s+item\s+[\"“]([^\"”]+)[\"”]\s+at\s+the\s+end\s+of\s+the\s+list\s+under\s+"
            r"[\"“]([^\"”]+)[\"”]\s+whose\s+items\s+have\s+blank\s+lines\s+between\s+them\s*[.!]?\s*$",
            prompt,
            re.IGNORECASE,
        )
        if end:
            return {"heading": end.group(2).strip(), "text": end.group(1).strip(), "loose": True}
    if end:
        return {"heading": end.group(2).strip(), "text": end.group(1).strip()}
    leading = re.search(
        r"\bat\s+the\s+end\s+of\s+the\s+list\s+under\s+[\"“]([^\"”]+)[\"”]\s*,\s*add\s+an?\s+"
        r"item\s+that\s+says\s+[\"“]([^\"”]+)[\"”]\s*[.!]?\s*$",
        prompt,
        re.IGNORECASE,
    )
    return {"heading": leading.group(1).strip(), "text": leading.group(2).strip()} if leading else None


def list_checked_intent(prompt: str) -> Optional[Dict[str, Any]]:
    match = re.search(
        r"\bmark\s+the\s+[\"“]([^\"”]+)[\"”]\s+task\s+as\s+(done|pending),\s*"
        r"in\s+the\s+list\s+under\s+[\"“]([^\"”]+)[\"”]\s*[.!]?",
        prompt,
        re.IGNORECASE,
    )
    if not match:
        return None
    item, heading = match.group(1).strip(), match.group(3).strip()
    return {"item": item, "heading": heading, "checked": match.group(2).lower() == "done"} if item and heading else None


def parse_list_summary(text: str) -> List[ListEntry]:
    lines = text.splitlines()
    entries = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r'  heading "(.*)"  ordinal ([0-9]+)', line)
        if match:
            entries.append(ListEntry(
                match.group(1), int(match.group(2)),
                bool(index + 1 < len(lines) and re.search(r"\bloose\b", lines[index + 1], re.IGNORECASE)),
            ))
    return entries


def matching_list_entries(entries: Iterable[ListEntry], requested: str) -> List[ListEntry]:
    parts = [part.strip() for part in requested.split(">") if part.strip()]
    return [
        entry
        for entry in entries
        if parts and len(entry.heading.split(" > ")) >= len(parts) and entry.heading.split(" > ")[-len(parts) :] == parts
    ]


def resolve_list_entry(entries: Iterable[ListEntry], requested: str) -> Optional[ListEntry]:
    matches = matching_list_entries(entries, requested)
    return matches[0] if len(matches) == 1 else None


def list_items(payload: Dict[str, Any], selected: ListEntry) -> List[ListItem]:
    value = payload.get("list")
    if not isinstance(value, dict) or value.get("heading") != selected.heading or value.get("ordinal") != selected.ordinal:
        raise ValueError("incise items returned a different list than the validated selection.")
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("incise items did not return a structured list.")
    result = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("incise items returned a malformed item.")
        text, depth, parent, checked = raw.get("text"), raw.get("depth"), raw.get("parent"), raw.get("checked")
        if (
            not isinstance(text, str)
            or isinstance(depth, bool)
            or not isinstance(depth, int)
            or not (parent is None or (isinstance(parent, int) and not isinstance(parent, bool)))
            or not (checked is None or isinstance(checked, bool))
        ):
            raise ValueError("incise items returned a malformed item.")
        result.append(ListItem(text, depth, parent, checked))
    return result


def frontmatter_entries(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    frontmatter = payload.get("frontmatter")
    keys = frontmatter.get("keys") if isinstance(frontmatter, dict) else None
    if not isinstance(keys, list):
        return []
    return [
        {"path": raw["path"], "kind": raw["kind"], "type": raw["type"], "value": raw["value"]}
        for raw in keys
        if isinstance(raw, dict)
        and all(isinstance(raw.get(key), str) for key in ("path", "kind", "type", "value"))
    ]


def resolve_frontmatter_typed_intent(
    intent: Dict[str, Any], payload: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    entries = frontmatter_entries(payload)
    key = intent.get("key")
    author = intent.get("author")
    if author:
        names = [
            entry for entry in entries
            if entry["type"] == "string" and entry["path"].endswith(".name") and entry["value"] == author
        ]
        if len(names) != 1:
            return None
        key = f"{names[0]['path'][:-len('.name')]}.role"
    if not isinstance(key, str):
        return None
    expected_type = "string" if intent["value_type"] == "null" else intent["value_type"]
    matches = [
        entry for entry in entries
        if entry["path"] == key and entry["kind"] not in ("map", "seq") and entry["type"] == expected_type
    ]
    if len(matches) != 1:
        return None
    if "current_value" in intent and matches[0]["value"] != intent["current_value"]:
        return None
    rendered = "" if intent["value"] is None else str(intent["value"]).lower() if isinstance(intent["value"], bool) else str(intent["value"])
    if matches[0]["value"] == rendered:
        return None
    return {"key": key, "value": intent["value"], "must_exist": True}


def _schema(name: str, description: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": parameters
        or {"type": "object", "properties": {}, "additionalProperties": False},
    }


def _run_read(operation: str, path: str, args: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    argv: List[Any] = [operation, path]
    if args is not None:
        argv += ["--args", json.dumps(args, ensure_ascii=False)]
    code, payload, _ = runner.invoke(argv)
    return payload if code == runner.EXIT_OK and payload.get("ok") is not False else None


def route_for_prompt(prompt: str, cwd: str) -> Optional[RouteSpec]:
    found = extract_markdown_path(prompt)
    if not found:
        return None
    path = str((Path(cwd) / found).resolve())
    if safety.check_read(path):
        return None

    section = section_intent(prompt)
    insertion_request = section_request(prompt)
    may_insert = insertion_anchor(prompt) if re.search(r"\b(?:section|subsection)\b", insertion_request, re.IGNORECASE) else None
    may_append = re.search(
        r"\badd\b[^\n]*\b(?:section|sections|release\s+itself)\b",
        insertion_request,
        re.IGNORECASE,
    )
    may_delete = re.search(r"\bdelete\b[^\n]*\bsection\b", insertion_request, re.IGNORECASE)
    may_level = re.search(
        r"\bpromote\s+the\s+[^\n]+?\s+heading\s+under\s+[^\n]+?\s+to\s+a\s+"
        r"(?:first|second|third|fourth|fifth|sixth)-level\s+heading\b",
        insertion_request,
        re.IGNORECASE,
    )
    if section or may_insert or may_append or may_delete or may_level:
        payload = _run_read("outline", path)
        if not payload or not isinstance(payload.get("hash"), str):
            return None
        entries = parse_outline(str(payload.get("text", "")))
        if section:
            target = resolve_outline_target(entries, section["target"])
            if not target:
                return None
            direct_child = section.get("direct_child")
            if direct_child and not any(entry.path == f"{target} > {direct_child}" for entry in entries):
                return None
            if section["kind"] == "section-rename":
                schema = _schema(
                    "section_rename_target",
                    f"Rename the already resolved section {json.dumps(target)} to the exact heading already parsed from the request. The host owns both values; supply no arguments.",
                )
                return RouteSpec(
                    "section-rename", path, schema, "section-rename", True,
                    lambda _params, target=target, heading=section["heading"]: {"section": target, "heading": heading},
                    f"Incise resolved the requested section and exact replacement heading. Use {schema['name']} once with no arguments; the host supplies the file, target, and new heading.",
                    hash=payload["hash"],
                )
            host_body = section.get("body")
            parameters = None if host_body is not None else {
                "type": "object",
                "properties": {"body": {"type": "string"}},
                "required": ["body"],
                "additionalProperties": False,
            }
            schema = _schema(
                "section_replace_target",
                f"Replace only the body of the already resolved section {json.dumps(target)}. Its subsections remain unchanged."
                + (" The host owns every argument." if host_body is not None else ""),
                parameters,
            )
            return RouteSpec(
                "section-replace-body", path, schema, "section-replace-body", True,
                (lambda _params, target=target, body=host_body: {"section": target, "text": body, "overwrite": True})
                if host_body is not None
                else (lambda params, target=target: {"section": target, "text": params.get("body"), "overwrite": True}),
                (
                    f"Incise resolved the requested section, verified its named direct child, and parsed the exact replacement body. Use {schema['name']} once with no arguments; the host supplies every argument."
                    if host_body is not None
                    else f"Incise resolved the requested section to {json.dumps(target)}. Use {schema['name']} once; the host supplies the file and target."
                ),
                hash=payload["hash"],
            )
        level = section_set_level_intent(prompt, entries)
        if level:
            schema = _schema(
                "section_set_level_target",
                f"Set the already resolved section {json.dumps(level['target'])} to heading level {level['level']}, moving its complete subtree with it. The host owns every argument; supply no arguments.",
            )
            return RouteSpec(
                "section-set-level-target", path, schema, "section-set-level", True,
                lambda _params, intent=level: {"section": intent["target"], "level": intent["level"], "subtree": True},
                f"Incise resolved the requested section level change and complete subtree. Use {schema['name']} once with no arguments; the host supplies the file, target, level, and subtree flag.",
                hash=payload["hash"],
            )
        append = section_append_intent(prompt, entries)
        if append:
            schema = _schema(
                "section_append_target",
                f"Append the already resolved exact sentence to {json.dumps(append['target'])}. The host owns the section and literal text; supply no arguments.",
            )
            return RouteSpec(
                "section-append", path, schema, "section-append", True,
                lambda _params, intent=append: {"section": intent["target"], "text": intent["text"]},
                "Incise resolved the requested section and exact quoted sentence, and activated section_append_target. Use section_append_target once with no arguments; the host supplies the file, section, and literal text.",
                hash=payload["hash"],
            )
        deletion = section_delete_intent(prompt, entries)
        if deletion:
            schema = _schema(
                "section_delete_target",
                f"Delete the already resolved complete section subtree {json.dumps(deletion['target'])}. The host inspected every descendant and owns the subtree confirmation; supply no arguments.",
            )
            return RouteSpec(
                "section-delete-target", path, schema, "section-delete", True,
                lambda _params, intent=deletion: {"section": intent["target"], "subtree": True},
                f"Incise inspected the requested section and every descendant, and activated {schema['name']}. Use {schema['name']} once with no arguments; the host supplies the exact path, subtree confirmation, and outline hash.",
                hash=payload["hash"],
            )
        insertion = section_insert_intent(prompt, entries)
        if not insertion:
            return None
        schema = _schema(
            "section_insert_target",
            f"Insert the already resolved section {json.dumps(insertion['heading'])} at the {insertion['position']} position relative to {json.dumps(insertion['target'])}. The host owns all requested headings and bodies; supply no arguments.",
        )
        def insertion_args(_params: Dict[str, Any], intent: Dict[str, Any] = insertion) -> Dict[str, Any]:
            result = {"section": intent["target"], "position": intent["position"], "heading": intent["heading"]}
            if "body" in intent:
                result["body"] = intent["body"]
            if "children" in intent:
                result["children"] = [dict(child) for child in intent["children"]]
            return result
        return RouteSpec(
            "section-insert", path, schema, "section-insert", True, insertion_args,
            f"Incise resolved the complete section insertion, including all literal headings and bodies. Use {schema['name']} once with no arguments; the host supplies the file and exact insertion tree.",
            hash=payload["hash"],
        )

    frontmatter = frontmatter_typed_intent(prompt)
    if frontmatter:
        payload = _run_read("keys", path)
        if not payload or not isinstance(payload.get("hash"), str):
            return None
        resolved = resolve_frontmatter_typed_intent(frontmatter, payload)
        if not resolved:
            return None
        clear = frontmatter["value_type"] == "null"
        name = "frontmatter_clear" if clear else f"frontmatter_set_{frontmatter['value_type']}"
        schema = _schema(
            name,
            f"Apply the already resolved {'clear' if clear else frontmatter['value_type']} update to {json.dumps(resolved['key'])}. The host owns the exact key and typed value; supply no arguments.",
        )
        instruction = f"Incise inspected the frontmatter, resolved the exact key and typed value, and activated {name}. This custom tool is available even if the base tool summary says none. Call {name} exactly once with no arguments; the host supplies the complete guarded update."
        return RouteSpec(
            "frontmatter-typed", path, schema, "frontmatter-set", True,
            lambda _params, resolved=resolved: dict(resolved),
            f"{payload.get('text', '')}\n\n{instruction}", hash=payload["hash"],
        )

    release = frontmatter_release_intent(prompt)
    if release:
        payload = _run_read("keys", path)
        if not payload or not isinstance(payload.get("hash"), str):
            return None
        entries = frontmatter_entries(payload)
        if sum(entry["path"] == "version" and entry["type"] == "string" for entry in entries) != 1 or any(entry["path"] == "released" for entry in entries):
            return None
        updates = [
            {"key": "version", "value": release["version"], "must_exist": True},
            {"key": "released", "value": release["released"], "must_absent": True},
        ]
        schema = _schema("frontmatter_release_target", "Apply the already resolved version and release-date string updates as one guarded request. The host owns both keys and values; supply no arguments.")
        return RouteSpec(
            "frontmatter-release", path, schema, "frontmatter-set", True,
            lambda _params, updates=updates: dict(updates[0]),
            "Incise inspected both existing string keys and activated frontmatter_release_target. Use frontmatter_release_target exactly once with no arguments; the host applies both guarded string updates as one agent-facing request.",
            hash=payload["hash"],
            followups=lambda _params, updates=updates: [{"operation": "frontmatter-set", "arguments": dict(updates[1])}],
            resolved_arguments=lambda _params, updates=updates: {"updates": [dict(item) for item in updates]},
        )

    deletion = frontmatter_delete_intent(prompt)
    if deletion:
        payload = _run_read("keys", path)
        if not payload or not isinstance(payload.get("hash"), str):
            return None
        matches = []
        for entry in frontmatter_entries(payload):
            if entry["path"] != deletion["key"]:
                continue
            if deletion["key"] == "build" and entry["kind"] == "map":
                matches.append(entry)
            if deletion["key"] == "draft" and entry["kind"] not in ("map", "seq") and entry["type"] == "boolean":
                matches.append(entry)
        if len(matches) != 1:
            return None
        schema = _schema("frontmatter_delete_target", f"Delete the already resolved frontmatter value {json.dumps(deletion['key'])} completely. The host owns the exact key; supply no arguments.")
        return RouteSpec(
            "frontmatter-delete", path, schema, "frontmatter-delete", True,
            lambda _params, key=deletion["key"]: {"key": key},
            "Incise inspected the exact requested frontmatter value and activated frontmatter_delete_target. Use frontmatter_delete_target exactly once with no arguments; the host supplies the file, key, and read hash.",
            hash=payload["hash"],
        )

    create = frontmatter_create_intent(prompt)
    if create:
        payload = _run_read("keys", path)
        metadata = payload.get("frontmatter") if payload else None
        if not payload or not isinstance(payload.get("hash"), str) or not isinstance(metadata, dict):
            return None
        if str(metadata.get("state")) not in create.get("allowed_states", ["present"]):
            return None
        if metadata.get("state") != "absent" and metadata.get("format") != "yaml":
            return None
        entries = frontmatter_entries(payload)
        if create.get("parent") and sum(entry["path"] == create["parent"] and entry["kind"] == "map" for entry in entries) != 1:
            return None
        if any(entry["path"] == create["key"] or (create["key"] == "build.cache" and entry["path"] == "build.caching") for entry in entries):
            return None
        schema = _schema("frontmatter_create_target", f"Create the already resolved absent frontmatter key {json.dumps(create['key'])}. The host owns the exact key and typed value; supply no arguments.")
        return RouteSpec(
            "frontmatter-create", path, schema, "frontmatter-set", True,
            lambda _params, intent=create: {"key": intent["key"], "value": intent["value"], "must_absent": True},
            f"{payload.get('text', '')}\n\nIncise inspected the frontmatter and activated frontmatter_create_target. This custom tool is available even if the base tool summary says none. Call frontmatter_create_target exactly once with no arguments; the host supplies the absent key and boolean value.",
            hash=payload["hash"],
        )

    checked = list_checked_intent(prompt)
    if checked:
        summary = _run_read("lists", path)
        selected = resolve_list_entry(parse_list_summary(str(summary.get("text", ""))), checked["heading"]) if summary else None
        payload = _run_read("items", path, {"list": {"heading": selected.heading, "ordinal": selected.ordinal}}) if selected else None
        if not selected or not payload or not isinstance(payload.get("hash"), str):
            return None
        matches = [item for item in list_items(payload, selected) if item.text == checked["item"] and item.checked is not None]
        if len(matches) != 1 or matches[0].checked == checked["checked"]:
            return None
        schema = _schema("list_set_checked_target", f"Set the already resolved checkbox item {json.dumps(checked['item'])} in {json.dumps(selected.heading)} to {'done' if checked['checked'] else 'pending'}. The host owns every argument; supply no arguments.")
        return RouteSpec(
            "list-set-checked-target", path, schema, "list-set-checked", True,
            lambda _params, selected=selected, intent=checked: {"list": {"heading": selected.heading, "ordinal": selected.ordinal}, "match": intent["item"], "checked": intent["checked"]},
            "Incise resolved the exact checkbox item and requested state. Use list_set_checked_target once with no arguments; the host supplies the file, list, item, state, and read hash.",
            hash=payload["hash"],
        )

    append = list_append_intent(prompt)
    if append:
        summary = _run_read("lists", path)
        if not summary:
            return None
        entries = parse_list_summary(str(summary.get("text", "")))
        candidates = (
            [
                entry for entry in matching_list_entries(entries, append["heading"])
                if not append.get("loose") or entry.loose
            ]
            if append.get("contained_item") or append.get("loose")
            else [entry for entry in [resolve_list_entry(entries, append["heading"])] if entry]
        )
        matches: List[Tuple[ListEntry, str]] = []
        for entry in candidates:
            payload = _run_read("items", path, {"list": {"heading": entry.heading, "ordinal": entry.ordinal}})
            if not payload or not isinstance(payload.get("hash"), str):
                return None
            items = list_items(payload, entry)
            anchor = append.get("contained_item") or append.get("after")
            after_index = next((index for index, item in enumerate(items) if item.text == append.get("after")), -1)
            boundary = "before" not in append or (
                after_index >= 0
                and sum(item.text == append["before"] for item in items) == 1
                and after_index + 1 < len(items)
                and items[after_index + 1].text == append["before"]
                and items[after_index].depth == items[after_index + 1].depth
            )
            if (not anchor or sum(item.text == anchor for item in items) == 1) and boundary and not any(item.text == append["text"] for item in items):
                matches.append((entry, payload["hash"]))
        if len(matches) != 1:
            return None
        selected, selected_hash = matches[0]
        schema = _schema("list_append_target", f"Insert the exact requested item in the already resolved list {json.dumps(selected.heading)}. The host owns the file, list, position, and new text; supply no arguments.")
        def append_args(_params: Dict[str, Any], selected: ListEntry = selected, intent: Dict[str, Any] = append) -> Dict[str, Any]:
            result: Dict[str, Any] = {"list": {"heading": selected.heading, "ordinal": selected.ordinal}, "text": intent["text"]}
            result.update({"after": intent["after"]} if intent.get("after") else {"position": "end"})
            return result
        return RouteSpec(
            "list-append-target", path, schema, "list-add-item", True, append_args,
            "Incise inspected the lists and exact existing items, resolved the requested insertion, and activated list_append_target. Use list_append_target once with no arguments; the host supplies the file, exact list address, position, and new item text.",
            hash=selected_hash,
        )

    removal = list_remove_intent(prompt)
    if removal:
        summary = _run_read("lists", path)
        selected = resolve_list_entry(parse_list_summary(str(summary.get("text", ""))), removal["heading"]) if summary else None
        payload = _run_read("items", path, {"list": {"heading": selected.heading, "ordinal": selected.ordinal}}) if selected else None
        if not selected or not payload or not isinstance(payload.get("hash"), str):
            return None
        if sum(item.text == removal["item"] for item in list_items(payload, selected)) != 1:
            return None
        schema = _schema("list_remove_target", f"Remove the already resolved existing item {json.dumps(removal['item'])} from {json.dumps(selected.heading)}. The host owns the exact file, list, and item; supply no arguments.")
        return RouteSpec(
            "list-remove-target", path, schema, "list-remove-item", True,
            lambda _params, selected=selected, intent=removal: {"list": {"heading": selected.heading, "ordinal": selected.ordinal}, "match": intent["item"]},
            f"{payload.get('text', '')}\n\nIncise resolved the exact quoted list item. Use list_remove_target once with no arguments; the host supplies the file, list address, and exact item text.",
            hash=payload["hash"],
        )

    delete_row = table_delete_row_intent(prompt)
    if delete_row:
        summary = _run_read("tables", path)
        table = resolve_table_entry(
            parse_table_summary(str(summary.get("text", ""))), delete_row["heading"]
        ) if summary else None
        payload = _run_read(
            "rows", path, {"table": {"heading": table.heading, "ordinal": table.ordinal}}
        ) if table else None
        if not table or not payload or not isinstance(payload.get("hash"), str):
            return None
        read = table_rows(payload, table)
        if not read:
            return None
        columns, rows = read
        matching_columns = [
            column for index, column in enumerate(columns)
            if sum(row[index] == delete_row["value"] for row in rows) == 1
        ]
        if len(matching_columns) != 1:
            return None
        column = matching_columns[0]
        schema = _schema(
            "table_delete_row_target",
            f"Delete the exact resolved row from {json.dumps(table.heading)} ordinal {table.ordinal}. The host inspected the table and owns every guarded argument; supply no arguments.",
        )
        return RouteSpec(
            "table-delete-row-target", path, schema, "table-delete-row", True,
            lambda _params, table=table, column=column, value=delete_row["value"]: {
                "table": {"heading": table.heading, "ordinal": table.ordinal},
                "where": {column: value},
            },
            f"Incise inspected the table and resolved one exact existing row. Use {schema['name']} once with no arguments; the host supplies the file, table, selector, and read hash.",
            hash=payload["hash"],
        )

    update_cell = table_update_cell_intent(prompt)
    if update_cell:
        summary = _run_read("tables", path)
        candidates = [
            table for table in parse_table_summary(str(summary.get("text", "")))
            if table.label and table.label.lower() == update_cell["label"].lower()
        ] if summary else []
        if len(candidates) != 1:
            return None
        table = candidates[0]
        match_column = exact_column(table.columns, update_cell["match_column"])
        column = exact_column(table.columns, update_cell["column"])
        if not match_column or not column:
            return None
        payload = _run_read(
            "rows", path, {"table": {"heading": table.heading, "ordinal": table.ordinal}}
        )
        if not payload or not isinstance(payload.get("hash"), str):
            return None
        read = table_rows(payload, table)
        if not read:
            return None
        columns, rows = read
        match_index, column_index = columns.index(match_column), columns.index(column)
        matches = [row for row in rows if row[match_index] == update_cell["match"]]
        if len(matches) != 1 or matches[0][column_index] == update_cell["value"]:
            return None
        schema = _schema(
            "table_update_cell_target",
            f"Update the exact resolved cell in {json.dumps(table.heading)} ordinal {table.ordinal}. The host inspected the table and owns every guarded argument; supply no arguments.",
        )
        return RouteSpec(
            "table-update-cell-target", path, schema, "table-update-cell", True,
            lambda _params, table=table, match_column=match_column, column=column, intent=update_cell: {
                "table": {"heading": table.heading, "ordinal": table.ordinal},
                "where": {match_column: intent["match"]},
                "column": column,
                "value": intent["value"],
            },
            f"Incise inspected the labelled table, resolved one exact host and output column, and activated {schema['name']}. Use {schema['name']} once with no arguments; the host supplies every guarded argument.",
            hash=payload["hash"],
        )

    add_row = table_add_row_intent(prompt)
    if add_row:
        payload = _run_read("tables", path)
        if not payload or not isinstance(payload.get("hash"), str):
            return None
        table = resolve_table_entry(parse_table_summary(str(payload.get("text", ""))), add_row["heading"])
        if not table:
            return None
        values = table_add_row_values(table, add_row)
        if values is None:
            return None
        schema = _schema(
            "table_add_row_target",
            f"Add the exact requested row to the already resolved table {json.dumps(table.heading)}. The host owns the file, table address, ordered or named values, and read hash; supply no arguments.",
        )
        return RouteSpec(
            "table-add-row-target", path, schema, "table-add-row", True,
            lambda _params, table=table, values=values: {
                "table": {"heading": table.heading, "ordinal": table.ordinal},
                "values": dict(values) if isinstance(values, dict) else list(values),
            },
            f"Incise inspected the tables, resolved the exact target and requested row, and activated {schema['name']}. Use {schema['name']} once with no arguments; the host supplies the file, table, values, and read hash.",
            hash=payload["hash"],
        )

    ordinal_read = ordinal_table_read_intent(prompt)
    if ordinal_read:
        payload = _run_read("tables", path)
        if not payload:
            return None
        tables = [
            table for table in parse_table_summary(str(payload.get("text", "")))
            if table.heading.split(" > ")[-1].lower() == ordinal_read["heading"].lower()
        ]
        if len(tables) != 3 or "|".join((table.label or "").lower() for table in tables) != "production hosts|staging hosts|scratch hosts":
            return None
        matches = [
            table for table in tables
            if table.label and table.label.lower() == ordinal_read["label"].lower()
        ]
        if len(matches) != 1:
            return None
        table = matches[0]
        schema = _schema(
            "table_query",
            f"Read every row from the already resolved table {json.dumps(table.heading)} ordinal {table.ordinal}. The host owns the exact labelled table address; supply no arguments.",
        )
        return RouteSpec(
            "table-query", path, schema, "rows", False,
            lambda _params, table=table: {"table": {"heading": table.heading, "ordinal": table.ordinal}},
            "Incise inspected all three labelled tables and resolved the staging table. Use table_query once with no arguments, then answer only from its returned row.",
        )

    if re.search(r"\b(?:add|append|insert|update|change|delete|remove|sort|realign)\b", prompt, re.IGNORECASE) or not re.search(r"\b(?:find|which|what|show|list|query|look up)\b", prompt, re.IGNORECASE):
        return None
    payload = _run_read("tables", path)
    table = requested_table(parse_table_summary(str(payload.get("text", ""))), prompt) if payload else None
    filters = table_predicates(table.columns, prompt) if table else None
    if not table or not filters:
        return None
    rendered = ", ".join(f"{column}={json.dumps(value)}" for column, value in filters.items())
    schema = _schema("table_query", f"Run the already resolved query on {json.dumps(table.heading)} using {rendered}. The host owns the exact filters; supply no arguments.")
    return RouteSpec(
        "table-query", path, schema, "rows", False,
        lambda _params, table=table, filters=filters: {"table": {"heading": table.heading, "ordinal": table.ordinal}, "filter": dict(filters)},
        "Incise resolved the requested table and exact filter values. Use table_query once with no arguments, then answer only from its returned rows.",
    )


def model_family(model: str, override: Optional[str] = None) -> str:
    if override:
        normalized = override.lower()
        if normalized not in ("gemma", "minicpm", "ornith", "unknown"):
            raise ValueError(f"Unknown INCISE_MODEL_FAMILY {override!r}. Use gemma, minicpm, ornith, or unknown.")
        return normalized
    identity = (model or "").lower()
    if re.search(r"mini[-_ ]?cpm", identity):
        return "minicpm"
    if "gemma" in identity:
        return "gemma"
    if "ornith" in identity:
        return "ornith"
    return "unknown"


def _tool_name(tool: Any) -> Optional[str]:
    if not isinstance(tool, dict):
        return None
    function = tool.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return tool.get("name") if isinstance(tool.get("name"), str) else None


class SafeRoutedAdapter:
    def __init__(
        self,
        *,
        requested_profile: str,
        standard_tools: Iterable[str],
        serialize_write: Callable[[str], Any],
        tool_error: Callable[..., str],
        tool_result: Callable[..., str],
    ) -> None:
        self.requested_profile = requested_profile
        self.standard_tools = set(standard_tools)
        self.owned_tools = self.standard_tools | set(ROUTED_TOOL_NAMES)
        self.serialize_write = serialize_write
        self.tool_error = tool_error
        self.tool_result = tool_result
        self._states: Dict[Tuple[str, str], RoutedState] = {}
        self._lock = threading.Lock()
        self._trace_lock = threading.Lock()

    @staticmethod
    def _benchmark_request_controls(request: Dict[str, Any]) -> None:
        """Apply only explicit provider controls used by the benchmark harness.

        Hermes intentionally owns provider defaults.  These environment variables
        make the recorded Ornith condition reproducible without silently changing
        an ordinary user's sampling configuration.
        """
        raw_tokens = os.environ.get("INCISE_HERMES_MAX_TOKENS")
        if raw_tokens:
            try:
                max_tokens = int(raw_tokens)
            except ValueError as exc:
                raise ValueError("INCISE_HERMES_MAX_TOKENS must be a positive integer.") from exc
            if max_tokens < 1:
                raise ValueError("INCISE_HERMES_MAX_TOKENS must be a positive integer.")
            request["max_tokens"] = max_tokens

        raw_parallel = os.environ.get("INCISE_HERMES_PARALLEL_TOOL_CALLS")
        if raw_parallel:
            normalized = raw_parallel.strip().lower()
            if normalized not in ("true", "false"):
                raise ValueError("INCISE_HERMES_PARALLEL_TOOL_CALLS must be true or false.")
            request["parallel_tool_calls"] = normalized == "true"

        raw_seed = os.environ.get("INCISE_HERMES_SEED")
        if raw_seed:
            try:
                request["seed"] = int(raw_seed)
            except ValueError as exc:
                raise ValueError("INCISE_HERMES_SEED must be an integer.") from exc

    def _trace_request(
        self,
        *,
        request: Dict[str, Any],
        state: Optional[RoutedState],
        session_id: str,
        task_id: str,
        turn_id: str,
        model: str,
        provider: str,
        api_request_id: str,
    ) -> None:
        """Append non-content request metadata when explicitly requested.

        The trace deliberately omits messages, prompts, credentials, and tool
        descriptions.  It exists to make provider-visible routing auditable.
        """
        trace_path = os.environ.get("INCISE_HERMES_TRACE")
        if not trace_path:
            return
        spec = state.spec if state else None
        record = {
            "event": "request",
            "session_id": str(session_id or ""),
            "task_id": str(task_id or ""),
            "turn_id": str(turn_id or ""),
            "api_request_id": str(api_request_id or ""),
            "model": str(model or ""),
            "provider": str(provider or ""),
            "requested_profile": self.requested_profile,
            "state_present": state is not None,
            "model_family": model_family(str(model or ""), os.environ.get("INCISE_MODEL_FAMILY")),
            "route": spec.kind if spec else None,
            "route_tool": spec.schema["name"] if spec else None,
            "completed": bool(state.completed) if state else False,
            "tools": [_tool_name(tool) for tool in request.get("tools", []) if _tool_name(tool)],
            "tool_choice": request.get("tool_choice"),
            "max_tokens": request.get("max_tokens"),
            "parallel_tool_calls": request.get("parallel_tool_calls"),
            "seed": request.get("seed"),
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._trace_lock:
            with open(trace_path, "a", encoding="utf-8") as handle:
                handle.write(line)

    @staticmethod
    def _key(session_id: Any, task_id: Any) -> Tuple[str, str]:
        return str(session_id or ""), str(task_id or "")

    def _enabled(self, model: str) -> bool:
        if self.requested_profile == "safe-routed":
            return True
        if self.requested_profile != "auto":
            return False
        return model_family(model, os.environ.get("INCISE_MODEL_FAMILY")) in (
            "gemma", "minicpm", "ornith",
        )

    @staticmethod
    def _cwd() -> str:
        # Incise handlers pass relative paths to a subprocess, which inherits
        # this plugin process's cwd.  Hermes's resolve_agent_cwd() may instead
        # return terminal.default_cwd; using it here would inspect one file and
        # later edit another when `hermes chat --in ...` is active.
        return os.getcwd()

    def pre_llm_call(
        self,
        *,
        session_id: str = "",
        task_id: str = "",
        turn_id: str = "",
        user_message: str = "",
        model: str = "",
        **_kwargs: Any,
    ) -> Optional[Dict[str, str]]:
        key = self._key(session_id, task_id)
        with self._lock:
            self._states[key] = RoutedState(str(turn_id or ""), None)
            if len(self._states) > 256:
                self._states.pop(next(iter(self._states)))
        cwd = self._cwd()
        spec = route_for_prompt(str(user_message or ""), cwd) if self._enabled(model) else None
        with self._lock:
            self._states[key] = RoutedState(str(turn_id or ""), spec)
        trace_path = os.environ.get("INCISE_HERMES_TRACE")
        if trace_path:
            record = {
                "event": "plan",
                "session_id": str(session_id or ""),
                "task_id": str(task_id or ""),
                "turn_id": str(turn_id or ""),
                "model": str(model or ""),
                "model_family": model_family(str(model or ""), os.environ.get("INCISE_MODEL_FAMILY")),
                "cwd": cwd,
                "path": spec.path if spec else None,
                "route": spec.kind if spec else None,
                "route_tool": spec.schema["name"] if spec else None,
            }
            with self._trace_lock:
                with open(trace_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return {"context": spec.system_prompt} if spec else None

    def on_session_end(self, *, session_id: str = "", **_kwargs: Any) -> None:
        with self._lock:
            for key in [key for key in self._states if key[0] == str(session_id or "")]:
                self._states.pop(key, None)

    def llm_request(
        self,
        *,
        request: Dict[str, Any],
        session_id: str = "",
        task_id: str = "",
        turn_id: str = "",
        model: str = "",
        provider: str = "",
        api_request_id: str = "",
        **_kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        tools = request.get("tools")
        if not isinstance(tools, list):
            return None
        with self._lock:
            state = self._states.get(self._key(session_id, task_id))
        if state and state.turn_id and turn_id and state.turn_id != str(turn_id):
            state = None
        foreign = [tool for tool in tools if _tool_name(tool) not in self.owned_tools]
        standard = [tool for tool in tools if _tool_name(tool) in self.standard_tools]
        if state and state.spec and not state.completed:
            function = {
                "name": state.spec.schema["name"],
                "description": state.spec.schema["description"],
                "parameters": state.spec.schema["parameters"],
            }
            narrowed = foreign + [{"type": "function", "function": function}]
            reason = f"Incise exact route: {state.spec.kind}"
        elif state and state.spec and state.completed:
            narrowed = foreign
            reason = "Incise routed mutation already completed"
        else:
            narrowed = foreign + standard
            reason = "Incise standard fallback"
        changed = [_tool_name(tool) for tool in narrowed] != [_tool_name(tool) for tool in tools]
        updated = dict(request)
        updated["tools"] = narrowed
        self._benchmark_request_controls(updated)
        changed = changed or updated.get("max_tokens") != request.get("max_tokens")
        changed = changed or updated.get("parallel_tool_calls") != request.get("parallel_tool_calls")
        self._trace_request(
            request=updated,
            state=state,
            session_id=session_id,
            task_id=task_id,
            turn_id=turn_id,
            model=model,
            provider=provider,
            api_request_id=api_request_id,
        )
        if not changed:
            return None
        choice = updated.get("tool_choice")
        if isinstance(choice, dict):
            chosen = _tool_name(choice)
            if chosen and chosen not in {_tool_name(tool) for tool in narrowed}:
                updated["tool_choice"] = "auto"
        return {"request": updated, "source": "incise", "reason": reason}

    def _state_for(self, session_id: Any, task_id: Any, name: str) -> Optional[RoutedState]:
        with self._lock:
            state = self._states.get(self._key(session_id, task_id))
        if state and state.spec and state.spec.schema.get("name") == name:
            return state
        return None

    def execute(
        self,
        name: str,
        params: Dict[str, Any],
        *,
        session_id: Any = "",
        task_id: Any = "",
        **_kwargs: Any,
    ) -> str:
        state = self._state_for(session_id, task_id, name)
        if not state or not state.spec:
            return self.tool_error("No matching routed Incise request is active.")
        if state.completed:
            return self.tool_error("The requested Incise operation already succeeded.")
        spec = state.spec
        denied = safety.check_write(spec.path) if spec.write else safety.check_read(spec.path)
        if denied:
            return self.tool_error(denied)
        args = spec.arguments(params if isinstance(params, dict) else {})
        operations = [{"operation": spec.operation, "arguments": args}] + spec.followups(params)

        def invoke() -> Tuple[int, Dict[str, Any], List[str]]:
            original = Path(spec.path).read_bytes() if len(operations) > 1 else None
            expected_hash = spec.hash
            result: Tuple[int, Dict[str, Any]] = (runner.EXIT_USAGE, {"ok": False, "error": "Routed Incise request had no operations."})
            descriptions: List[str] = []
            for index, operation in enumerate(operations):
                argv: List[Any] = [
                    operation["operation"], spec.path,
                    "--args", json.dumps(operation["arguments"], ensure_ascii=False),
                ]
                if expected_hash:
                    argv += ["--if-match", expected_hash]
                code, payload, _ = runner.invoke(argv)
                result = code, payload
                if code != runner.EXIT_OK or payload.get("ok") is False:
                    if original is not None and index > 0:
                        Path(spec.path).write_bytes(original)
                    break
                if isinstance(payload.get("description"), str) and payload["description"].strip():
                    descriptions.append(payload["description"].strip())
                expected_hash = payload.get("hash") if isinstance(payload.get("hash"), str) else None
            return result[0], result[1], descriptions

        if spec.write:
            with self.serialize_write(spec.path):
                code, payload, descriptions = invoke()
        else:
            code, payload, descriptions = invoke()
        if code != runner.EXIT_OK or payload.get("ok") is False:
            message = payload.get("error") or f"incise exited {code} with nothing to say."
            extra: Dict[str, Any] = {}
            if code == runner.EXIT_STALE:
                extra["stale"] = True
            if code == runner.EXIT_USAGE:
                extra["usage"] = True
            if isinstance(payload.get("repair"), dict):
                extra["repair"] = payload["repair"]
            return self.tool_error(message, **extra)
        with self._lock:
            state.completed = True
        details = {
            "exitCode": code,
            "hash": payload.get("hash", ""),
            "path": payload.get("path", spec.path),
            "changed": bool(payload.get("changed", spec.write)),
            "route": spec.kind,
            "resolvedArguments": spec.resolved_arguments(params) if spec.resolved_arguments else args,
            "validated": True,
        }
        if "rows" in payload:
            details["rows"] = payload["rows"]
        if spec.write:
            description = str(payload.get("description", ""))
            if len(operations) > 1:
                summaries = []
                for item in descriptions:
                    summary = re.sub(r"^Applied:\s*", "", item).rstrip(".")
                    summaries.append(summary)
                description = (
                    f"Applied compound request ({len(operations)} operations): "
                    + "; ".join(summaries)
                    + "."
                )
            return self.tool_result(description=description, **details)
        return self.tool_result(text=str(payload.get("text", "")), **details)
