"""Explicit-only native checker activation for the Hermes Incise skill."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple


CHECK_TOOL_NAME = "md_check"
PRELOAD_MARKER = (
    '[IMPORTANT: The user launched this CLI session with the "incise:incise-check" skill preloaded.'
)

CHECK_TOOL_SCHEMA: Dict[str, Any] = {
    "name": CHECK_TOOL_NAME,
    "description": (
        "Check one Markdown file for Incise structural hazards. Read-only. Returns the exact "
        "versioned JSON report. Available only while the explicit incise-check skill is active."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Markdown file to check."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}


def _tool_name(tool: Any) -> Optional[str]:
    if not isinstance(tool, dict):
        return None
    function = tool.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return tool.get("name") if isinstance(tool.get("name"), str) else None


def _text_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"content", "text", "messages"}:
                yield from _text_values(item)


def has_explicit_skill(request: Dict[str, Any]) -> bool:
    return any(PRELOAD_MARKER in text for text in _text_values(request.get("messages", [])))


def repair_tools(report: Dict[str, Any], available: Iterable[str]) -> Tuple[str, ...]:
    allowed = set(available)
    mapped = []
    for finding in report.get("findings", []):
        if not isinstance(finding, dict):
            continue
        repair = finding.get("repair")
        operation = repair.get("operation") if isinstance(repair, dict) else None
        if not isinstance(operation, str):
            continue
        name = (
            "table_edit" if operation.startswith("table-")
            else "list_edit" if operation.startswith("list-")
            else "section_edit" if operation.startswith("section-")
            else "frontmatter_edit" if operation.startswith("frontmatter-")
            else None
        )
        if name in allowed and name not in mapped:
            mapped.append(name)
    return tuple(mapped)


@dataclass
class CheckState:
    turn_id: str
    checked: bool = False
    repair_tools: Tuple[str, ...] = field(default_factory=tuple)


class CheckSkillAdapter:
    def __init__(self, standard_tools: Iterable[str]) -> None:
        self.standard_tools = tuple(standard_tools)
        self._states: Dict[Tuple[str, str], CheckState] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: Any, task_id: Any) -> Tuple[str, str]:
        return str(session_id or ""), str(task_id or "")

    def observe_report(
        self,
        report: Dict[str, Any],
        *,
        session_id: str = "",
        task_id: str = "",
        turn_id: str = "",
    ) -> None:
        key = self._key(session_id, task_id)
        with self._lock:
            state = self._states.get(key)
            if state is None or (state.turn_id and turn_id and state.turn_id != str(turn_id)):
                state = CheckState(str(turn_id or ""))
                self._states[key] = state
            state.checked = True
            state.repair_tools = repair_tools(report, self.standard_tools)

    def is_active(
        self, *, session_id: str = "", task_id: str = "", turn_id: str = "", **_kwargs: Any
    ) -> bool:
        with self._lock:
            state = self._states.get(self._key(session_id, task_id))
        return bool(
            state
            and not (state.turn_id and turn_id and state.turn_id != str(turn_id))
        )

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
        **_kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        tools = request.get("tools")
        if not isinstance(tools, list):
            return None

        by_name = {name: tool for tool in tools if (name := _tool_name(tool))}
        explicit = has_explicit_skill(request)
        if explicit:
            key = self._key(session_id, task_id)
            with self._lock:
                state = self._states.get(key)
                if state is None or (state.turn_id and turn_id and state.turn_id != str(turn_id)):
                    state = CheckState(str(turn_id or ""))
                    self._states[key] = state
                names = [CHECK_TOOL_NAME]
                if state.checked:
                    names.extend(state.repair_tools)
            narrowed = [by_name[name] for name in names if name in by_name]
            reason = "explicit incise-check skill"
        else:
            narrowed = [tool for tool in tools if _tool_name(tool) != CHECK_TOOL_NAME]
            reason = "md_check hidden outside explicit skill"

        if [_tool_name(tool) for tool in narrowed] == [_tool_name(tool) for tool in tools]:
            return None
        updated = dict(request)
        updated["tools"] = narrowed
        choice = updated.get("tool_choice")
        if isinstance(choice, dict):
            chosen = _tool_name(choice)
            if chosen and chosen not in {_tool_name(tool) for tool in narrowed}:
                updated["tool_choice"] = "auto"
        return {"request": updated, "source": "incise", "reason": reason}
