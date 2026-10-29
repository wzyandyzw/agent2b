"""Small, source-grounded local knowledge search for the CLI demo."""
from __future__ import annotations

import pathlib
import re

from agent_app.contracts import ToolSpec


SPEC = ToolSpec(
    name="search_knowledge",
    description="检索公司资料、产品说明和业务规则，返回原文片段与来源文件。只读。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要检索的关键词或问题"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)


def _terms(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text.lower())
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9._-]+", text)
    terms: set[str] = set()
    for chunk in chunks:
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            terms.update(chunk[i : i + 2] for i in range(max(0, len(chunk) - 1)))
        else:
            terms.add(chunk)
    return terms


class SearchKnowledge:
    spec = SPEC

    def __init__(self, root: str | pathlib.Path) -> None:
        self.root = pathlib.Path(root)

    def run(self, args: dict, *, timeout_s: float) -> dict:
        del timeout_s
        query_terms = _terms(args["query"])
        hits: list[dict] = []
        if self.root.exists():
            for path in sorted(self.root.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.stem)
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
                for index, paragraph in enumerate(paragraphs):
                    score = sum(paragraph.lower().count(term) for term in query_terms)
                    if score:
                        hits.append({
                            "source": str(path.relative_to(self.root)).replace("\\", "/"),
                            "title": title,
                            "paragraph": index + 1,
                            "score": score,
                            "excerpt": re.sub(r"\s+", " ", paragraph)[:500],
                        })
        hits.sort(key=lambda item: (-item["score"], item["source"], item["paragraph"]))
        return {"query": args["query"], "results": hits[: int(args.get("limit") or 3)]}
