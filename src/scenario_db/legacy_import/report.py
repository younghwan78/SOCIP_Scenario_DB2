from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ReportLevel = Literal["error", "warning", "info"]


@dataclass(slots=True)
class ImportMessage:
    level: ReportLevel
    code: str
    message: str
    source: str | None = None


@dataclass(slots=True)
class ImportReport:
    messages: list[ImportMessage] = field(default_factory=list)
    generated: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(message.level == "error" for message in self.messages)

    def add(self, level: ReportLevel, code: str, message: str, source: str | None = None) -> None:
        self.messages.append(ImportMessage(level=level, code=code, message=message, source=source))

    def error(self, code: str, message: str, source: str | None = None) -> None:
        self.add("error", code, message, source)

    def warning(self, code: str, message: str, source: str | None = None) -> None:
        self.add("warning", code, message, source)

    def info(self, code: str, message: str, source: str | None = None) -> None:
        self.add("info", code, message, source)

    def increment(self, key: str, count: int = 1) -> None:
        self.generated[key] = self.generated.get(key, 0) + count

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "generated": dict(sorted(self.generated.items())),
            "messages": [
                {
                    "level": message.level,
                    "code": message.code,
                    "message": message.message,
                    **({"source": message.source} if message.source else {}),
                }
                for message in self.messages
            ],
        }

