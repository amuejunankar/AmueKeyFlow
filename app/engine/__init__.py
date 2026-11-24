"""Keyboard engine package.

Heavy modules are imported lazily so that pure helpers (key tables, output
validation) can be used without pulling in the Windows/Qt dependent engine.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MappingEngine", "MappingProcessor", "HookEvent"]


def __getattr__(name: str) -> Any:
    if name == "MappingEngine":
        from app.engine.engine import MappingEngine

        return MappingEngine
    if name in {"MappingProcessor", "HookEvent"}:
        from app.engine.mapping_processor import HookEvent, MappingProcessor

        return {"MappingProcessor": MappingProcessor, "HookEvent": HookEvent}[name]
    raise AttributeError(name)
