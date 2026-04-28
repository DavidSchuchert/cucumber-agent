"""Custom tool loader - dynamically loads Python tools from ~/.cucumber/custom_tools/."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import time
from pathlib import Path

from cucumber_agent.tools.base import BaseTool
from cucumber_agent.tools.registry import ToolRegistry


class CustomToolLoader:
    """Scans a directory for *.py custom tool files and dynamically loads them."""

    def __init__(self, tools_dir: Path | None = None) -> None:
        self._dir = tools_dir or (Path.home() / ".cucumber" / "custom_tools")
        self._last_scan: float = 0.0
        self._mtimes: dict[Path, float] = {}
        self._loaded_tools: dict[Path, list[str]] = {}  # Path -> list of tool names registered

    def load_all(self) -> None:
        """Load (or reload if changed) all custom tools."""
        self._dir.mkdir(parents=True, exist_ok=True)

        current_files = set(self._dir.glob("*.py"))
        removed = set(self._mtimes.keys()) - current_files

        # Unregister tools from deleted files
        for f in removed:
            self._unload_file(f)

        # Load/reload changed files
        for py_file in sorted(current_files):
            mtime = py_file.stat().st_mtime
            if self._mtimes.get(py_file) == mtime:
                continue  # unchanged

            # If it was loaded before, unregister its old tools first
            if py_file in self._mtimes:
                self._unload_file(py_file)

            try:
                self._load_file(py_file)
                self._mtimes[py_file] = mtime
            except Exception as e:
                # Silently skip malformed tools or print to debug log?
                # We'll just skip them so we don't crash the REPL.
                print(f"[dim yellow]Warning: Failed to load custom tool {py_file.name}: {e}[/dim yellow]")

        self._last_scan = time.monotonic()

    def _load_file(self, path: Path) -> None:
        """Dynamically load a python file and register BaseTool subclasses."""
        module_name = f"custom_tools.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            return

        module = importlib.util.module_from_spec(spec)
        # We don't necessarily need to add it to sys.modules unless it has relative imports
        # but adding it is standard.
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        registered_names = []
        for _, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, BaseTool) and obj != BaseTool:
                try:
                    tool_instance = obj()
                    ToolRegistry.register(tool_instance)
                    registered_names.append(tool_instance.name)
                except Exception:
                    pass  # skip if constructor fails

        self._loaded_tools[path] = registered_names

    def _unload_file(self, path: Path) -> None:
        """Unregister tools that were loaded from this file."""
        if path in self._loaded_tools:
            for tool_name in self._loaded_tools[path]:
                ToolRegistry.unregister(tool_name)
            del self._loaded_tools[path]
        self._mtimes.pop(path, None)
        
        module_name = f"custom_tools.{path.stem}"
        if module_name in sys.modules:
            del sys.modules[module_name]

    def needs_reload(self) -> bool:
        """True if any tool file has changed since last load."""
        if not self._dir.exists():
            return False
        for py_file in self._dir.glob("*.py"):
            if self._mtimes.get(py_file) != py_file.stat().st_mtime:
                return True
        return False
