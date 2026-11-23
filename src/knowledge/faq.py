import json
import re
from importlib.resources import files
from typing import TypedDict, cast


class Entry(TypedDict):
    id: str
    terms: list[str]
    evidence: str


class FAQ:
    def __init__(self) -> None:
        raw = files("knowledge").joinpath("faq.json").read_text(encoding="utf-8")
        self._entries = cast(list[Entry], json.loads(raw))

    def search(self, query: str) -> dict[str, str]:
        normalized = query.casefold()
        matches = [
            (
                sum(
                    bool(re.search(rf"\b{re.escape(term)}\b", normalized))
                    for term in entry["terms"]
                ),
                entry,
            )
            for entry in self._entries
        ]
        matches.sort(key=lambda item: (-item[0], item[1]["id"]))
        return {entry["id"]: entry["evidence"] for score, entry in matches[:3] if score}
