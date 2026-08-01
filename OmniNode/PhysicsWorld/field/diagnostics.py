"""不依赖 Blender 的 Field 诊断值对象。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldDiagnosticV0:
    code: str
    message: str
    field_id: str = ""
    severity: str = "ERROR"

    def __post_init__(self) -> None:
        code = str(self.code or "").strip()
        message = str(self.message or "").strip()
        severity = str(self.severity or "ERROR").strip().upper()
        if not code:
            raise ValueError("Field diagnostic code 不能为空")
        if not message:
            raise ValueError("Field diagnostic message 不能为空")
        if severity not in {"INFO", "WARNING", "ERROR"}:
            raise ValueError(f"不支持的 Field diagnostic severity: {severity}")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "field_id", str(self.field_id or ""))
        object.__setattr__(self, "severity", severity)

    def debug_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "field_id": self.field_id,
            "severity": self.severity,
        }


__all__ = ["FieldDiagnosticV0"]
