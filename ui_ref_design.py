#!/usr/bin/env python3
"""Structured game UX/UI contracts and deterministic design outputs.

This module extends ``ui-ref`` without changing the reference collector.  The
collector supplies evidence; this module turns that evidence and a GDD into a
versionable contract which can be validated, rendered, reviewed, prototyped,
and handed to a game engine.

The implementation intentionally uses the Python standard library only.  AI
agents author or refine the JSON contracts and ``.uiwire`` files while the CLI
owns deterministic validation and compilation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse


DESIGN_SCHEMA_VERSION = "1.0"
DESIGN_WORKSPACE = "ui_design"
STATUS_ORDER = ("draft", "reviewed", "approved", "deprecated")
ALLOWED_TRANSITIONS = {
    "draft": {"reviewed"},
    "reviewed": {"draft", "approved"},
    "approved": {"draft", "deprecated"},
    "deprecated": {"draft"},
}
INTERACTIVE_TYPES = {"button", "input", "toggle", "slider", "tab", "slot", "list_item"}
ELEMENT_TYPES = INTERACTIVE_TYPES | {"panel", "rect", "text", "bar", "image", "icon", "container"}
REQUIRED_INTERACTIVE_STATES = {
    "default", "hover", "focused", "pressed", "selected", "disabled", "locked",
    "loading_entry", "loading_data", "empty", "error",
}
ENGINE_CHOICES = ("unity-uitoolkit", "unity-ugui", "godot", "cocos")
REFERENCE_SOURCE_TYPES = {"local_reference", "analysis_evidence"}
REFERENCE_SYNC_STATES = {"present", "missing", "invalid_path", "hash_mismatch"}
QUALITY_GATE_DEFAULTS = {
    "approved_requires_references_or_exception": True,
    "approved_requires_acceptance": True,
    "approved_requires_accessibility": True,
    "approved_requires_input_parity": True,
    "approved_requires_no_open_questions": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(value: str, fallback: str = "item") -> str:
    value = re.sub(r"[^\w.-]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-._")
    return value[:100] or fallback


def _portable_id(value: str, fallback: str = "item") -> str:
    """Create an engine- and filename-portable canonical contract ID."""
    original = str(value or "").strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", original.lower()).strip("-")
    if normalized and not normalized[0].isalpha():
        normalized = f"{fallback}-{normalized}"
    if not normalized:
        suffix = hashlib.sha256(original.encode("utf-8")).hexdigest()[:8]
        normalized = f"{fallback}-{suffix}"
    return normalized[:100].rstrip("-")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temp_name).unlink(missing_ok=True)
        raise


def _write_json(path: Path, data: Any) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _write_text_transaction(updates: list[tuple[Path, str]]) -> None:
    """Commit several UTF-8 files together, restoring every original on failure."""
    paths = [path for path, _ in updates]
    if len(set(paths)) != len(paths):
        raise ValueError("A file transaction cannot contain duplicate target paths.")
    for path in paths:
        if (path.exists() or path.is_symlink()) and (not path.is_file() or path.is_symlink()):
            raise ValueError(f"Refusing to replace a non-file or symbolic-link transaction target: {path}")
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    completed = False
    try:
        for path, content in updates:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.stage-", suffix=".tmp", dir=str(path.parent))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            staged[path] = Path(temp_name)

        for path, _ in updates:
            backup: Path | None = None
            if path.exists():
                fd, backup_name = tempfile.mkstemp(prefix=f".{path.name}.backup-", suffix=".tmp", dir=str(path.parent))
                os.close(fd)
                backup = Path(backup_name)
                backup.unlink()
                os.replace(path, backup)
            backups[path] = backup
            os.replace(staged[path], path)
            committed.append(path)
        completed = True
    except Exception:
        for path in reversed(committed):
            path.unlink(missing_ok=True)
        for path, backup in backups.items():
            if backup is not None and backup.exists():
                os.replace(backup, path)
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
        for backup in backups.values():
            if completed and backup is not None and backup.exists():
                try:
                    backup.unlink()
                except OSError as exc:
                    print(f"WARNING Transaction backup could not be removed: {backup} ({exc})")


def _write_json_transaction(updates: list[tuple[Path, Any]]) -> None:
    """Commit several JSON documents together, restoring every original on failure."""
    _write_text_transaction([(path, _json_text(data)) for path, data in updates])


def _replace_generated_directory(staging: Path, target: Path) -> None:
    """Swap a fully generated sibling directory into place without stale files."""
    parent = target.parent.resolve()
    staging_resolved = staging.resolve()
    target_resolved = target.resolve()
    if staging_resolved.parent != parent or target_resolved.parent != parent:
        raise ValueError("Generated-directory swap targets must be exact siblings in the intended output directory.")
    if staging_resolved == target_resolved or target.name in {"", ".", ".."}:
        raise ValueError("Refusing an unsafe generated-directory replacement target.")
    if not staging.is_dir() or staging.is_symlink():
        raise ValueError("Generated-directory staging must be a real directory.")
    if (target.exists() or target.is_symlink()) and (not target.is_dir() or target.is_symlink()):
        raise ValueError(f"Refusing to replace a non-directory output path: {target}")
    backup: Path | None = None
    try:
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{target.name}.backup-", dir=str(parent)))
            backup.rmdir()
            os.replace(target, backup)
        os.replace(staging, target)
    except Exception:
        if target.exists() and target.resolve().parent == parent:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        if backup is not None and backup.exists():
            os.replace(backup, target)
        raise
    if backup is not None and backup.exists():
        if backup.resolve().parent != parent:
            print(f"WARNING Prior generated-output backup was left in place because its resolved location changed: {backup}")
            return
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            print(f"WARNING Generated output was replaced, but the prior backup could not be removed: {backup} ({exc})")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _project_root(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "project_root", ".")).resolve()


def _design_root(args: argparse.Namespace) -> Path:
    root = _project_root(args)
    explicit = getattr(args, "design_root", None)
    if explicit:
        path = Path(explicit)
        return path.resolve() if path.is_absolute() else (root / path).resolve()
    # Reuse the legacy CLI's discovery/validation rules so an explicit
    # `--config` and all three documented config locations behave identically.
    from ui_ref_cli import load_config

    cfg = load_config(root, args, required=bool(getattr(args, "config", None)))
    configured = cfg.get("design_workspace", DESIGN_WORKSPACE)
    path = Path(str(configured))
    if path.is_absolute():
        raise SystemExit("Configured design_workspace must be relative to the project root; use --design-root for an explicit absolute path.")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise SystemExit(f"Configured design_workspace must stay inside the project root: {configured}")
    return resolved


def _resolve_design_path(design_root: Path, value: str, field: str) -> Path:
    """Resolve a contract-owned path without allowing it to escape the design workspace."""
    candidate = Path(str(value))
    if candidate.is_absolute():
        raise ValueError(f"{field} must be relative to the design workspace: {value}")
    resolved = (design_root / candidate).resolve()
    if not resolved.is_relative_to(design_root.resolve()):
        raise ValueError(f"{field} must stay inside the design workspace: {value}")
    return resolved


def _ensure_workspace(design_root: Path) -> dict[str, Any]:
    project_path = design_root / "project.json"
    if not project_path.exists():
        raise SystemExit(f"Design workspace not found: {design_root}. Run `ui-ref spec init` first.")
    project = _read_json(project_path)
    if not isinstance(project, dict):
        raise SystemExit(f"Invalid project contract: {project_path}")
    return project


def _schema_document() -> dict[str, Any]:
    """Return the public contract shape.

    The bundled validator additionally performs referential and release-gate
    checks which JSON Schema cannot express cleanly.
    """
    rect = {
        "type": "object",
        "required": ["x", "y", "width", "height"],
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "width": {"type": "number", "exclusiveMinimum": 0},
            "height": {"type": "number", "exclusiveMinimum": 0},
            "anchor": {"type": "string"},
        },
        "additionalProperties": True,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/SillyToolValley/Game-UI-Reference-Cli/schemas/game-ui-design-contract-v1.schema.json",
        "title": "Game UX/UI Design Contract",
        "description": "Portable, evidence-linked game UX/UI contracts authored by humans and AI agents.",
        "oneOf": [
            {"$ref": "#/$defs/screen"},
            {"$ref": "#/$defs/component"},
        ],
        "$defs": {
            "status": {"enum": list(STATUS_ORDER)},
            "provenance": {
                "type": "object",
                "required": ["created_by", "created_at"],
                "properties": {
                    "created_by": {"type": "string", "minLength": 1},
                    "created_at": {"type": "string", "minLength": 1},
                    "source_files": {"type": "array", "items": {"type": "string"}},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                },
            },
            "element": {
                "type": "object",
                "required": ["id", "name", "type", "rect", "states", "accessibility"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]*$"},
                    "name": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "minLength": 1},
                    "rect": rect,
                    "states": {"type": "object"},
                    "reference_ids": {"type": "array", "items": {"type": "string"}},
                    "data_bindings": {"type": "array", "items": {"type": "object"}},
                    "interactions": {"type": "array", "items": {"type": "object"}},
                    "acceptance": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
                    "accessibility": {"type": "object"},
                },
            },
            "screen": {
                "type": "object",
                "required": ["schema_version", "kind", "id", "name", "status", "purpose", "player_goal", "viewport", "coordinate_space", "elements", "provenance"],
                "properties": {
                    "schema_version": {"const": DESIGN_SCHEMA_VERSION},
                    "kind": {"const": "screen"},
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
                    "name": {"type": "string", "minLength": 1},
                    "status": {"$ref": "#/$defs/status"},
                    "purpose": {"type": "string"},
                    "player_goal": {"type": "string"},
                    "viewport": {"type": "object", "required": ["width", "height"]},
                    "coordinate_space": {"const": "viewport_absolute"},
                    "elements": {"type": "array", "items": {"$ref": "#/$defs/element"}},
                    "provenance": {"$ref": "#/$defs/provenance"},
                },
            },
            "component": {
                "type": "object",
                "required": ["schema_version", "kind", "id", "name", "status", "purpose", "states", "provenance"],
                "properties": {
                    "schema_version": {"const": DESIGN_SCHEMA_VERSION},
                    "kind": {"const": "component"},
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
                    "name": {"type": "string", "minLength": 1},
                    "status": {"$ref": "#/$defs/status"},
                    "purpose": {"type": "string"},
                    "states": {"type": "object"},
                    "acceptance": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
                    "provenance": {"$ref": "#/$defs/provenance"},
                },
            },
        },
    }


def _default_tokens() -> dict[str, Any]:
    return {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "kind": "tokens",
        "status": "draft",
        "color": {
            "surface.canvas": {"value": "#11151D", "source": "assumption"},
            "surface.panel": {"value": "#1C2430", "source": "assumption"},
            "text.primary": {"value": "#F5F7FA", "source": "assumption"},
            "text.muted": {"value": "#A9B4C2", "source": "assumption"},
            "accent.primary": {"value": "#55D6BE", "source": "assumption"},
            "feedback.danger": {"value": "#FF5D73", "source": "assumption"},
        },
        "spacing": {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32},
        "typography": {
            "body": {"family": "project-default", "size": 18, "weight": 400},
            "label": {"family": "project-default", "size": 16, "weight": 600},
            "title": {"family": "project-default", "size": 32, "weight": 700},
        },
        "motion": {
            "instant_ms": 100,
            "fast_ms": 180,
            "standard_ms": 280,
            "reduced_motion": "replace spatial motion with opacity or instant state change",
        },
        "input": {"minimum_pointer_target_px": 44, "focus_ring_px": 3},
        "notes": ["Starter values are assumptions. Review and approve before production use."],
    }


def _empty_collections(kind: str, key: str) -> dict[str, Any]:
    return {"schema_version": DESIGN_SCHEMA_VERSION, "kind": kind, key: []}


def _screen_template(screen_id: str, name: str, width: int, height: int, author: str) -> dict[str, Any]:
    return {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "kind": "screen",
        "id": screen_id,
        "name": name,
        "status": "draft",
        "revision": 1,
        "purpose": "",
        "player_goal": "",
        "viewport": {
            "width": width,
            "height": height,
            "safe_area": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        },
        "coordinate_space": "viewport_absolute",
        "entry_conditions": [],
        "exit_paths": [],
        "reference_ids": [],
        "elements": [],
        "edge_cases": [],
        "open_questions": [],
        "wireframe": f"wireframes/{screen_id}.uiwire",
        "provenance": {
            "created_by": author,
            "created_at": _now(),
            "source_files": [],
            "assumptions": [],
        },
        "review_history": [],
    }


def _component_template(component_id: str, name: str, author: str) -> dict[str, Any]:
    return {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "kind": "component",
        "id": component_id,
        "name": name,
        "status": "draft",
        "revision": 1,
        "purpose": "",
        "anatomy": [],
        "variants": [],
        "states": {
            "default": {"applicable": True, "description": "Define the resting presentation."},
            "hover": {"applicable": False, "reason": "Decide based on target input devices."},
            "focused": {"applicable": True, "description": "Define a non-color focus cue."},
            "pressed": {"applicable": True, "description": "Define immediate activation feedback."},
            "selected": {"applicable": False, "reason": "Mark applicable for persistent choices."},
            "disabled": {"applicable": True, "description": "Show why activation is unavailable."},
            "locked": {"applicable": False, "reason": "Mark applicable for progression locks."},
            "loading_entry": {"applicable": False, "reason": "Separate entry transition from data loading."},
            "loading_data": {"applicable": False, "reason": "Mark applicable for asynchronous data."},
            "empty": {"applicable": False, "reason": "Define if the component can have no content."},
            "error": {"applicable": False, "reason": "Define if data/action failure is possible."},
        },
        "tokens": [],
        "inputs": [],
        "accessibility": {"role": "", "label_template": "", "non_color_cues": []},
        "acceptance": [],
        "reference_ids": [],
        "provenance": {
            "created_by": author,
            "created_at": _now(),
            "source_files": [],
            "assumptions": [],
        },
        "review_history": [],
    }


def _import_reference_manifest(project_root: Path, design_root: Path) -> int:
    candidates = (
        project_root / "ui_research" / "manifests" / "local_ui_refs_manifest.json",
        project_root / "docs" / "ui_research" / "manifests" / "local_ui_refs_manifest.json",
    )
    manifest_path = next((path for path in candidates if path.exists()), None)
    if not manifest_path:
        return 0
    manifest = _read_json(manifest_path)
    source_urls: dict[str, str] = {}
    manifests_root = manifest_path.parent
    for collected_path in sorted(manifests_root.glob("collected_pages_*.json")):
        try:
            collected = _read_json(collected_path)
        except (OSError, json.JSONDecodeError):
            continue
        for record in collected.get("records", []) if isinstance(collected, dict) else []:
            if not isinstance(record, dict):
                continue
            for asset in record.get("downloaded_assets", []) or []:
                if isinstance(asset, dict) and asset.get("local_path") and asset.get("source_url"):
                    source_urls[str(asset["local_path"]).replace("\\", "/")] = str(asset["source_url"])
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(manifest.get("items", []), start=1):
        item_path = str(item.get("path", "")).replace("\\", "/")
        absolute = (project_root / item_path).resolve() if item_path else None
        path_safe = bool(absolute and absolute.is_relative_to(project_root.resolve()))
        content_hash = _sha256(absolute) if path_safe and absolute and absolute.exists() and absolute.is_file() else ""
        sync_state = "present" if content_hash else "missing" if path_safe else "invalid_path"
        # Content hashes alone are not identities: two distinct screenshots can
        # legitimately contain the same bytes.  Include the manifest URI so IDs
        # remain unique while exact URI matching preserves annotations on sync.
        identity_suffix = hashlib.sha256(item_path.encode("utf-8")).hexdigest()[:6]
        stable_suffix = f"{content_hash[:8]}-{identity_suffix}" if content_hash else f"{index:08d}-{identity_suffix}"
        sources.append(
            {
                "id": f"ref-{_slug(str(item.get('filename', 'local')), 'local')}-{stable_suffix}",
                "source_type": "local_reference",
                "uri": item_path,
                "source_url": source_urls.get(item_path, ""),
                "title": item.get("filename", ""),
                "collection": item.get("collection", ""),
                "category": item.get("category", ""),
                "tags": item.get("tags", []),
                "rights": "verify-before-redistribution",
                "captured_at": manifest.get("generated_at", ""),
                "sync_state": sync_state,
                "evidence_notes": [],
                "sha256": content_hash,
                "verification": "verified-file" if content_hash else "missing",
                "manifest_link": {"manifest_path": _rel(project_root, manifest_path), "item_path": item_path},
            }
        )
    refs_path = design_root / "references.json"
    existing_sources: list[dict[str, Any]] = []
    if refs_path.exists():
        try:
            existing_doc = _read_json(refs_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Cannot synchronize references because the existing catalog is invalid: {exc}") from exc
        if not isinstance(existing_doc, dict) or not isinstance(existing_doc.get("sources"), list):
            raise SystemExit("Cannot synchronize references because references.json must contain a sources array.")
        if any(not isinstance(item, dict) for item in existing_doc["sources"]):
            raise SystemExit("Cannot synchronize references because every references.json source must be an object.")
        existing_sources = list(existing_doc["sources"])

    by_uri: dict[str, list[int]] = {}
    by_hash: dict[str, list[int]] = {}
    for previous_index, previous in enumerate(existing_sources):
        if previous.get("uri"):
            by_uri.setdefault(str(previous["uri"]), []).append(previous_index)
        if previous.get("sha256"):
            by_hash.setdefault(str(previous["sha256"]), []).append(previous_index)
    merged: list[dict[str, Any]] = []
    matched_indexes: set[int] = set()
    for source in sources:
        candidates = [index for index in by_uri.get(str(source.get("uri", "")), []) if index not in matched_indexes]
        previous_index = candidates[0] if len(candidates) == 1 else None
        if previous_index is None and source.get("sha256"):
            # Hash fallback is rename detection only.  Ambiguous duplicate
            # content is never allowed to collapse two catalog identities.
            hash_candidates = [index for index in by_hash.get(str(source["sha256"]), []) if index not in matched_indexes]
            if len(hash_candidates) == 1:
                previous_index = hash_candidates[0]
        previous = existing_sources[previous_index] if previous_index is not None else None
        if previous:
            combined = {**source, **previous, "sha256": source.get("sha256"), "uri": source.get("uri"), "sync_state": source.get("sync_state", "present")}
            if not combined.get("source_url") and source.get("source_url"):
                combined["source_url"] = source["source_url"]
            merged.append(combined)
            matched_indexes.add(previous_index)
        else:
            source["sync_state"] = source.get("sync_state", "present")
            merged.append(source)
    for previous_index, previous in enumerate(existing_sources):
        if previous_index not in matched_indexes:
            merged.append({**previous, "sync_state": "missing"})
    refs = _empty_collections("references", "sources")
    refs["sources"] = merged
    refs["imported_from"] = _rel(project_root, manifest_path)
    _write_json(refs_path, refs)
    return len(sources)


def command_design_init(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    design_root = _design_root(args)
    project_path = design_root / "project.json"
    if project_path.exists() and not args.force:
        raise SystemExit(f"Design workspace already exists: {design_root}. Use --force to refresh only starter metadata.")

    project_id = _portable_id(args.project_id or args.project_name or project_root.name, "game-ui")
    project = {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "kind": "project",
        "project": {
            "id": project_id,
            "name": args.project_name or project_root.name,
            "status": "draft",
            "platforms": args.platform or ["pc"],
            "input_devices": args.input_device or ["keyboard_mouse", "gamepad"],
            "aspect_ratios": args.aspect_ratio or ["16:9"],
            "default_locale": args.locale,
            "intent": "Evidence-backed, implementation-ready game UX/UI contracts.",
        },
        "paths": {
            "tokens": "tokens.json",
            "flows": "flows.json",
            "references": "references.json",
            "decisions": "decisions.json",
            "approvals": "approvals.json",
            "screens": "screens",
            "components": "components",
            "wireframes": "wireframes",
            "build": "build",
        },
        "quality_gates": {
            "approved_requires_references_or_exception": True,
            "approved_requires_acceptance": True,
            "approved_requires_accessibility": True,
            "approved_requires_input_parity": True,
            "approved_requires_no_open_questions": False,
        },
        "created_at": _now(),
        "updated_at": _now(),
    }
    if project_path.exists() and args.force:
        try:
            existing_project = _read_json(project_path)
        except (OSError, json.JSONDecodeError):
            existing_project = {}
        if isinstance(existing_project, dict):
            existing_meta = existing_project.get("project", {}) if isinstance(existing_project.get("project"), dict) else {}
            project = {
                **existing_project,
                "schema_version": DESIGN_SCHEMA_VERSION,
                "kind": "project",
                "project": {**project["project"], **existing_meta},
                "paths": {**project["paths"], **(existing_project.get("paths", {}) if isinstance(existing_project.get("paths"), dict) else {})},
                "quality_gates": {**project["quality_gates"], **(existing_project.get("quality_gates", {}) if isinstance(existing_project.get("quality_gates"), dict) else {})},
                "created_at": existing_project.get("created_at", project["created_at"]),
                "updated_at": _now(),
            }
            if args.project_name:
                project["project"]["name"] = args.project_name
    for folder in ("screens", "components", "wireframes", "analysis", "build", "schemas"):
        (design_root / folder).mkdir(parents=True, exist_ok=True)
    _write_json(project_path, project)
    if not (design_root / "tokens.json").exists():
        _write_json(design_root / "tokens.json", _default_tokens())
    if not (design_root / "flows.json").exists():
        _write_json(design_root / "flows.json", _empty_collections("flows", "flows"))
    if not (design_root / "references.json").exists():
        _write_json(design_root / "references.json", _empty_collections("references", "sources"))
    if not (design_root / "decisions.json").exists():
        _write_json(design_root / "decisions.json", _empty_collections("decisions", "decisions"))
    if not (design_root / "approvals.json").exists():
        _write_json(design_root / "approvals.json", _empty_collections("approvals", "approvals"))
    _write_json(design_root / "schemas" / "game-ui-design-contract-v1.schema.json", _schema_document())

    imported = 0
    if not args.no_import_references:
        imported = _import_reference_manifest(project_root, design_root)
    print(f"Initialized game UX/UI design workspace: {design_root}")
    print(f"Contract schema: {design_root / 'schemas' / 'game-ui-design-contract-v1.schema.json'}")
    print(f"Imported local reference evidence: {imported}")
    return 0


def command_design_new_screen(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    screen_id = _portable_id(args.screen_id or args.name, "screen")
    output = design_root / "screens" / f"{screen_id}.json"
    if output.exists():
        if not args.force:
            raise SystemExit(f"Screen already exists: {output}")
        existing = _read_json(output)
        if not isinstance(existing, dict) or existing.get("status") != "draft" or existing.get("review_history"):
            raise SystemExit("--force can replace only an unreviewed draft screen; preserve reviewed/approved history through the lifecycle workflow.")
    screen = _screen_template(screen_id, args.name or screen_id.replace("-", " ").title(), args.width, args.height, args.author)
    _write_json(output, screen)
    if args.wireframe:
        _write_text(design_root / screen["wireframe"], _wireframe_from_screen(screen))
    print(f"Created screen contract: {output}")
    return 0


def command_design_new_component(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    component_id = _portable_id(args.component_id or args.name, "component")
    output = design_root / "components" / f"{component_id}.json"
    if output.exists():
        if not args.force:
            raise SystemExit(f"Component already exists: {output}")
        existing = _read_json(output)
        if not isinstance(existing, dict) or existing.get("status") != "draft" or existing.get("review_history"):
            raise SystemExit("--force can replace only an unreviewed draft component; preserve reviewed/approved history through the lifecycle workflow.")
    _write_json(output, _component_template(component_id, args.name or component_id.replace("-", " ").title(), args.author))
    print(f"Created component contract: {output}")
    return 0


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "path": self.path, "message": self.message}


def _issue(issues: list[ValidationIssue], severity: str, code: str, path: str, message: str) -> None:
    issues.append(ValidationIssue(severity, code, path, message))


def _json_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.glob("*.json") if path.is_file()) if folder.exists() else []


def _dependency_snapshot(design_root: Path, contract: dict[str, Any]) -> dict[str, str]:
    paths = [design_root / "tokens.json", design_root / "flows.json", design_root / "references.json"]
    component_ids: set[str] = set()
    for element in contract.get("elements", []) if isinstance(contract.get("elements"), list) else []:
        if isinstance(element, dict) and isinstance(element.get("component_id"), str):
            component_ids.add(element["component_id"])
    paths.extend(design_root / "components" / f"{_portable_id(value, 'component')}.json" for value in sorted(component_ids))
    return {_rel(design_root, path): _sha256(path) if path.is_file() else "<missing>" for path in paths}


def _validate_approval(
    design_root: Path,
    path: Path,
    contract: dict[str, Any],
    approvals: list[dict[str, Any]],
    issues: list[ValidationIssue],
) -> None:
    if contract.get("status") != "approved":
        return
    matches = [
        item for item in approvals
        if isinstance(item, dict)
        and item.get("artifact_kind") == contract.get("kind")
        and item.get("artifact_id") == contract.get("id")
        and item.get("status") == "approved"
        and item.get("revision") == contract.get("revision")
    ]
    if not matches:
        _issue(issues, "error", "approval.missing", str(path), "Approved status has no matching human approval ledger entry.")
        return
    approval = matches[-1]
    if approval.get("actor_type") != "human" or not approval.get("actor"):
        _issue(issues, "error", "approval.not_human", str(path), "Final approval must identify a human actor.")
    current_hash = _sha256(path)
    if approval.get("content_sha256") != current_hash:
        _issue(issues, "error", "approval.stale_content", str(path), "Contract changed after approval; return it to draft and review again.")
    current_dependencies = _dependency_snapshot(design_root, contract)
    if approval.get("dependency_sha256") != current_dependencies:
        _issue(issues, "error", "approval.stale_dependency", str(path), "A token, flow, reference, or component dependency changed after approval.")


def _load_contracts(folder: Path, expected_kind: str, issues: list[ValidationIssue]) -> list[tuple[Path, dict[str, Any]]]:
    contracts: list[tuple[Path, dict[str, Any]]] = []
    for path in _json_files(folder):
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            _issue(issues, "error", "json.invalid", str(path), str(exc))
            continue
        if not isinstance(data, dict):
            _issue(issues, "error", "contract.not_object", str(path), "Contract root must be an object.")
            continue
        if data.get("kind") != expected_kind:
            _issue(issues, "error", "contract.kind", str(path), f"Expected kind={expected_kind!r}.")
        contracts.append((path, data))
    return contracts


def _reference_actual_state(source: dict[str, Any], project_root: Path) -> str | None:
    """Re-check local evidence instead of trusting its cached catalog state."""
    source_type = source.get("source_type")
    if source_type not in REFERENCE_SOURCE_TYPES:
        return "unsupported_type"
    raw_uri = source.get("uri")
    if not isinstance(raw_uri, str) or not raw_uri.strip():
        return "missing"
    if urlparse(raw_uri).scheme.lower() in {"http", "https", "data"}:
        return "invalid_path"
    raw_path = Path(raw_uri)
    resolved = raw_path.resolve() if raw_path.is_absolute() else (project_root / raw_path).resolve()
    if source_type == "local_reference" and not resolved.is_relative_to(project_root.resolve()):
        return "invalid_path"
    if not resolved.is_file():
        return "missing"
    expected_hash = source.get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        return "hash_missing"
    return "present" if _sha256(resolved) == expected_hash else "hash_mismatch"


def _validate_rect(rect: Any, viewport: dict[str, Any], base: str, issues: list[ValidationIssue], strict: bool) -> None:
    if not isinstance(rect, dict):
        _issue(issues, "error", "rect.missing", base, "Element requires a rect object.")
        return
    values: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        value = rect.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            _issue(issues, "error", "rect.number", f"{base}.{key}", "Must be a number.")
            return
        values[key] = float(value)
    if values["width"] <= 0 or values["height"] <= 0:
        _issue(issues, "error", "rect.positive", base, "Width and height must be positive.")
    width = viewport.get("width")
    height = viewport.get("height")
    if isinstance(width, (int, float)) and not isinstance(width, bool) and isinstance(height, (int, float)) and not isinstance(height, bool) and math.isfinite(float(width)) and math.isfinite(float(height)):
        outside = values["x"] < 0 or values["y"] < 0 or values["x"] + values["width"] > width or values["y"] + values["height"] > height
        if outside:
            _issue(issues, "error" if strict else "warning", "rect.outside_viewport", base, "Element extends outside the declared viewport.")


def _validate_reference_ids(
    values: Any,
    known_refs: set[str],
    base: str,
    issues: list[ValidationIssue],
    *,
    unavailable_refs: set[str] | None = None,
    require_available: bool = False,
) -> None:
    if values is None:
        return
    if not isinstance(values, list):
        _issue(issues, "error", "references.not_array", base, "reference_ids must be an array.")
        return
    for index, ref_id in enumerate(values):
        if not isinstance(ref_id, str) or not ref_id:
            _issue(issues, "error", "references.invalid_id", f"{base}[{index}]", "Reference ID must be a non-empty string.")
        elif ref_id not in known_refs:
            _issue(issues, "error", "references.unknown", f"{base}[{index}]", f"Unknown reference ID: {ref_id}")
        elif require_available and ref_id in (unavailable_refs or set()):
            _issue(issues, "error", "evidence.unavailable", f"{base}[{index}]", f"Evidence is missing or invalid: {ref_id}")


def _validate_acceptance(values: Any, base: str, issues: list[ValidationIssue], strict: bool) -> None:
    if not isinstance(values, list):
        _issue(issues, "error", "acceptance.not_array", base, "Acceptance criteria must be an array.")
        return
    if strict and not values:
        _issue(issues, "error", "acceptance.missing", base, "Reviewed/approved interaction needs acceptance criteria.")
        return
    for index, criterion in enumerate(values):
        item_base = f"{base}[{index}]"
        if isinstance(criterion, dict):
            if not all(str(criterion.get(key, "")).strip() for key in ("given", "when", "then")):
                _issue(issues, "error" if strict else "warning", "acceptance.gwt", item_base, "Use non-empty given, when, and then fields.")
        elif isinstance(criterion, str):
            if not re.search(r"\bgiven\b.+\bwhen\b.+\bthen\b", criterion, flags=re.IGNORECASE | re.DOTALL):
                _issue(issues, "error" if strict else "warning", "acceptance.gwt", item_base, "Use an explicit Given/When/Then criterion.")
        else:
            _issue(issues, "error", "acceptance.invalid", item_base, "Criterion must be a string or an object.")


def _screen_scenario_names(screen: dict[str, Any]) -> set[str]:
    # Screen scenarios are authored, reviewable variants. Component-level
    # interaction states (hover/focused/etc.) are deliberately excluded so a
    # transition can never validate against a state the prototype cannot open.
    scenarios = {"default", "loading", "empty", "error", "disabled"}
    for element in screen.get("elements", []) if isinstance(screen.get("elements"), list) else []:
        if not isinstance(element, dict):
            continue
        states = element.get("states")
        if isinstance(states, dict):
            scenarios.update(
                str(value)
                for value in states
                if isinstance(value, str) and value and value not in REQUIRED_INTERACTIVE_STATES
            )
    return scenarios


def _validate_screen(
    path: Path,
    screen: dict[str, Any],
    known_refs: set[str],
    unavailable_refs: set[str],
    known_screens: set[str],
    screen_scenarios: dict[str, set[str]],
    component_statuses: dict[str, str],
    required_inputs: set[str],
    quality_gates: dict[str, bool],
    issues: list[ValidationIssue],
    strict_all: bool,
) -> None:
    rel = str(path)
    status = screen.get("status")
    strict = strict_all or status in {"reviewed", "approved"}

    def gate(name: str, default: bool = True) -> bool:
        return strict and quality_gates.get(name, default) is True
    for key in ("schema_version", "kind", "id", "name", "status", "revision", "purpose", "viewport", "coordinate_space", "elements", "provenance"):
        if key not in screen:
            _issue(issues, "error", "screen.required", f"{rel}:{key}", "Required field is missing.")
    if screen.get("schema_version") != DESIGN_SCHEMA_VERSION:
        _issue(issues, "error", "schema.version", rel, f"Expected schema_version {DESIGN_SCHEMA_VERSION}.")
    screen_id = screen.get("id")
    if not isinstance(screen_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", screen_id):
        _issue(issues, "error", "screen.id", f"{rel}:id", "Use a portable lowercase ID beginning with a letter (a-z, 0-9, hyphen).")
    elif path.stem != screen_id:
        _issue(issues, "error", "screen.filename", rel, f"Filename must match screen ID: {screen_id}.json")
    default_scenario = screen.get("default_scenario")
    if default_scenario is not None:
        if not isinstance(default_scenario, str) or not default_scenario:
            _issue(issues, "error", "scenario.default", f"{rel}:default_scenario", "default_scenario must be a non-empty string.")
        elif default_scenario not in screen_scenarios.get(str(screen_id), {"default"}):
            _issue(issues, "error", "scenario.unknown_default", f"{rel}:default_scenario", f"Unknown scenario on {screen_id}: {default_scenario}")
    if not str(screen.get("name", "")).strip():
        _issue(issues, "error", "screen.name", f"{rel}:name", "Screen needs a name.")
    revision = screen.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        _issue(issues, "error", "revision.invalid", f"{rel}:revision", "Revision must be a positive integer.")
    provenance = screen.get("provenance")
    if not isinstance(provenance, dict) or not str(provenance.get("created_by", "")).strip() or not str(provenance.get("created_at", "")).strip():
        _issue(issues, "error", "provenance.invalid", f"{rel}:provenance", "Provenance needs non-empty created_by and created_at fields.")
    if screen.get("coordinate_space") != "viewport_absolute":
        _issue(issues, "error", "screen.coordinate_space", f"{rel}:coordinate_space", "v1 screen rects must use viewport_absolute coordinates.")
    if status not in STATUS_ORDER:
        _issue(issues, "error", "status.invalid", f"{rel}:status", f"Expected one of {', '.join(STATUS_ORDER)}.")
    if strict and not str(screen.get("purpose", "")).strip():
        _issue(issues, "error", "screen.purpose", f"{rel}:purpose", "Reviewed/approved output needs a concrete purpose.")
    if strict and not str(screen.get("player_goal", "")).strip():
        _issue(issues, "error", "screen.player_goal", f"{rel}:player_goal", "Reviewed/approved output needs a concrete player goal.")
    if strict and not screen.get("entry_conditions") and not screen.get("entry_exception"):
        _issue(issues, "error", "screen.entry", f"{rel}:entry_conditions", "Define entry conditions or an explicit entry_exception.")
    if strict and not screen.get("exit_paths") and not screen.get("exit_exception"):
        _issue(issues, "error", "screen.exit", f"{rel}:exit_paths", "Define exit paths or an explicit exit_exception.")
    if strict and not screen.get("edge_cases") and not screen.get("edge_case_exception"):
        _issue(issues, "error", "screen.edge_cases", f"{rel}:edge_cases", "Define edge cases/recovery or an explicit exception.")
    viewport = screen.get("viewport") if isinstance(screen.get("viewport"), dict) else {}
    viewport_width = viewport.get("width")
    viewport_height = viewport.get("height")
    if (
        isinstance(viewport_width, bool) or not isinstance(viewport_width, (int, float)) or not math.isfinite(float(viewport_width))
        or isinstance(viewport_height, bool) or not isinstance(viewport_height, (int, float)) or not math.isfinite(float(viewport_height))
        or viewport_width <= 0 or viewport_height <= 0 or viewport_width > 16384 or viewport_height > 16384
    ):
        _issue(issues, "error", "viewport.invalid", f"{rel}:viewport", "Viewport dimensions must be finite numbers between 1 and 16384.")
    safe_area = viewport.get("safe_area", {})
    if not isinstance(safe_area, dict):
        _issue(issues, "error", "viewport.safe_area", f"{rel}:viewport.safe_area", "Safe area must be an object.")
    else:
        safe_values: dict[str, float] = {}
        for edge in ("left", "top", "right", "bottom"):
            value = safe_area.get(edge, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
                _issue(issues, "error", "viewport.safe_area", f"{rel}:viewport.safe_area.{edge}", "Safe-area inset must be a finite non-negative number.")
            else:
                safe_values[edge] = float(value)
        if len(safe_values) == 4 and isinstance(viewport_width, (int, float)) and isinstance(viewport_height, (int, float)):
            if safe_values["left"] + safe_values["right"] >= float(viewport_width) or safe_values["top"] + safe_values["bottom"] >= float(viewport_height):
                _issue(issues, "error", "viewport.safe_area", f"{rel}:viewport.safe_area", "Safe-area insets leave no usable viewport.")
    _validate_reference_ids(
        screen.get("reference_ids", []), known_refs, f"{rel}:reference_ids", issues,
        unavailable_refs=unavailable_refs, require_available=strict,
    )
    if gate("approved_requires_references_or_exception") and not screen.get("reference_ids") and not screen.get("evidence_exception"):
        _issue(issues, "error", "evidence.missing", rel, "Approved screen needs reference evidence or an explicit evidence_exception.")
    wireframe_value = screen.get("wireframe")
    if strict and not wireframe_value:
        _issue(issues, "error", "wireframe.missing", f"{rel}:wireframe", "Reviewed/approved screen needs a .uiwire source.")
    elif wireframe_value:
        try:
            wireframe_path = _resolve_design_path(path.parent.parent, str(wireframe_value), f"screen {screen_id} wireframe")
            if wireframe_path.suffix.lower() != ".uiwire":
                _issue(issues, "error", "wireframe.extension", f"{rel}:wireframe", "Wireframe source must use the .uiwire extension.")
            elif not wireframe_path.is_file():
                _issue(issues, "error" if strict else "warning", "wireframe.missing", f"{rel}:wireframe", f"Wireframe source not found: {wireframe_value}")
        except ValueError as exc:
            _issue(issues, "error", "wireframe.path", f"{rel}:wireframe", str(exc))

    elements = screen.get("elements", [])
    if not isinstance(elements, list):
        _issue(issues, "error", "elements.not_array", f"{rel}:elements", "Elements must be an array.")
        return
    if strict and not elements:
        _issue(issues, "error", "elements.empty", f"{rel}:elements", "Reviewed/approved screen needs at least one element.")
    seen: set[str] = set()
    element_map: dict[str, dict[str, Any]] = {}
    focus_orders: set[int] = set()
    for index, element in enumerate(elements):
        base = f"{rel}:elements[{index}]"
        if not isinstance(element, dict):
            _issue(issues, "error", "element.not_object", base, "Element must be an object.")
            continue
        element_id = element.get("id")
        if not isinstance(element_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", element_id):
            _issue(issues, "error", "element.id", f"{base}.id", "Use an immutable ID beginning with a letter.")
        elif element_id in seen:
            _issue(issues, "error", "element.duplicate", f"{base}.id", f"Duplicate element ID: {element_id}")
        else:
            seen.add(element_id)
            element_map[element_id] = element
        if not str(element.get("name", "")).strip():
            _issue(issues, "error", "element.name", f"{base}.name", "Element needs a name.")
        if strict and not str(element.get("ux_intent", "")).strip():
            _issue(issues, "error", "element.ux_intent", f"{base}.ux_intent", "Reviewed/approved element needs a plain-language UX intent.")
        _validate_rect(element.get("rect"), viewport, f"{base}.rect", issues, strict)
        rect_overrides = element.get("rect_overrides")
        if rect_overrides is not None:
            if not isinstance(rect_overrides, dict):
                _issue(issues, "error", "rect_overrides.not_object", f"{base}.rect_overrides", "Scenario rect overrides must be an object.")
            else:
                for scenario_name, scenario_rect in rect_overrides.items():
                    if not isinstance(scenario_name, str) or not scenario_name:
                        _issue(issues, "error", "rect_overrides.scenario", f"{base}.rect_overrides", "Scenario names must be non-empty strings.")
                        continue
                    merged_rect = dict(element.get("rect", {})) if isinstance(element.get("rect"), dict) else {}
                    if isinstance(scenario_rect, dict):
                        merged_rect.update(scenario_rect)
                    _validate_rect(merged_rect, viewport, f"{base}.rect_overrides.{scenario_name}", issues, strict)
        _validate_reference_ids(
            element.get("reference_ids", []), known_refs, f"{base}.reference_ids", issues,
            unavailable_refs=unavailable_refs, require_available=strict,
        )
        component_id = element.get("component_id")
        if component_id is not None:
            if not isinstance(component_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", component_id):
                _issue(issues, "error", "component.reference_id", f"{base}.component_id", "component_id must be a portable canonical component ID.")
            elif component_id not in component_statuses:
                _issue(issues, "error", "component.unknown", f"{base}.component_id", f"Unknown component ID: {component_id}")
            elif status == "approved" and component_statuses[component_id] != "approved":
                _issue(issues, "error", "component.not_approved", f"{base}.component_id", f"Approved screens require an approved component: {component_id}")

        element_type = element.get("type")
        if element_type not in ELEMENT_TYPES:
            _issue(issues, "error", "element.type", f"{base}.type", f"Expected one of: {', '.join(sorted(ELEMENT_TYPES))}.")
        z_index = element.get("z_index")
        if isinstance(z_index, bool) or (z_index is not None and (not isinstance(z_index, int) or not -1000 <= z_index <= 1000)):
            _issue(issues, "error", "element.z_index", f"{base}.z_index", "z_index must be an integer between -1000 and 1000.")
        control_contracts = element.get("control_contracts")
        if control_contracts is not None:
            if not isinstance(control_contracts, list) or not control_contracts:
                _issue(issues, "error", "control_contracts.not_array", f"{base}.control_contracts", "control_contracts must be a non-empty array when provided.")
            else:
                control_ids: set[str] = set()
                for control_index, control in enumerate(control_contracts):
                    control_base = f"{base}.control_contracts[{control_index}]"
                    if not isinstance(control, dict):
                        _issue(issues, "error", "control_contracts.not_object", control_base, "Each control contract must be an object.")
                        continue
                    control_id = control.get("id")
                    if not isinstance(control_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", control_id):
                        _issue(issues, "error", "control_contracts.id", f"{control_base}.id", "Use a lowercase control ID beginning with a letter.")
                    elif control_id in control_ids:
                        _issue(issues, "error", "control_contracts.duplicate", f"{control_base}.id", f"Duplicate nested control ID: {control_id}")
                    control_ids.add(str(control_id))
                    if not isinstance(control.get("type"), str) or not str(control.get("type", "")).strip():
                        _issue(issues, "error", "control_contracts.type", f"{control_base}.type", "Nested control contract needs a type.")
        element_states = element.get("states")
        if not isinstance(element_states, dict):
            _issue(issues, "error", "states.missing", f"{base}.states", "Element states must be an object.")
        elif strict and ("default" not in element_states or element_states.get("default") in (None, "", {}, [])):
            _issue(issues, "error", "states.default", f"{base}.states.default", "Define the default state.")
        element_accessibility = element.get("accessibility")
        if not isinstance(element_accessibility, dict):
            _issue(issues, "error", "accessibility.missing", f"{base}.accessibility", "Element accessibility metadata must be an object.")
        elif gate("approved_requires_accessibility") and not element_accessibility.get("label") and not element_accessibility.get("accessibility_exception"):
            _issue(issues, "error", "accessibility.label", f"{base}.accessibility", "Define an accessible label or an explicit exception.")
        interactions = element.get("interactions", [])
        interactive = element_type in INTERACTIVE_TYPES or bool(interactions)
        covered_inputs: set[str] = set()
        if interactions is not None and not isinstance(interactions, list):
            _issue(issues, "error", "interactions.not_array", f"{base}.interactions", "Interactions must be an array.")
            interactions = []
        for action_index, interaction in enumerate(interactions or []):
            action_base = f"{base}.interactions[{action_index}]"
            if not isinstance(interaction, dict):
                _issue(issues, "error", "interaction.not_object", action_base, "Interaction must be an object.")
                continue
            if not interaction.get("input") or not interaction.get("action"):
                _issue(issues, "error" if strict else "warning", "interaction.incomplete", action_base, "Interaction needs input and action.")
            devices = interaction.get("devices", [])
            if not isinstance(devices, list) or any(not isinstance(value, str) or not value for value in devices):
                _issue(issues, "error", "interaction.devices", f"{action_base}.devices", "devices must be an array of non-empty input-device IDs.")
            else:
                covered_inputs.update(devices)
            target = interaction.get("target_screen")
            if target and target not in known_screens:
                _issue(issues, "error", "interaction.unknown_target", action_base, f"Unknown target screen: {target}")
            target_scenario = interaction.get("target_scenario")
            if target_scenario is not None:
                if not isinstance(target_scenario, str) or not target_scenario:
                    _issue(issues, "error", "interaction.target_scenario", f"{action_base}.target_scenario", "target_scenario must be a non-empty string.")
                elif not target:
                    _issue(issues, "error", "interaction.target_scenario", f"{action_base}.target_scenario", "target_scenario requires target_screen.")
                elif target_scenario == "@base":
                    if target != screen_id:
                        _issue(issues, "error", "interaction.target_scenario", f"{action_base}.target_scenario", "@base is valid only for a same-screen overlay transition.")
                elif target in known_screens and target_scenario not in screen_scenarios.get(str(target), {"default"}):
                    _issue(issues, "error", "interaction.unknown_target_scenario", f"{action_base}.target_scenario", f"Unknown scenario on {target}: {target_scenario}")
            target_scenario_by_mode = interaction.get("target_scenario_by_mode")
            if target_scenario_by_mode is not None:
                if not isinstance(target_scenario_by_mode, dict) or not target_scenario_by_mode:
                    _issue(issues, "error", "interaction.target_scenario_by_mode", f"{action_base}.target_scenario_by_mode", "target_scenario_by_mode must be a non-empty object.")
                elif not target:
                    _issue(issues, "error", "interaction.target_scenario_by_mode", f"{action_base}.target_scenario_by_mode", "target_scenario_by_mode requires target_screen.")
                else:
                    for mode_name, mode_scenario in target_scenario_by_mode.items():
                        mode_base = f"{action_base}.target_scenario_by_mode.{mode_name}"
                        if not isinstance(mode_name, str) or not mode_name or not isinstance(mode_scenario, str) or not mode_scenario:
                            _issue(issues, "error", "interaction.target_scenario_by_mode", mode_base, "Mode and scenario names must be non-empty strings.")
                        elif mode_name not in {"online", "local_demo"}:
                            _issue(issues, "error", "interaction.target_scenario_by_mode", mode_base, "Supported modes are online and local_demo.")
                        elif target in known_screens and mode_scenario not in screen_scenarios.get(str(target), {"default"}):
                            _issue(issues, "error", "interaction.unknown_target_scenario", mode_base, f"Unknown scenario on {target}: {mode_scenario}")
            source_scenarios = interaction.get("source_scenarios")
            if source_scenarios is not None:
                if not isinstance(source_scenarios, list) or not source_scenarios or any(not isinstance(value, str) or not value for value in source_scenarios):
                    _issue(issues, "error", "interaction.source_scenarios", f"{action_base}.source_scenarios", "source_scenarios must be a non-empty array of scenario names.")
                else:
                    for source_scenario in source_scenarios:
                        if source_scenario not in screen_scenarios.get(str(screen_id), {"default"}):
                            _issue(issues, "error", "interaction.unknown_source_scenario", f"{action_base}.source_scenarios", f"Unknown source scenario on {screen_id}: {source_scenario}")
            source_modes = interaction.get("source_modes")
            if source_modes is not None:
                if not isinstance(source_modes, list) or not source_modes or any(value not in {"online", "local_demo"} for value in source_modes):
                    _issue(issues, "error", "interaction.source_modes", f"{action_base}.source_modes", "source_modes must be a non-empty array containing online and/or local_demo.")
            restore_history = interaction.get("restore_history")
            if restore_history is not None:
                if not isinstance(restore_history, bool):
                    _issue(issues, "error", "interaction.restore_history", f"{action_base}.restore_history", "restore_history must be boolean.")
                elif restore_history and not target:
                    _issue(issues, "error", "interaction.restore_history", f"{action_base}.restore_history", "restore_history requires target_screen.")
        if interactive:
            if strict and not interactions:
                _issue(issues, "error", "interactions.missing", f"{base}.interactions", "Interactive element needs at least one input/action mapping.")
            exceptions = element.get("input_exceptions", {})
            if exceptions is None:
                exceptions = {}
            if not isinstance(exceptions, dict) or any(not isinstance(key, str) or not str(value).strip() for key, value in exceptions.items()):
                _issue(issues, "error", "input.exceptions", f"{base}.input_exceptions", "Input exceptions must map device IDs to non-empty reasons.")
                exceptions = {}
            if gate("approved_requires_input_parity"):
                missing_inputs = sorted(required_inputs - covered_inputs - set(exceptions))
                if missing_inputs:
                    _issue(issues, "error", "input.parity", f"{base}.interactions", f"Missing input coverage or exception for: {', '.join(missing_inputs)}")
            states = element.get("states")
            if not isinstance(states, dict):
                _issue(issues, "error", "states.missing", f"{base}.states", "Interactive element needs states.")
            elif strict:
                missing = sorted(REQUIRED_INTERACTIVE_STATES - set(states))
                if missing:
                    _issue(issues, "error", "states.incomplete", f"{base}.states", f"Missing states: {', '.join(missing)}")
                for state_name in sorted(REQUIRED_INTERACTIVE_STATES & set(states)):
                    definition = states.get(state_name)
                    if definition in (None, "", {}, []):
                        _issue(issues, "error", "states.undefined", f"{base}.states.{state_name}", "Define the state or record a non-applicable reason.")
            accessibility = element_accessibility
            if isinstance(accessibility, dict):
                order = accessibility.get("focus_order")
                if isinstance(order, bool) or (order is not None and not isinstance(order, int)):
                    _issue(issues, "error", "accessibility.focus_order", f"{base}.accessibility.focus_order", "Focus order must be a positive integer.")
                elif isinstance(order, int):
                    if order < 1:
                        _issue(issues, "error", "accessibility.focus_order", f"{base}.accessibility.focus_order", "Focus order must be at least 1.")
                    elif order in focus_orders:
                        _issue(issues, "error", "accessibility.focus_duplicate", f"{base}.accessibility.focus_order", f"Duplicate focus order: {order}")
                    focus_orders.add(order)
                elif gate("approved_requires_accessibility") and not accessibility.get("focus_exception"):
                    _issue(issues, "error", "accessibility.focus_order", f"{base}.accessibility", "Interactive element needs focus_order or an explicit focus_exception.")
            if gate("approved_requires_accessibility") and isinstance(accessibility, dict) and not accessibility.get("non_color_cues") and not accessibility.get("non_color_exception"):
                _issue(issues, "error", "accessibility.non_color", f"{base}.accessibility", "Define a non-color cue or an explicit exception.")
        _validate_acceptance(
            element.get("acceptance", []),
            f"{base}.acceptance",
            issues,
            gate("approved_requires_acceptance"),
        )

        bindings = element.get("data_bindings", [])
        if bindings is not None and not isinstance(bindings, list):
            _issue(issues, "error", "bindings.not_array", f"{base}.data_bindings", "Data bindings must be an array.")
        for binding_index, binding in enumerate(bindings or []):
            binding_base = f"{base}.data_bindings[{binding_index}]"
            if not isinstance(binding, dict) or not binding.get("path"):
                _issue(issues, "error", "binding.path", binding_base, "Binding needs a data path.")
            elif strict and not (binding.get("source") or binding.get("assumption")):
                _issue(issues, "error", "binding.provenance", binding_base, "Binding needs a GDD source or an explicit assumption.")

    for element_id, element in element_map.items():
        parent = element.get("parent")
        if parent is not None and (not isinstance(parent, str) or parent not in element_map):
            _issue(issues, "error", "element.parent", f"{rel}:elements.{element_id}.parent", f"Unknown parent element: {parent}")
    for element_id in element_map:
        chain: set[str] = set()
        current = element_id
        while current in element_map and element_map[current].get("parent"):
            if current in chain:
                _issue(issues, "error", "element.parent_cycle", f"{rel}:elements.{element_id}.parent", f"Parent cycle includes {current}.")
                break
            chain.add(current)
            current = str(element_map[current].get("parent"))

    for index, exit_path in enumerate(screen.get("exit_paths", []) or []):
        if not isinstance(exit_path, dict):
            _issue(issues, "error", "exit.not_object", f"{rel}:exit_paths[{index}]", "Exit path must be an object.")
            continue
        target = exit_path.get("target_screen")
        if target and target not in known_screens:
            _issue(issues, "error", "exit.unknown_target", f"{rel}:exit_paths[{index}]", f"Unknown target screen: {target}")
        if strict and not (exit_path.get("action") or exit_path.get("action_id")):
            _issue(issues, "error", "exit.action", f"{rel}:exit_paths[{index}]", "Reviewed/approved exit paths need an action or action_id.")
        if strict and not (target or exit_path.get("outcome")):
            _issue(issues, "error", "exit.destination", f"{rel}:exit_paths[{index}]", "Reviewed/approved exit paths need target_screen or an explicit external outcome.")
    if screen.get("open_questions"):
        if gate("approved_requires_no_open_questions", False):
            _issue(issues, "error", "questions.open", f"{rel}:open_questions", "The configured approval gate requires every open question to be resolved.")
        elif strict_all:
            _issue(issues, "warning", "questions.open", f"{rel}:open_questions", "Open questions remain in strict validation.")


def _validate_component(
    path: Path,
    component: dict[str, Any],
    known_refs: set[str],
    unavailable_refs: set[str],
    required_inputs: set[str],
    quality_gates: dict[str, bool],
    issues: list[ValidationIssue],
    strict_all: bool,
) -> None:
    rel = str(path)
    strict = strict_all or component.get("status") in {"reviewed", "approved"}

    def gate(name: str, default: bool = True) -> bool:
        return strict and quality_gates.get(name, default) is True
    for key in ("schema_version", "kind", "id", "name", "status", "revision", "purpose", "states", "provenance"):
        if key not in component:
            _issue(issues, "error", "component.required", f"{rel}:{key}", "Required field is missing.")
    if component.get("schema_version") != DESIGN_SCHEMA_VERSION:
        _issue(issues, "error", "schema.version", rel, f"Expected schema_version {DESIGN_SCHEMA_VERSION}.")
    component_id = component.get("id")
    if not isinstance(component_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", component_id):
        _issue(issues, "error", "component.id", f"{rel}:id", "Use a portable lowercase ID beginning with a letter (a-z, 0-9, hyphen).")
    elif path.stem != component_id:
        _issue(issues, "error", "component.filename", rel, f"Filename must match component ID: {component_id}.json")
    if not str(component.get("name", "")).strip():
        _issue(issues, "error", "component.name", f"{rel}:name", "Component needs a name.")
    revision = component.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        _issue(issues, "error", "revision.invalid", f"{rel}:revision", "Revision must be a positive integer.")
    provenance = component.get("provenance")
    if not isinstance(provenance, dict) or not str(provenance.get("created_by", "")).strip() or not str(provenance.get("created_at", "")).strip():
        _issue(issues, "error", "provenance.invalid", f"{rel}:provenance", "Provenance needs non-empty created_by and created_at fields.")
    if component.get("status") not in STATUS_ORDER:
        _issue(issues, "error", "status.invalid", f"{rel}:status", f"Expected one of {', '.join(STATUS_ORDER)}.")
    if strict and not str(component.get("purpose", "")).strip():
        _issue(issues, "error", "component.purpose", f"{rel}:purpose", "Reviewed/approved component needs a purpose.")
    states = component.get("states", {})
    if not isinstance(states, dict):
        _issue(issues, "error", "states.missing", f"{rel}:states", "Component states must be an object.")
    elif strict:
        missing = sorted(REQUIRED_INTERACTIVE_STATES - set(states))
        if missing:
            _issue(issues, "error", "states.incomplete", f"{rel}:states", f"Missing states: {', '.join(missing)}")
        for state_name in sorted(REQUIRED_INTERACTIVE_STATES & set(states)):
            definition = states.get(state_name)
            if definition in (None, "", {}, []):
                _issue(issues, "error", "states.undefined", f"{rel}:states.{state_name}", "Define the state or record a non-applicable reason.")
    _validate_reference_ids(
        component.get("reference_ids", []), known_refs, f"{rel}:reference_ids", issues,
        unavailable_refs=unavailable_refs, require_available=strict,
    )
    interactive = component.get("interactive", False)
    if not isinstance(interactive, bool):
        _issue(issues, "error", "component.interactive", f"{rel}:interactive", "interactive must be a boolean when provided.")
        interactive = False
    inputs = component.get("inputs", [])
    if not isinstance(inputs, list):
        _issue(issues, "error", "component.inputs", f"{rel}:inputs", "Component inputs must be an array.")
        inputs = []
    if interactive:
        if strict and not inputs:
            _issue(issues, "error", "component.inputs.missing", f"{rel}:inputs", "Reviewed/approved interactive component needs at least one input mapping.")
        covered: set[str] = set()
        for input_index, item in enumerate(inputs):
            input_base = f"{rel}:inputs[{input_index}]"
            if not isinstance(item, dict):
                _issue(issues, "error", "component.input.not_object", input_base, "Input mapping must be an object.")
                continue
            if not str(item.get("input", "")).strip() or not str(item.get("action", "")).strip():
                _issue(issues, "error" if strict else "warning", "component.input.incomplete", input_base, "Input mapping needs non-empty input and action fields.")
            devices = item.get("devices", [])
            if not isinstance(devices, list) or not devices or any(not isinstance(device, str) or not device for device in devices):
                _issue(issues, "error", "component.input.devices", f"{input_base}.devices", "devices must be a non-empty array of input-device IDs.")
            else:
                covered.update(devices)
        raw_exceptions = component.get("input_exceptions", {})
        if raw_exceptions is None:
            raw_exceptions = {}
        if not isinstance(raw_exceptions, dict) or any(not isinstance(key, str) or not str(value).strip() for key, value in raw_exceptions.items()):
            _issue(issues, "error", "input.exceptions", f"{rel}:input_exceptions", "Input exceptions must map device IDs to non-empty reasons.")
            raw_exceptions = {}
        missing = sorted(required_inputs - covered - set(raw_exceptions)) if gate("approved_requires_input_parity") else []
        if missing:
            _issue(issues, "error", "input.parity", f"{rel}:inputs", f"Missing input coverage or exception for: {', '.join(missing)}")
    elif inputs:
        _issue(issues, "error", "component.interactive", f"{rel}:inputs", "Components with input mappings must set interactive=true.")
    if gate("approved_requires_accessibility"):
        accessibility = component.get("accessibility")
        if not isinstance(accessibility, dict) or not accessibility.get("role") or not accessibility.get("non_color_cues"):
            _issue(issues, "error", "component.accessibility", f"{rel}:accessibility", "Define a role and non-color cues or disable the configured accessibility gate.")
    _validate_acceptance(component.get("acceptance", []), f"{rel}:acceptance", issues, gate("approved_requires_acceptance"))


def _validate_collection_root(document: Any, path: Path, kind: str, key: str, issues: list[ValidationIssue]) -> list[Any]:
    if not isinstance(document, dict):
        _issue(issues, "error", f"{kind}.not_object", str(path), "Document root must be an object.")
        return []
    if document.get("schema_version") != DESIGN_SCHEMA_VERSION:
        _issue(issues, "error", "schema.version", str(path), f"Expected schema_version {DESIGN_SCHEMA_VERSION}.")
    if document.get("kind") != kind:
        _issue(issues, "error", f"{kind}.kind", str(path), f"Expected kind={kind!r}.")
    values = document.get(key)
    if not isinstance(values, list):
        _issue(issues, "error", f"{kind}.not_array", f"{path}:{key}", f"{key} must be an array.")
        return []
    return values


def _validate_tokens(tokens: Any, path: Path, issues: list[ValidationIssue]) -> None:
    if not isinstance(tokens, dict):
        _issue(issues, "error", "tokens.not_object", str(path), "Token document root must be an object.")
        return
    if tokens.get("schema_version") != DESIGN_SCHEMA_VERSION:
        _issue(issues, "error", "schema.version", str(path), f"Expected schema_version {DESIGN_SCHEMA_VERSION}.")
    if tokens.get("kind") != "tokens":
        _issue(issues, "error", "tokens.kind", str(path), "Expected kind='tokens'.")
    if tokens.get("status") not in STATUS_ORDER:
        _issue(issues, "error", "tokens.status", f"{path}:status", f"Expected one of {', '.join(STATUS_ORDER)}.")
    for group in ("color", "spacing", "typography", "motion", "input"):
        if not isinstance(tokens.get(group), dict) or not tokens.get(group):
            _issue(issues, "error", "tokens.group", f"{path}:{group}", f"{group} must be a non-empty object.")
    colors = tokens.get("color", {}) if isinstance(tokens.get("color"), dict) else {}
    for name, definition in colors.items():
        if not isinstance(definition, dict) or definition.get("value") in (None, ""):
            _issue(issues, "error", "tokens.color", f"{path}:color.{name}", "Color token needs a value and object metadata.")
        elif not str(definition.get("source", "")).strip():
            _issue(issues, "error", "tokens.source", f"{path}:color.{name}", "Record a source or assumption for the color token.")
    for group in ("spacing", "motion", "input"):
        values = tokens.get(group, {}) if isinstance(tokens.get(group), dict) else {}
        for name, value in values.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(float(value)) or value < 0:
                    _issue(issues, "error", "tokens.number", f"{path}:{group}.{name}", "Numeric token must be finite and non-negative.")
    typography = tokens.get("typography", {}) if isinstance(tokens.get("typography"), dict) else {}
    for name, style in typography.items():
        base = f"{path}:typography.{name}"
        if not isinstance(style, dict):
            _issue(issues, "error", "tokens.typography", base, "Typography token must be an object.")
            continue
        if not str(style.get("family", "")).strip():
            _issue(issues, "error", "tokens.typography", f"{base}.family", "Typography token needs a font family.")
        size = style.get("size")
        weight = style.get("weight")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(float(size)) or size <= 0:
            _issue(issues, "error", "tokens.typography", f"{base}.size", "Typography size must be a finite positive number.")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(float(weight)) or not 1 <= weight <= 1000:
            _issue(issues, "error", "tokens.typography", f"{base}.weight", "Typography weight must be between 1 and 1000.")

    def walk(value: Any, base: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{base}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{base}[{index}]")
        elif isinstance(value, float) and not math.isfinite(value):
            _issue(issues, "error", "tokens.number", base, "Token numbers must be finite.")

    walk(tokens, str(path))


def _validate_route_guards(
    route: dict[str, Any],
    base: str,
    source_screen: str,
    target_screen: str,
    known_screens: set[str],
    screen_scenarios: dict[str, set[str]],
    issues: list[ValidationIssue],
    code_prefix: str,
) -> None:
    source_scenarios = route.get("source_scenarios")
    if source_scenarios is not None:
        if not isinstance(source_scenarios, list) or not source_scenarios or any(not isinstance(value, str) or not value for value in source_scenarios):
            _issue(issues, "error", f"{code_prefix}.source_scenarios", f"{base}.source_scenarios", "source_scenarios must be a non-empty array of scenario names.")
        else:
            for scenario in source_scenarios:
                if scenario not in screen_scenarios.get(source_screen, {"default"}):
                    _issue(issues, "error", f"{code_prefix}.unknown_source_scenario", f"{base}.source_scenarios", f"Unknown source scenario on {source_screen}: {scenario}")
    source_modes = route.get("source_modes")
    if source_modes is not None and (
        not isinstance(source_modes, list)
        or not source_modes
        or any(value not in {"online", "local_demo"} for value in source_modes)
    ):
        _issue(issues, "error", f"{code_prefix}.source_modes", f"{base}.source_modes", "source_modes must be a non-empty array containing online and/or local_demo.")
    target_scenario_by_mode = route.get("target_scenario_by_mode")
    if target_scenario_by_mode is not None:
        if not isinstance(target_scenario_by_mode, dict) or not target_scenario_by_mode:
            _issue(issues, "error", f"{code_prefix}.target_scenario_by_mode", f"{base}.target_scenario_by_mode", "target_scenario_by_mode must be a non-empty object.")
        elif not target_screen:
            _issue(issues, "error", f"{code_prefix}.target_scenario_by_mode", f"{base}.target_scenario_by_mode", "target_scenario_by_mode requires target_screen.")
        else:
            for mode_name, scenario in target_scenario_by_mode.items():
                mode_base = f"{base}.target_scenario_by_mode.{mode_name}"
                if mode_name not in {"online", "local_demo"} or not isinstance(scenario, str) or not scenario:
                    _issue(issues, "error", f"{code_prefix}.target_scenario_by_mode", mode_base, "Use online/local_demo keys with non-empty scenario names.")
                elif target_screen in known_screens and scenario not in screen_scenarios.get(target_screen, {"default"}):
                    _issue(issues, "error", f"{code_prefix}.unknown_target_scenario", mode_base, f"Unknown scenario on {target_screen}: {scenario}")
    restore_history = route.get("restore_history")
    if restore_history is not None:
        if not isinstance(restore_history, bool):
            _issue(issues, "error", f"{code_prefix}.restore_history", f"{base}.restore_history", "restore_history must be boolean.")
        elif restore_history and not target_screen:
            _issue(issues, "error", f"{code_prefix}.restore_history", f"{base}.restore_history", "restore_history requires target_screen.")


def validate_design_workspace(
    design_root: Path,
    strict: bool = False,
    *,
    project_root: Path | None = None,
) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    reference_root = (project_root or design_root.parent).resolve()
    project_path = design_root / "project.json"
    if not project_path.exists():
        _issue(issues, "error", "project.missing", str(project_path), "Run `ui-ref spec init` first.")
        return issues, {}
    try:
        project = _read_json(project_path)
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "project.invalid", str(project_path), str(exc))
        return issues, {}
    if not isinstance(project, dict):
        _issue(issues, "error", "project.not_object", str(project_path), "Project document root must be an object.")
        return issues, {}
    if project.get("schema_version") != DESIGN_SCHEMA_VERSION:
        _issue(issues, "error", "schema.version", str(project_path), f"Expected schema_version {DESIGN_SCHEMA_VERSION}.")
    if project.get("kind") != "project":
        _issue(issues, "error", "project.kind", str(project_path), "Expected kind='project'.")
    project_meta = project.get("project", {}) if isinstance(project.get("project"), dict) else {}
    quality_gates_raw = project.get("quality_gates", {})
    if not isinstance(quality_gates_raw, dict):
        _issue(issues, "error", "quality_gates.not_object", f"{project_path}:quality_gates", "quality_gates must be an object.")
        quality_gates_raw = {}
    quality_gates: dict[str, bool] = {}
    for gate_name, default in QUALITY_GATE_DEFAULTS.items():
        gate_value = quality_gates_raw.get(gate_name, default)
        if not isinstance(gate_value, bool):
            _issue(issues, "error", "quality_gates.boolean", f"{project_path}:quality_gates.{gate_name}", "Quality-gate values must be booleans.")
            gate_value = default
        quality_gates[gate_name] = gate_value
    for gate_name in sorted(set(quality_gates_raw) - set(QUALITY_GATE_DEFAULTS)):
        _issue(issues, "error", "quality_gates.unknown", f"{project_path}:quality_gates.{gate_name}", "Unknown quality-gate key; fix the spelling or remove it.")
    for key in ("id", "name", "status", "platforms", "input_devices", "aspect_ratios", "default_locale"):
        if key not in project_meta:
            _issue(issues, "error", "project.required", f"{project_path}:project.{key}", "Required project metadata is missing; run `ui-ref spec init --force` to migrate starters.")
    for key in ("id", "name", "default_locale"):
        if not isinstance(project_meta.get(key), str) or not project_meta.get(key, "").strip():
            _issue(issues, "error", f"project.{key}", f"{project_path}:project.{key}", f"{key} must be a non-empty string.")
    project_id = project_meta.get("id")
    if isinstance(project_id, str) and not re.fullmatch(r"[a-z][a-z0-9-]*", project_id):
        _issue(issues, "error", "project.id", f"{project_path}:project.id", "Use a portable lowercase ID beginning with a letter (a-z, 0-9, hyphen).")
    if project_meta.get("status") not in STATUS_ORDER:
        _issue(issues, "error", "project.status", f"{project_path}:project.status", f"Expected one of {', '.join(STATUS_ORDER)}.")
    for key in ("platforms", "aspect_ratios"):
        values = project_meta.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
            _issue(issues, "error", f"project.{key}", f"{project_path}:project.{key}", f"{key} must be a non-empty array of IDs.")
    raw_required_inputs = project_meta.get("input_devices", [])
    if not isinstance(raw_required_inputs, list) or not raw_required_inputs or any(not isinstance(value, str) or not value for value in raw_required_inputs):
        _issue(issues, "error", "project.input_devices", str(project_path), "project.input_devices must be a non-empty array of IDs.")
        required_inputs: set[str] = set()
    else:
        required_inputs = set(raw_required_inputs)
        if len(required_inputs) != len(raw_required_inputs):
            _issue(issues, "error", "project.input_duplicate", str(project_path), "project.input_devices contains duplicate IDs.")

    tokens_path = design_root / "tokens.json"
    try:
        tokens = _read_json(tokens_path)
        _validate_tokens(tokens, tokens_path, issues)
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "tokens.invalid", str(tokens_path), str(exc))

    references_path = design_root / "references.json"
    references: dict[str, Any] = {}
    try:
        references = _read_json(references_path)
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "references.invalid", str(references_path), str(exc))
    sources = _validate_collection_root(references, references_path, "references", "sources", issues)
    known_refs: set[str] = set()
    unavailable_refs: set[str] = set()
    for index, source in enumerate(sources):
        source_base = f"{references_path}:sources[{index}]"
        if not isinstance(source, dict):
            _issue(issues, "error", "reference.not_object", source_base, "Reference must be an object.")
            continue
        ref_id = source.get("id")
        if not isinstance(ref_id, str) or not ref_id.strip():
            _issue(issues, "error", "reference.id", source_base, "Reference needs a non-empty string ID.")
            continue
        if ref_id in known_refs:
            _issue(issues, "error", "reference.duplicate", source_base, f"Duplicate reference ID: {ref_id}")
        known_refs.add(ref_id)
        source_type = source.get("source_type")
        if source_type not in REFERENCE_SOURCE_TYPES:
            _issue(issues, "error", "reference.source_type", f"{source_base}.source_type", f"Expected one of: {', '.join(sorted(REFERENCE_SOURCE_TYPES))}.")
            unavailable_refs.add(ref_id)
        declared_state = source.get("sync_state")
        if declared_state not in REFERENCE_SYNC_STATES:
            _issue(issues, "error", "reference.sync_state", f"{source_base}.sync_state", f"Expected one of: {', '.join(sorted(REFERENCE_SYNC_STATES))}.")
            unavailable_refs.add(ref_id)
        raw_uri = source.get("uri")
        if not isinstance(raw_uri, str) or not raw_uri.strip():
            _issue(issues, "error", "reference.uri", f"{source_base}.uri", "Reference needs a local evidence path.")
            unavailable_refs.add(ref_id)
        digest = source.get("sha256")
        if declared_state == "present" and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            _issue(issues, "error", "reference.hash", f"{source_base}.sha256", "Present evidence needs a lowercase SHA-256 digest.")
            unavailable_refs.add(ref_id)
        elif digest not in (None, "") and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            _issue(issues, "error", "reference.hash", f"{source_base}.sha256", "Expected an empty value or a lowercase SHA-256 digest.")
            unavailable_refs.add(ref_id)
        actual_state = _reference_actual_state(source, reference_root)
        if declared_state in {"missing", "invalid_path", "hash_mismatch"} or actual_state in {"missing", "invalid_path", "hash_mismatch", "hash_missing", "unsupported_type"}:
            unavailable_refs.add(str(ref_id))
        if actual_state is not None and declared_state == "present" and actual_state != "present":
            _issue(
                issues,
                "error",
                "reference.stale_sync",
                source_base,
                f"Catalog says present but current evidence state is {actual_state}; synchronize references before validation/release.",
            )
        elif actual_state == "present" and declared_state in {"missing", "invalid_path", "hash_mismatch"}:
            _issue(issues, "warning", "reference.stale_sync", source_base, "Evidence is present again; synchronize the catalog before review.")
        if source.get("sync_state") == "invalid_path":
            _issue(issues, "error", "reference.path_escape", source_base, "Reference manifest path escapes the project root and was not read.")

    approvals_path = design_root / "approvals.json"
    approvals: list[dict[str, Any]] = []
    try:
        approval_document = _read_json(approvals_path)
        raw_approvals = _validate_collection_root(approval_document, approvals_path, "approvals", "approvals", issues)
        approvals = [item for item in raw_approvals if isinstance(item, dict)]
        approval_ids: set[str] = set()
        for index, item in enumerate(raw_approvals):
            base = f"{approvals_path}:approvals[{index}]"
            if not isinstance(item, dict):
                _issue(issues, "error", "approval.not_object", base, "Approval entry must be an object.")
                continue
            approval_id = item.get("id")
            if not isinstance(approval_id, str) or not approval_id:
                _issue(issues, "error", "approval.id", base, "Approval entry needs an ID.")
            elif approval_id in approval_ids:
                _issue(issues, "error", "approval.duplicate", base, f"Duplicate approval ID: {approval_id}")
            approval_ids.add(str(approval_id))
            for field in ("artifact_kind", "artifact_id", "status", "actor", "actor_type", "recorded_at", "content_sha256"):
                if item.get(field) in (None, ""):
                    _issue(issues, "error", "approval.required", f"{base}.{field}", "Required approval ledger field is missing.")
            if item.get("artifact_kind") not in {"screen", "component"}:
                _issue(issues, "error", "approval.kind", base, "artifact_kind must be screen or component.")
            if item.get("actor_type") not in {"agent", "human"}:
                _issue(issues, "error", "approval.actor_type", base, "actor_type must be agent or human.")
            if item.get("status") == "approved" and item.get("actor_type") != "human":
                _issue(issues, "error", "approval.not_human", base, "Approved ledger entries must identify a human actor.")
            digest = item.get("content_sha256")
            if digest and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                _issue(issues, "error", "approval.hash", f"{base}.content_sha256", "Expected a lowercase SHA-256 digest.")
            if not isinstance(item.get("dependency_sha256"), dict):
                _issue(issues, "error", "approval.dependencies", f"{base}.dependency_sha256", "Dependency hash snapshot must be an object.")
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "approvals.invalid", str(approvals_path), str(exc))

    screens = _load_contracts(design_root / "screens", "screen", issues)
    components = _load_contracts(design_root / "components", "component", issues)
    component_statuses: dict[str, str] = {}
    for path, component in components:
        component_id = component.get("id")
        if isinstance(component_id, str):
            if component_id in component_statuses:
                _issue(issues, "error", "component.duplicate", str(path), f"Duplicate component ID: {component_id}")
            component_statuses[component_id] = str(component.get("status", ""))
    known_screens: set[str] = set()
    screen_scenarios: dict[str, set[str]] = {}
    for path, screen in screens:
        screen_id = screen.get("id")
        if isinstance(screen_id, str):
            if screen_id in known_screens:
                _issue(issues, "error", "screen.duplicate", str(path), f"Duplicate screen ID: {screen_id}")
            known_screens.add(screen_id)
            screen_scenarios[screen_id] = _screen_scenario_names(screen)
    for path, screen in screens:
        _validate_screen(
            path,
            screen,
            known_refs,
            unavailable_refs,
            known_screens,
            screen_scenarios,
            component_statuses,
            required_inputs,
            quality_gates,
            issues,
            strict,
        )
        _validate_approval(design_root, path, screen, approvals, issues)
    for path, component in components:
        _validate_component(path, component, known_refs, unavailable_refs, required_inputs, quality_gates, issues, strict)
        _validate_approval(design_root, path, component, approvals, issues)

    flows_path = design_root / "flows.json"
    flows: dict[str, Any] = {}
    try:
        flows = _read_json(flows_path)
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "flows.invalid", str(flows_path), str(exc))
    flow_values = _validate_collection_root(flows, flows_path, "flows", "flows", issues)
    flow_ids: set[str] = set()
    transition_targets: dict[tuple[str, str], set[str]] = {}
    for screen_path, screen in screens:
        screen_id = str(screen.get("id", ""))
        authored_transitions: list[tuple[str, str, str]] = []
        for exit_index, exit_path in enumerate(screen.get("exit_paths", []) or []):
            if isinstance(exit_path, dict):
                action = str(exit_path.get("action") or exit_path.get("action_id") or "")
                target = str(exit_path.get("target_screen") or "")
                exit_base = f"{screen_path}:exit_paths[{exit_index}]"
                target_scenario = exit_path.get("target_scenario")
                if target_scenario is not None:
                    if not isinstance(target_scenario, str) or not target_scenario:
                        _issue(issues, "error", "navigation.target_scenario", f"{exit_base}.target_scenario", "target_scenario must be a non-empty string.")
                    elif target_scenario == "@base":
                        if target != screen_id:
                            _issue(issues, "error", "navigation.target_scenario", f"{exit_base}.target_scenario", "@base is valid only for a same-screen overlay transition.")
                    elif target in known_screens and target_scenario not in screen_scenarios.get(target, {"default"}):
                        _issue(issues, "error", "navigation.unknown_target_scenario", f"{exit_base}.target_scenario", f"Unknown scenario on {target}: {target_scenario}")
                _validate_route_guards(
                    exit_path,
                    exit_base,
                    screen_id,
                    target,
                    known_screens,
                    screen_scenarios,
                    issues,
                    "navigation",
                )
                authored_transitions.append((action, target, exit_base))
        for element_index, element in enumerate(screen.get("elements", []) or []):
            if not isinstance(element, dict):
                continue
            for interaction_index, interaction in enumerate(element.get("interactions", []) or []):
                if isinstance(interaction, dict):
                    action = str(interaction.get("action") or interaction.get("action_id") or "")
                    target = str(interaction.get("target_screen") or "")
                    authored_transitions.append((action, target, f"{screen_path}:elements[{element_index}].interactions[{interaction_index}]"))
        for action, target, transition_path in authored_transitions:
            if not action or not target:
                continue
            key = (screen_id, action)
            existing_targets = transition_targets.setdefault(key, set())
            if existing_targets and target not in existing_targets:
                _issue(issues, "error", "navigation.conflict", transition_path, f"Action {action!r} has conflicting targets: {', '.join(sorted(existing_targets | {target}))}")
            existing_targets.add(target)
    for index, flow in enumerate(flow_values):
        base = f"{flows_path}:flows[{index}]"
        if not isinstance(flow, dict):
            _issue(issues, "error", "flow.id", base, "Flow needs an ID.")
            continue
        flow_id = flow.get("id")
        if not isinstance(flow_id, str) or not flow_id:
            _issue(issues, "error", "flow.id", base, "Flow needs a string ID.")
            continue
        if not re.fullmatch(r"[a-z][a-z0-9-]*", flow_id):
            _issue(issues, "error", "flow.id", base, "Use a portable lowercase flow ID (a-z, 0-9, hyphen).")
        if flow_id in flow_ids:
            _issue(issues, "error", "flow.duplicate", base, f"Duplicate flow ID: {flow_id}")
        flow_ids.add(flow_id)
        entry = flow.get("entry_screen")
        if not isinstance(entry, str) or not entry:
            _issue(issues, "error", "flow.entry", base, "Flow needs an entry_screen.")
        elif entry not in known_screens:
            _issue(issues, "error", "flow.unknown_entry", base, f"Unknown entry screen: {entry}")
        entry_scenario = flow.get("entry_scenario")
        if entry_scenario is not None:
            if not isinstance(entry_scenario, str) or not entry_scenario:
                _issue(issues, "error", "flow.entry_scenario", f"{base}.entry_scenario", "entry_scenario must be a non-empty string.")
            elif isinstance(entry, str) and entry in known_screens and entry_scenario not in screen_scenarios.get(entry, {"default"}):
                _issue(issues, "error", "flow.unknown_entry_scenario", f"{base}.entry_scenario", f"Unknown scenario on {entry}: {entry_scenario}")
        steps = flow.get("steps", [])
        if not isinstance(steps, list) or not steps:
            _issue(issues, "error", "flow.steps", f"{base}.steps", "Flow needs at least one ordered step.")
            steps = []
        expected_source = entry if isinstance(entry, str) and entry else None
        for step_index, step in enumerate(steps):
            step_base = f"{base}.steps[{step_index}]"
            if not isinstance(step, dict):
                _issue(issues, "error", "flow.step", step_base, "Flow step must be an object.")
                continue
            for field in ("screen", "next_screen"):
                target = step.get(field)
                if not isinstance(target, str) or not target:
                    _issue(issues, "error", "flow.step_required", f"{step_base}.{field}", f"Flow step needs {field}.")
                elif target not in known_screens:
                    _issue(issues, "error", "flow.unknown_screen", step_base, f"Unknown {field}: {target}")
            action = step.get("action") or step.get("action_id")
            if not isinstance(action, str) or not action:
                _issue(issues, "error", "flow.action", step_base, "Flow step needs an action or action_id.")
                continue
            source = step.get("screen")
            target = step.get("next_screen")
            target_scenario = step.get("target_scenario")
            if target_scenario is not None:
                if not isinstance(target_scenario, str) or not target_scenario:
                    _issue(issues, "error", "flow.target_scenario", f"{step_base}.target_scenario", "target_scenario must be a non-empty string.")
                elif target_scenario == "@base":
                    if target != source:
                        _issue(issues, "error", "flow.target_scenario", f"{step_base}.target_scenario", "@base is valid only for a same-screen overlay transition.")
                elif isinstance(target, str) and target in known_screens and target_scenario not in screen_scenarios.get(target, {"default"}):
                    _issue(issues, "error", "flow.unknown_target_scenario", f"{step_base}.target_scenario", f"Unknown scenario on {target}: {target_scenario}")
            _validate_route_guards(
                step,
                step_base,
                str(source or ""),
                str(target or ""),
                known_screens,
                screen_scenarios,
                issues,
                "flow",
            )
            if expected_source and isinstance(source, str) and source and source != expected_source:
                _issue(issues, "error", "flow.disconnected", f"{step_base}.screen", f"Ordered flow expected screen {expected_source!r}, not {source!r}.")
            if isinstance(source, str) and isinstance(target, str) and source and target:
                key = (source, action)
                existing_targets = transition_targets.setdefault(key, set())
                if existing_targets and target not in existing_targets:
                    _issue(issues, "error", "flow.conflict", step_base, f"Action {action!r} conflicts with an authored target: {', '.join(sorted(existing_targets | {target}))}")
                existing_targets.add(target)
                expected_source = target

    decisions_path = design_root / "decisions.json"
    try:
        decisions_document = _read_json(decisions_path)
        decision_values = _validate_collection_root(decisions_document, decisions_path, "decisions", "decisions", issues)
        decision_ids: set[str] = set()
        for index, decision in enumerate(decision_values):
            base = f"{decisions_path}:decisions[{index}]"
            if not isinstance(decision, dict):
                _issue(issues, "error", "decision.not_object", base, "Decision must be an object.")
                continue
            decision_id = decision.get("id")
            if not isinstance(decision_id, str) or not decision_id:
                _issue(issues, "error", "decision.id", base, "Decision needs an ID.")
            elif decision_id in decision_ids:
                _issue(issues, "error", "decision.duplicate", base, f"Duplicate decision ID: {decision_id}")
            decision_ids.add(str(decision_id))
            if not str(decision.get("statement", "")).strip():
                _issue(issues, "error", "decision.statement", base, "Decision needs a statement.")
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "decisions.invalid", str(decisions_path), str(exc))

    summary = {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "validated_at": _now(),
        "strict": strict,
        "screens": len(screens),
        "components": len(components),
        "references": len(known_refs),
        "flows": len(flow_ids),
        "errors": sum(1 for item in issues if item.severity == "error"),
        "warnings": sum(1 for item in issues if item.severity == "warning"),
    }
    return issues, summary


def command_design_validate(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    issues, summary = validate_design_workspace(design_root, strict=args.strict, project_root=_project_root(args))
    error_count = sum(1 for item in issues if item.severity == "error")
    warning_count = sum(1 for item in issues if item.severity == "warning")
    report = {**summary, "errors": error_count, "warnings": warning_count, "issues": [item.as_dict() for item in issues]}
    output = Path(args.output).resolve() if args.output else design_root / "build" / "validation-report.json"
    _write_json(output, report)
    for item in issues:
        print(f"{item.severity.upper()} [{item.code}] {item.path}: {item.message}")
    print(
        f"Validated {report.get('screens', 0)} screen(s), {report.get('components', 0)} component(s): "
        f"{error_count} error(s), {warning_count} warning(s)."
    )
    print(f"Validation report: {output}")
    return 1 if error_count else 0


@dataclass(frozen=True)
class WireNode:
    kind: str
    node_id: str
    attrs: dict[str, str]
    line: int


@dataclass(frozen=True)
class WireCallout:
    target: str
    side: str
    text: str
    line: int


@dataclass(frozen=True)
class WireDocument:
    version: str
    width: int
    height: int
    title: str
    nodes: tuple[WireNode, ...]
    callouts: tuple[WireCallout, ...]


def _parse_attrs(parts: list[str], line_number: int) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            raise ValueError(f"line {line_number}: expected key=value, got {part!r}")
        key, value = part.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            raise ValueError(f"line {line_number}: invalid attribute name {key!r}")
        if key in attrs:
            raise ValueError(f"line {line_number}: duplicate attribute {key!r}")
        attrs[key] = value
    return attrs


def parse_uiwire(source: str) -> WireDocument:
    version = ""
    width = 0
    height = 0
    title = "Wireframe"
    nodes: list[WireNode] = []
    callouts: list[WireCallout] = []
    ids: set[str] = set()
    node_kinds = {"panel", "rect", "text", "button", "bar", "image", "icon", "slot", "input", "toggle"}
    seen_header = False
    seen_canvas = False

    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parts = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
        if not parts:
            continue
        command = parts[0].lower()
        if not seen_header and command != "uiwire":
            raise ValueError(f"line {line_number}: first declaration must be `uiwire 1`")
        if command == "uiwire":
            if seen_header:
                raise ValueError(f"line {line_number}: duplicate uiwire header")
            if len(parts) != 2:
                raise ValueError(f"line {line_number}: use `uiwire 1`")
            version = parts[1]
            if version != "1":
                raise ValueError(f"line {line_number}: unsupported uiwire version {version!r}")
            seen_header = True
            continue
        if command == "canvas":
            if seen_canvas:
                raise ValueError(f"line {line_number}: duplicate canvas declaration")
            if len(parts) < 3:
                raise ValueError(f"line {line_number}: use `canvas WIDTH HEIGHT title=...`")
            try:
                width, height = int(parts[1]), int(parts[2])
            except ValueError as exc:
                raise ValueError(f"line {line_number}: canvas dimensions must be integers") from exc
            if width <= 0 or height <= 0 or width > 16384 or height > 16384:
                raise ValueError(f"line {line_number}: canvas dimensions must be between 1 and 16384")
            attrs = _parse_attrs(parts[3:], line_number)
            unknown = sorted(set(attrs) - {"title"})
            if unknown:
                raise ValueError(f"line {line_number}: unknown canvas attribute(s): {', '.join(unknown)}")
            title = attrs.get("title", title)
            if len(title) > 500:
                raise ValueError(f"line {line_number}: canvas title is too long")
            seen_canvas = True
            continue
        if not seen_canvas:
            raise ValueError(f"line {line_number}: declare canvas before elements or callouts")
        if command in node_kinds:
            if len(nodes) >= 500:
                raise ValueError(f"line {line_number}: uiwire supports at most 500 elements")
            if len(parts) < 2:
                raise ValueError(f"line {line_number}: {command} needs an element ID")
            node_id = parts[1]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", node_id):
                raise ValueError(f"line {line_number}: invalid element ID {node_id!r}")
            if node_id in ids:
                raise ValueError(f"line {line_number}: duplicate element ID {node_id!r}")
            ids.add(node_id)
            attrs = _parse_attrs(parts[2:], line_number)
            allowed_attrs = {"x", "y", "w", "h", "label", "parent", "bind", "action", "asset", "anchor"}
            if command == "bar":
                allowed_attrs.add("value")
            unknown = sorted(set(attrs) - allowed_attrs)
            if unknown:
                raise ValueError(f"line {line_number}: unknown {command} attribute(s): {', '.join(unknown)}")
            if len(attrs.get("label", "")) > 2000:
                raise ValueError(f"line {line_number}: label is too long")
            nodes.append(WireNode(command, node_id, attrs, line_number))
            continue
        if command == "callout":
            if len(callouts) >= 100:
                raise ValueError(f"line {line_number}: uiwire supports at most 100 callouts")
            if len(parts) < 2:
                raise ValueError(f"line {line_number}: callout needs a target ID")
            attrs = _parse_attrs(parts[2:], line_number)
            unknown = sorted(set(attrs) - {"side", "text"})
            if unknown:
                raise ValueError(f"line {line_number}: unknown callout attribute(s): {', '.join(unknown)}")
            side = attrs.get("side", "right").lower()
            if side not in {"left", "right", "top", "bottom"}:
                raise ValueError(f"line {line_number}: invalid callout side {side!r}")
            text = attrs.get("text", "")
            if not text:
                raise ValueError(f"line {line_number}: callout needs text=...")
            if len(text) > 1000:
                raise ValueError(f"line {line_number}: callout text is too long")
            callouts.append(WireCallout(parts[1], side, text, line_number))
            continue
        raise ValueError(f"line {line_number}: unknown command {command!r}")

    if version != "1":
        raise ValueError("missing `uiwire 1` header")
    if width <= 0 or height <= 0:
        raise ValueError("missing `canvas WIDTH HEIGHT` declaration")
    for callout in callouts:
        if callout.target not in ids:
            raise ValueError(f"line {callout.line}: callout target {callout.target!r} does not exist")
    for node in nodes:
        parent = node.attrs.get("parent")
        if parent and parent not in ids:
            raise ValueError(f"line {node.line}: parent {parent!r} does not exist")
        for key in ("x", "y", "w", "h"):
            if key not in node.attrs:
                raise ValueError(f"line {node.line}: {node.kind} {node.node_id} needs {key}=...")
            try:
                numeric = float(node.attrs[key])
            except ValueError as exc:
                raise ValueError(f"line {node.line}: {key} must be numeric") from exc
            if not math.isfinite(numeric):
                raise ValueError(f"line {node.line}: {key} must be finite")
        if float(node.attrs["w"]) <= 0 or float(node.attrs["h"]) <= 0:
            raise ValueError(f"line {node.line}: w and h must be positive")
        if node.kind == "bar" and "value" in node.attrs:
            try:
                bar_value = float(node.attrs["value"])
            except ValueError as exc:
                raise ValueError(f"line {node.line}: bar value must be numeric") from exc
            if not math.isfinite(bar_value):
                raise ValueError(f"line {node.line}: bar value must be finite")
    return WireDocument(version, width, height, title, tuple(nodes), tuple(callouts))


def _node_rects(document: WireDocument) -> dict[str, tuple[float, float, float, float]]:
    raw = {node.node_id: node for node in document.nodes}
    resolved: dict[str, tuple[float, float, float, float]] = {}
    resolving: set[str] = set()

    def resolve(node_id: str) -> tuple[float, float, float, float]:
        if node_id in resolved:
            return resolved[node_id]
        if node_id in resolving:
            raise ValueError(f"parent cycle includes {node_id!r}")
        resolving.add(node_id)
        node = raw[node_id]
        x = float(node.attrs["x"])
        y = float(node.attrs["y"])
        w = float(node.attrs["w"])
        h = float(node.attrs["h"])
        parent = node.attrs.get("parent")
        if parent:
            parent_x, parent_y, _, _ = resolve(parent)
            x += parent_x
            y += parent_y
        resolving.remove(node_id)
        resolved[node_id] = (x, y, w, h)
        return resolved[node_id]

    for node_id in raw:
        resolve(node_id)
    for node_id, (x, y, width, height) in resolved.items():
        if x < 0 or y < 0 or x + width > document.width or y + height > document.height:
            raise ValueError(f"element {node_id!r} extends outside the {document.width}×{document.height} canvas")
    return resolved


def _wrap_svg_lines(text: str, max_chars: int) -> list[str]:
    paragraphs = text.replace("\\n", "\n").splitlines() or [""]
    lines: list[str] = []
    for paragraph in paragraphs:
        current = ""
        for word in paragraph.split():
            if len(word) > max_chars:
                if current:
                    lines.append(current)
                    current = ""
                while len(word) > max_chars:
                    lines.append(word[:max_chars])
                    word = word[max_chars:]
            proposed = word if not current else f"{current} {word}"
            if len(proposed) > max_chars and current:
                lines.append(current)
                current = word
            else:
                current = proposed
        lines.append(current)
    return lines


def _svg_text_lines(
    text: str,
    x: float,
    y: float,
    max_chars: int,
    *,
    cls: str = "label",
    anchor: str = "start",
    max_lines: int | None = 4,
) -> str:
    lines = _wrap_svg_lines(text, max_chars)
    visible_lines = lines if max_lines is None else lines[:max_lines]
    tspans = "".join(
        f'<tspan x="{x:.1f}" dy="{0 if index == 0 else 20}">{escape(line)}</tspan>'
        for index, line in enumerate(visible_lines)
    )
    return f'<text class="{cls}" text-anchor="{anchor}" x="{x:.1f}" y="{y:.1f}">{tspans}</text>'


def render_uiwire_svg(document: WireDocument) -> str:
    rects = _node_rects(document)
    gutter = 420
    horizontal_slot_width = 540.0
    view_x = -gutter
    horizontal_heights = {"left": 36.0, "right": 36.0}
    horizontal_counts = {"top": 0, "bottom": 0}
    top_line_counts: list[int] = []
    bottom_extent = document.height + 80.0
    for callout in document.callouts:
        max_chars = 22 if callout.side in {"left", "right"} else 32
        line_count = max(1, len(_wrap_svg_lines(callout.text, max_chars)))
        if callout.side in horizontal_heights:
            horizontal_heights[callout.side] += max(86, line_count * 20 + 26)
        else:
            horizontal_counts[callout.side] += 1
            if callout.side == "top":
                top_line_counts.append(line_count)
            else:
                bottom_extent = max(bottom_extent, document.height + 48 + (line_count - 1) * 20 + 40)
    horizontal_slots = max(horizontal_counts.values())
    horizontal_right = 30.0 + horizontal_slots * horizontal_slot_width if horizontal_slots else float(document.width)
    view_right = max(float(document.width + gutter), horizontal_right)
    view_width = view_right - view_x
    bottom_extent = max(bottom_extent, *(value + 30 for value in horizontal_heights.values()))
    view_top = min(-80.0, -48.0 - (max(top_line_counts, default=1) - 1) * 20.0 - 24.0)
    view_height = bottom_extent - view_top
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_x} {view_top:g} {view_width:g} {view_height:g}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(document.title)}</title>',
        '<desc id="desc">Deterministic annotated game UI wireframe generated by ui-ref.</desc>',
        "<style>",
        ".canvas{fill:#10151d;stroke:#8291a6;stroke-width:3}.panel{fill:#1d2734;stroke:#8291a6;stroke-width:2}.rect,.slot,.input,.toggle{fill:#263445;stroke:#9aabc0;stroke-width:2}.button{fill:#315168;stroke:#65d6c4;stroke-width:3}.image{fill:#202a36;stroke:#76869b;stroke-width:2;stroke-dasharray:10 8}.bar-bg{fill:#202a36;stroke:#8291a6;stroke-width:2}.bar-fill{fill:#55d6be}.label{fill:#f4f7fb;font:600 18px system-ui,sans-serif}.small{fill:#c8d1dd;font:500 14px system-ui,sans-serif}.id{fill:#0f141c;font:700 14px system-ui,sans-serif}.badge{fill:#f1c75b;stroke:#0f141c;stroke-width:2}.callout-line{stroke:#f1c75b;stroke-width:2;fill:none}.callout{fill:#f6e8bd;font:500 16px system-ui,sans-serif}.title{fill:#f6e8bd;font:700 24px system-ui,sans-serif}",
        "</style>",
        f'<rect class="canvas" x="0" y="0" width="{document.width}" height="{document.height}" rx="8"/>',
        f'<text class="title" x="0" y="-28">{escape(document.title)}</text>',
    ]
    for node in document.nodes:
        x, y, w, h = rects[node.node_id]
        label = node.attrs.get("label", node.node_id)
        if node.kind == "panel":
            parts.append(f'<rect class="panel" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12"/>')
        elif node.kind in {"rect", "slot", "input", "toggle"}:
            parts.append(f'<rect class="{node.kind}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8"/>')
        elif node.kind == "button":
            parts.append(f'<rect class="button" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12"/>')
        elif node.kind == "bar":
            try:
                value = max(0.0, min(1.0, float(node.attrs.get("value", "0.65"))))
            except ValueError:
                value = 0.65
            parts.append(f'<rect class="bar-bg" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{min(h / 2, 10):.1f}"/>')
            parts.append(f'<rect class="bar-fill" x="{x:.1f}" y="{y:.1f}" width="{w * value:.1f}" height="{h:.1f}" rx="{min(h / 2, 10):.1f}"/>')
        elif node.kind == "image":
            parts.append(f'<rect class="image" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4"/>')
            parts.append(f'<path class="image" d="M{x:.1f},{y + h:.1f} L{x + w * .35:.1f},{y + h * .48:.1f} L{x + w * .58:.1f},{y + h * .72:.1f} L{x + w:.1f},{y + h * .2:.1f}"/>')
        elif node.kind == "icon":
            parts.append(f'<circle class="rect" cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" r="{min(w, h) / 2:.1f}"/>')
        elif node.kind == "text":
            pass
        label_y = y + (h / 2) + 6
        parts.append(_svg_text_lines(label, x + w / 2, label_y, max(8, int(w / 10)), cls="label", anchor="middle"))
        badge_x, badge_y = x + 4, y + 4
        parts.append(f'<circle class="badge" cx="{badge_x + 12:.1f}" cy="{badge_y + 12:.1f}" r="12"/>')
        parts.append(f'<text class="id" text-anchor="middle" x="{badge_x + 12:.1f}" y="{badge_y + 17:.1f}">{escape(node.node_id)}</text>')

    counts = {"top": 0, "bottom": 0}
    side_offsets = {"left": 36.0, "right": 36.0}
    for callout in document.callouts:
        x, y, w, h = rects[callout.target]
        source_x, source_y = x + w / 2, y + h / 2
        if callout.side == "right":
            text_x, text_y, anchor = document.width + 42, side_offsets["right"], "start"
            elbow_x, elbow_y = document.width + 20, text_y - 6
            line_count = max(1, len(_wrap_svg_lines(callout.text, 22)))
            side_offsets["right"] += max(86, line_count * 20 + 26)
        elif callout.side == "left":
            text_x, text_y, anchor = -42, side_offsets["left"], "end"
            elbow_x, elbow_y = -20, text_y - 6
            line_count = max(1, len(_wrap_svg_lines(callout.text, 22)))
            side_offsets["left"] += max(86, line_count * 20 + 26)
        elif callout.side == "top":
            slot = counts["top"]
            counts["top"] += 1
            line_count = max(1, len(_wrap_svg_lines(callout.text, 32)))
            text_x, text_y, anchor = 30 + slot * horizontal_slot_width, -48 - (line_count - 1) * 20, "start"
            elbow_x, elbow_y = text_x, -20
        else:
            slot = counts["bottom"]
            counts["bottom"] += 1
            text_x, text_y, anchor = 30 + slot * horizontal_slot_width, document.height + 48, "start"
            elbow_x, elbow_y = text_x, document.height + 20
        parts.append(f'<path class="callout-line" d="M{source_x:.1f},{source_y:.1f} L{elbow_x:.1f},{elbow_y:.1f} L{text_x:.1f},{elbow_y:.1f}"/>')
        max_chars = 22 if callout.side in {"left", "right"} else 32
        parts.append(_svg_text_lines(callout.text, text_x, text_y, max_chars, cls="callout", anchor=anchor, max_lines=None))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _state_applicable(definition: Any, *, fallback: bool = True) -> bool:
    """Return whether a state definition should be rendered.

    ``applicable`` is canonical. ``visible`` remains supported for imported
    contracts so hidden resting-state elements do not leak into generated views.
    """
    if not isinstance(definition, dict):
        return fallback
    if isinstance(definition.get("applicable"), bool):
        return bool(definition["applicable"])
    if isinstance(definition.get("visible"), bool):
        return bool(definition["visible"])
    return fallback


def _element_applicable_for_scenario(element: dict[str, Any], scenario: str) -> bool:
    states = element.get("states") if isinstance(element.get("states"), dict) else {}
    if scenario in states:
        return _state_applicable(states[scenario])
    if "default" in states:
        return _state_applicable(states["default"])
    return True


def _rect_for_scenario(element: dict[str, Any], scenario: str) -> dict[str, Any]:
    """Return a complete absolute rect, applying an authored scenario override."""
    base = element.get("rect") if isinstance(element.get("rect"), dict) else {}
    result = dict(base)
    overrides = element.get("rect_overrides")
    if isinstance(overrides, dict):
        override = overrides.get(scenario)
        if isinstance(override, dict):
            result.update(override)
    return result


def _wireframe_from_screen(screen: dict[str, Any]) -> str:
    viewport = screen.get("viewport", {})
    try:
        width = int(viewport.get("width", 1920))
        height = int(viewport.get("height", 1080))
    except (TypeError, ValueError) as exc:
        raise ValueError("screen viewport width and height must be integers") from exc
    if width <= 0 or height <= 0 or width > 16384 or height > 16384:
        raise ValueError("screen viewport dimensions must be between 1 and 16384")
    scenario = str(screen.get("default_scenario") or "default")
    lines = ["uiwire 1", f'canvas {width} {height} title={json.dumps(str(screen.get("name", "Screen")), ensure_ascii=False)}']
    supported = {"panel", "rect", "text", "button", "bar", "image", "icon", "slot", "input", "toggle"}
    seen_ids: set[str] = set()
    all_elements = [element for element in screen.get("elements", []) if isinstance(element, dict)]
    element_by_id = {
        str(element.get("id")): element
        for element in all_elements
        if element.get("id")
    }

    visibility_cache: dict[str, bool] = {}

    def visible_in_default(element: dict[str, Any], trail: set[str] | None = None) -> bool:
        element_id = str(element.get("id", ""))
        if element_id in visibility_cache:
            return visibility_cache[element_id]
        if not _element_applicable_for_scenario(element, scenario):
            visibility_cache[element_id] = False
            return False
        parent_id = str(element.get("parent", ""))
        if parent_id:
            seen = set(trail or ())
            if element_id in seen:
                visibility_cache[element_id] = False
                return False
            seen.add(element_id)
            parent = element_by_id.get(parent_id)
            if isinstance(parent, dict) and not visible_in_default(parent, seen):
                visibility_cache[element_id] = False
                return False
        visibility_cache[element_id] = True
        return True

    for element in all_elements:
        if not isinstance(element, dict) or not element.get("id") or not isinstance(element.get("rect"), dict):
            continue
        if not visible_in_default(element):
            continue
        element_id = str(element["id"])
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", element_id):
            raise ValueError(f"cannot generate wireframe: invalid element ID {element_id!r}")
        if element_id in seen_ids:
            raise ValueError(f"cannot generate wireframe: duplicate element ID {element_id!r}")
        seen_ids.add(element_id)
        rect = _rect_for_scenario(element, scenario)
        values = [rect.get(key) for key in ("x", "y", "width", "height")]
        if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
            raise ValueError(f"cannot generate wireframe: {element_id} rect must contain finite numbers")
        if float(rect["width"]) <= 0 or float(rect["height"]) <= 0:
            raise ValueError(f"cannot generate wireframe: {element_id} width and height must be positive")
        kind = str(element.get("type", "rect"))
        if kind not in supported:
            kind = "rect"
        label = json.dumps(str(element.get("name", element_id)), ensure_ascii=False)
        parent_id = str(element.get("parent", ""))
        if parent_id and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", parent_id):
            raise ValueError(f"cannot generate wireframe: invalid parent ID {parent_id!r}")
        draw_x = float(rect["x"])
        draw_y = float(rect["y"])
        if parent_id:
            parent_element = element_by_id.get(parent_id)
            parent_rect = _rect_for_scenario(parent_element, scenario) if isinstance(parent_element, dict) else None
            if not isinstance(parent_rect, dict):
                raise ValueError(f"cannot generate wireframe: unknown parent ID {parent_id!r}")
            try:
                parent_x = float(parent_rect["x"])
                parent_y = float(parent_rect["y"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"cannot generate wireframe: parent {parent_id!r} needs numeric x and y") from exc
            if not math.isfinite(parent_x) or not math.isfinite(parent_y):
                raise ValueError(f"cannot generate wireframe: parent {parent_id!r} x and y must be finite")
            draw_x -= parent_x
            draw_y -= parent_y
        parent = f" parent={parent_id}" if parent_id else ""
        value = ""
        if kind == "bar":
            bar_value = element.get("value", 0.65)
            if not isinstance(bar_value, (int, float)) or not math.isfinite(float(bar_value)):
                raise ValueError(f"cannot generate wireframe: {element_id} bar value must be finite")
            value = f" value={float(bar_value):g}"
        lines.append(
            f"{kind} {element_id} x={draw_x:g} y={draw_y:g} "
            f"w={rect.get('width', 100)} h={rect.get('height', 60)} label={label}{parent}{value}"
        )
        intent = element.get("ux_intent") or element.get("description")
        if intent:
            lines.append(f"callout {element_id} side=right text={json.dumps(str(intent), ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def command_wireframe_new(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    screen_path = design_root / "screens" / f"{_portable_id(args.screen_id, 'screen')}.json"
    if not screen_path.exists():
        raise SystemExit(f"Screen contract not found: {screen_path}")
    screen = _read_json(screen_path)
    try:
        output = Path(args.output).resolve() if args.output else _resolve_design_path(
            design_root,
            str(screen.get("wireframe", f"wireframes/{screen['id']}.uiwire")),
            f"screen {screen.get('id')} wireframe",
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if output.exists() and not args.force:
        raise SystemExit(f"Wireframe already exists: {output}. Use --force to regenerate it from the contract.")
    try:
        source = _wireframe_from_screen(screen)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _write_text(output, source)
    print(f"Created AI-friendly wireframe source: {output}")
    return 0


def command_wireframe_lint(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    try:
        document = parse_uiwire(_read_text(path))
        _node_rects(document)
    except (OSError, ValueError) as exc:
        print(f"ERROR {path}: {exc}")
        return 1
    print(f"Valid uiwire v{document.version}: {len(document.nodes)} element(s), {len(document.callouts)} callout(s).")
    return 0


def command_wireframe_render(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    try:
        document = parse_uiwire(_read_text(path))
        svg = render_uiwire_svg(document)
    except (OSError, ValueError) as exc:
        print(f"ERROR {path}: {exc}")
        return 1
    output = Path(args.output).resolve() if args.output else path.with_suffix(".svg")
    if output.exists() and not args.force:
        raise SystemExit(f"Output exists: {output}. Use --force to replace it.")
    _write_text(output, svg)
    print(f"Rendered wireframe SVG: {output}")
    return 0


def compile_design_ir(
    design_root: Path,
    *,
    require_valid: bool = True,
    project_root: Path | None = None,
) -> dict[str, Any]:
    issues, summary = validate_design_workspace(design_root, strict=False, project_root=project_root)
    errors = [item for item in issues if item.severity == "error"]
    if errors and require_valid:
        first = errors[0]
        raise ValueError(f"[{first.code}] {first.path}: {first.message}")
    source_paths = [
        design_root / "project.json",
        design_root / "tokens.json",
        design_root / "flows.json",
        design_root / "references.json",
        design_root / "decisions.json",
        design_root / "approvals.json",
        *_json_files(design_root / "screens"),
        *_json_files(design_root / "components"),
    ]
    source_paths.extend(sorted((design_root / "wireframes").glob("*.uiwire")))
    hashes = {_rel(design_root, path): _sha256(path) for path in source_paths if path.exists()}
    return {
        "ir_version": DESIGN_SCHEMA_VERSION,
        "compiled_at": _now(),
        "project": _read_json(design_root / "project.json"),
        "tokens": _read_json(design_root / "tokens.json"),
        "flows": _read_json(design_root / "flows.json"),
        "references": _read_json(design_root / "references.json"),
        "decisions": _read_json(design_root / "decisions.json"),
        "approvals": _read_json(design_root / "approvals.json"),
        "screens": [_read_json(path) for path in _json_files(design_root / "screens")],
        "components": [_read_json(path) for path in _json_files(design_root / "components")],
        "validation": {**summary, "issues": [item.as_dict() for item in issues]},
        "source_hashes": hashes,
    }


def command_design_compile(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    try:
        ir = compile_design_ir(design_root, project_root=_project_root(args))
    except ValueError as exc:
        print(f"ERROR Cannot compile invalid contracts: {exc}")
        return 1
    output = Path(args.output).resolve() if args.output else design_root / "build" / "design.ir.json"
    if output.exists() and not args.force:
        raise SystemExit(f"Output exists: {output}. Use --force to replace it.")
    _write_json(output, ir)
    print(f"Compiled canonical design IR: {output}")
    return 0


def _markdown_table(headers: list[str], rows: Iterable[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _markdown_reference_path(uri: Any, reference_prefix: str) -> str:
    raw = str(uri or "").replace("\\", "/").strip()
    parsed = urlparse(raw)
    if not raw or parsed.scheme or raw.startswith("/") or ".." in Path(raw).parts:
        return ""
    combined = f"{reference_prefix.rstrip('/')}/{raw.lstrip('/')}" if reference_prefix else raw
    return quote(combined, safe="/._-~")


def _safe_web_link(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    return raw if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _criterion_text(value: Any) -> str:
    if isinstance(value, dict):
        return f"Given {value.get('given', '')}; When {value.get('when', '')}; Then {value.get('then', '')}"
    return str(value)


def _token_rows(tokens: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict) and "value" in value:
            rows.append([prefix, _compact_json(value.get("value")), str(value.get("source", "unrecorded"))])
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in {"schema_version", "kind", "status", "notes", "source"}:
                    walk(f"{prefix}.{key}" if prefix else str(key), child)
            return
        rows.append([prefix, _compact_json(value), "unrecorded"])

    walk("", tokens)
    return [row for row in rows if row[0]]


def design_ir_markdown(ir: dict[str, Any], reference_prefix: str = "") -> str:
    project = ir["project"].get("project", {})
    refs = [item for item in ir["references"].get("sources", []) if isinstance(item, dict)]
    ref_map = {str(item.get("id")): item for item in refs if item.get("id")}
    lines = [
        f"# {project.get('name', 'Game')} — UX/UI Design Contract",
        "",
        f"Contract version: `{ir['ir_version']}`  ",
        f"Compiled: `{ir['compiled_at']}`  ",
        f"Project status: **{project.get('status', 'draft')}**  ",
        f"Platforms: {', '.join(project.get('platforms', [])) or 'unspecified'}  ",
        f"Input devices: {', '.join(project.get('input_devices', [])) or 'unspecified'}  ",
        f"Aspect ratios: {', '.join(project.get('aspect_ratios', [])) or 'unspecified'}  ",
        f"Default locale: `{project.get('default_locale', 'unspecified')}`",
        "",
        "> Generated from validated JSON contracts. Edit `ui_design/` contracts, then rebuild; do not edit this file.",
        "",
        "## Player-facing intent",
        "",
        project.get("intent", "") or "_Not authored yet._",
        "",
        "## Screen map",
        "",
        _markdown_table(
            ["ID", "Screen", "Revision", "Status", "Purpose", "Evidence", "Open questions"],
            (
                [screen.get("id"), screen.get("name"), screen.get("revision"), screen.get("status"), screen.get("purpose"), len(screen.get("reference_ids", [])), len(screen.get("open_questions", []))]
                for screen in ir["screens"]
            ),
        ),
        "",
        "## Flows",
        "",
    ]
    flows = ir.get("flows", {}).get("flows", [])
    if flows:
        lines.append(_markdown_table(
            ["ID", "Entry screen", "Steps"],
            ([item.get("id"), item.get("entry_screen"), len(item.get("steps", []))] for item in flows if isinstance(item, dict)),
        ))
    else:
        lines.append("No flows authored yet.")
    lines.append("")
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        flow_id = str(flow.get("id", "flow"))
        lines.extend([f"### Flow `{flow_id}`", "", f"Entry screen: `{flow.get('entry_screen', '')}`", ""])
        steps = [item for item in flow.get("steps", []) or [] if isinstance(item, dict)]
        if steps:
            lines.extend([_markdown_table(
                ["Step", "Screen", "Action", "Next screen", "Condition", "Recovery"],
                ([index, item.get("screen"), item.get("action", item.get("action_id")), item.get("next_screen"), item.get("condition"), item.get("recovery")] for index, item in enumerate(steps, start=1)),
            ), ""])
        else:
            lines.extend(["No steps authored.", ""])

    token_document = ir.get("tokens", {}) if isinstance(ir.get("tokens"), dict) else {}
    lines.extend(["## Design tokens", ""])
    token_rows = _token_rows(token_document)
    if token_rows:
        lines.extend([_markdown_table(["Token", "Value", "Source"], token_rows), ""])
    else:
        lines.extend(["No tokens authored yet.", ""])
    for note in token_document.get("notes", []) or []:
        lines.append(f"- Token note: {note}")
    if token_document.get("notes"):
        lines.append("")

    for screen in ir["screens"]:
        screen_id = str(screen.get("id", "screen"))
        lines.extend(
            [
                f"## {screen.get('name', screen_id)} (`{screen_id}`)",
                "",
                f"Status: **{screen.get('status', 'draft')}**, revision `{screen.get('revision', '?')}`  ",
                f"Purpose: {screen.get('purpose') or '_Not authored yet_'}  ",
                f"Player goal: {screen.get('player_goal') or '_Not authored yet_'}",
                "",
                "### Entry, exit, and recovery",
                "",
            ]
        )
        for item in screen.get("entry_conditions", []) or []:
            lines.append(f"- Entry: {_compact_json(item) if isinstance(item, dict) else item}")
        if screen.get("entry_exception"):
            lines.append(f"- Entry exception: {screen['entry_exception']}")
        for item in screen.get("exit_paths", []) or []:
            if isinstance(item, dict):
                lines.append(f"- Exit `{item.get('action', item.get('action_id', 'action'))}` → `{item.get('target_screen', 'outcome')}`")
            else:
                lines.append(f"- Exit: {item}")
        if screen.get("exit_exception"):
            lines.append(f"- Exit exception: {screen['exit_exception']}")
        for item in screen.get("edge_cases", []) or []:
            lines.append(f"- Edge case: {item if isinstance(item, str) else item.get('description', _compact_json(item))}")
        if screen.get("edge_case_exception"):
            lines.append(f"- Edge-case exception: {screen['edge_case_exception']}")
        lines.append("")

        evidence_ids: set[str] = set(str(value) for value in screen.get("reference_ids", []) or [])
        for element in screen.get("elements", []) or []:
            if isinstance(element, dict):
                evidence_ids.update(str(value) for value in element.get("reference_ids", []) or [])
        lines.extend(["### Evidence used by this screen", ""])
        if not evidence_ids:
            lines.append(f"Evidence exception: {screen.get('evidence_exception', '_No evidence or exception recorded._')}")
        for ref_id in sorted(evidence_ids):
            ref = ref_map.get(ref_id)
            if not ref:
                lines.append(f"- Missing evidence record: `{ref_id}`")
                continue
            title = str(ref.get("title") or ref_id)
            lines.append(f"#### {title} (`{ref_id}`)")
            lines.append("")
            display_path = _markdown_reference_path(ref.get("uri"), reference_prefix)
            suffix = Path(str(ref.get("uri", ""))).suffix.lower()
            if display_path and suffix in ANALYSIS_IMAGE_EXTS:
                alt = title.replace("[", "(").replace("]", ")")
                lines.extend([f"![{alt}]({display_path})", ""])
            source_url = _safe_web_link(ref.get("source_url"))
            if source_url:
                encoded_source = quote(source_url, safe=":/?#[]@!$&'*+,;=%~-._")
                lines.append(f"Source: [original source]({encoded_source})  ")
            lines.append(f"Local evidence: `{ref.get('uri', '')}` · SHA-256 `{ref.get('sha256', '') or 'unavailable'}`  ")
            lines.append(f"Rights/usage: {ref.get('rights', 'unverified')} · Sync: {ref.get('sync_state', 'unknown')}")
            for note in ref.get("evidence_notes", []) or []:
                lines.append(f"- Evidence note: {note if isinstance(note, str) else _compact_json(note)}")
            if ref.get("annotation"):
                lines.append(f"- Human annotation: {ref['annotation']}")
            lines.append("")

        if screen.get("wireframe"):
            lines.extend(["### Annotated wireframe", "", f"![{screen.get('name', 'screen')} annotated wireframe](wireframes/{screen_id}.svg)", ""])

        elements = [item for item in screen.get("elements", []) if isinstance(item, dict)]
        lines.extend(
            [
                "### Element inventory",
                "",
                _markdown_table(
                    ["ID", "Element", "Type", "Rect", "UX intent", "Bindings", "Inputs", "Evidence"],
                    (
                        [
                            element.get("id"),
                            element.get("name"),
                            element.get("type"),
                            "{x},{y} {width}×{height}".format(**element.get("rect", {"x": "?", "y": "?", "width": "?", "height": "?"})),
                            element.get("ux_intent", ""),
                            ", ".join(str(binding.get("path", "")) for binding in element.get("data_bindings", []) if isinstance(binding, dict)),
                            ", ".join(str(action.get("input", "")) for action in element.get("interactions", []) if isinstance(action, dict)),
                            ", ".join(str(value) for value in element.get("reference_ids", []) or []),
                        ]
                        for element in elements
                    ),
                ),
                "",
            ]
        )
        for element in elements:
            element_id = str(element.get("id", "element"))
            lines.extend([f"#### `{element_id}` — {element.get('name', element_id)}", ""])
            if element.get("ux_intent"):
                lines.extend([f"UX intent: {element['ux_intent']}", ""])
            states = element.get("states", {}) if isinstance(element.get("states"), dict) else {}
            lines.extend(["States:", "", _markdown_table(["State", "Definition"], ([name, _compact_json(value)] for name, value in states.items())), ""])
            interactions = [item for item in element.get("interactions", []) or [] if isinstance(item, dict)]
            if interactions:
                lines.extend(["Interactions:", "", _markdown_table(
                    ["Input", "Action", "Target", "Devices"],
                    ([item.get("input"), item.get("action"), item.get("target_screen"), ", ".join(item.get("devices", []))] for item in interactions),
                ), ""])
            bindings = [item for item in element.get("data_bindings", []) or [] if isinstance(item, dict)]
            if bindings:
                lines.extend(["Data bindings:", "", _markdown_table(
                    ["Path", "Source", "Assumption", "Format", "Fallback"],
                    ([item.get("path"), item.get("source"), item.get("assumption"), item.get("format"), item.get("fallback")] for item in bindings),
                ), ""])
            lines.extend([f"Accessibility: `{_compact_json(element.get('accessibility', {}))}`", "", "Acceptance:", ""])
            for criterion in element.get("acceptance", []) or []:
                lines.append(f"- {_criterion_text(criterion)}")
            if not element.get("acceptance"):
                lines.append("- _Not authored yet._")
            lines.append("")

        if screen.get("analysis_claims"):
            lines.extend(["### Reverse-engineering claims", "", _markdown_table(
                ["Classification", "Claim", "Confidence", "Evidence"],
                ([item.get("classification"), item.get("claim"), item.get("confidence"), ", ".join(item.get("evidence_ids", []))] for item in screen.get("analysis_claims", []) if isinstance(item, dict)),
            ), ""])
        lines.extend(["### Open questions and provenance", ""])
        for question in screen.get("open_questions", []) or []:
            lines.append(f"- Open: {question if isinstance(question, str) else _compact_json(question)}")
        if not screen.get("open_questions"):
            lines.append("- No open questions recorded.")
        provenance = screen.get("provenance", {})
        lines.extend([f"- Provenance: `{_compact_json(provenance)}`", ""])

    lines.extend(["## Components", ""])
    components = ir["components"]
    if components:
        lines.append(_markdown_table(
            ["ID", "Component", "Revision", "Status", "Purpose", "States", "Acceptance"],
            ([item.get("id"), item.get("name"), item.get("revision"), item.get("status"), item.get("purpose"), ", ".join(item.get("states", {}).keys()), len(item.get("acceptance", []))] for item in components),
        ))
    else:
        lines.append("No reusable components authored yet.")
    lines.append("")
    for component in components:
        if not isinstance(component, dict):
            continue
        component_id = str(component.get("id", "component"))
        lines.extend(
            [
                f"### {component.get('name', component_id)} (`{component_id}`)",
                "",
                f"Status: **{component.get('status', 'draft')}**, revision `{component.get('revision', '?')}`  ",
                f"Purpose: {component.get('purpose') or '_Not authored yet_'}",
                "",
                "States:",
                "",
                _markdown_table(
                    ["State", "Definition"],
                    ([name, _compact_json(value)] for name, value in (component.get("states", {}) if isinstance(component.get("states"), dict) else {}).items()),
                ),
                "",
            ]
        )
        inputs = [item for item in component.get("inputs", []) or [] if isinstance(item, dict)]
        if inputs:
            lines.extend(["Inputs:", "", _markdown_table(
                ["Input", "Action", "Devices", "Target"],
                ([item.get("input"), item.get("action"), ", ".join(item.get("devices", [])), item.get("target_screen")] for item in inputs),
            ), ""])
        lines.extend(
            [
                f"Accessibility: `{_compact_json(component.get('accessibility', {}))}`  ",
                f"Evidence: {', '.join(str(value) for value in component.get('reference_ids', []) or []) or '_none_'}",
                "",
                "Acceptance:",
                "",
            ]
        )
        for criterion in component.get("acceptance", []) or []:
            lines.append(f"- {_criterion_text(criterion)}")
        if not component.get("acceptance"):
            lines.append("- _Not authored yet._")
        lines.extend(["", f"Provenance: `{_compact_json(component.get('provenance', {}))}`", ""])

    lines.extend(["", "## Decisions", ""])
    decisions = ir["decisions"].get("decisions", [])
    if decisions:
        lines.append(_markdown_table(
            ["ID", "Status", "Decision", "Rationale", "Author"],
            ([item.get("id"), item.get("status"), item.get("statement"), item.get("rationale"), item.get("author")] for item in decisions),
        ))
    else:
        lines.append("No decisions recorded.")

    lines.extend(["", "## Approval ledger", ""])
    approvals = ir["approvals"].get("approvals", [])
    if approvals:
        lines.append(_markdown_table(
            ["Artifact", "Revision", "Status", "Actor", "Actor type", "Recorded", "Content hash"],
            ([f"{item.get('artifact_kind')}:{item.get('artifact_id')}", item.get("revision"), item.get("status"), item.get("actor"), item.get("actor_type"), item.get("recorded_at"), item.get("content_sha256")] for item in approvals if isinstance(item, dict)),
        ))
    else:
        lines.append("No reviews or approvals recorded.")

    lines.extend(["", "## Evidence catalog", ""])
    if refs:
        lines.append(_markdown_table(
            ["ID", "Title", "Type", "URI", "Source URL", "SHA-256", "Rights", "Sync"],
            ([item.get("id"), item.get("title"), item.get("source_type"), item.get("uri"), item.get("source_url"), item.get("sha256"), item.get("rights"), item.get("sync_state")] for item in refs),
        ))
    else:
        lines.append("No evidence records.")
    lines.extend(["", "## Reproducibility", ""])
    lines.append(_markdown_table(["Canonical input", "SHA-256"], sorted(ir.get("source_hashes", {}).items())))
    lines.append("")
    return "\n".join(lines)


def design_ir_html(ir: dict[str, Any], markdown: str, reference_prefix: str = "") -> str:
    """Produce a standalone readable view without a Markdown dependency."""
    project = ir["project"].get("project", {})
    refs = {str(item.get("id")): item for item in ir["references"].get("sources", []) if isinstance(item, dict) and item.get("id")}
    screen_cards: list[str] = []
    for screen in ir["screens"]:
        rows = []
        evidence_ids: set[str] = set(str(value) for value in screen.get("reference_ids", []) or [])
        for element in screen.get("elements", []):
            rect = element.get("rect", {})
            evidence_ids.update(str(value) for value in element.get("reference_ids", []) or [])
            rows.append(
                "<tr>"
                f"<td><code>{escape(str(element.get('id', '')))}</code></td>"
                f"<td>{escape(str(element.get('name', '')))}</td>"
                f"<td>{escape(str(element.get('type', '')))}</td>"
                f"<td>{escape(str(rect.get('x', '?')))}, {escape(str(rect.get('y', '?')))} · {escape(str(rect.get('width', '?')))}×{escape(str(rect.get('height', '?')))}</td>"
                f"<td>{escape(', '.join(str(item.get('path', '')) for item in element.get('data_bindings', [])))}</td>"
                f"<td>{escape(', '.join(str(item.get('input', '')) for item in element.get('interactions', [])))}</td>"
                f"<td>{escape(str(element.get('ux_intent', '')))}</td>"
                "</tr>"
            )
        wireframe = f'<img src="wireframes/{escape(str(screen.get("id")))}.svg" alt="annotated wireframe">' if screen.get("wireframe") else ""
        evidence_cards: list[str] = []
        for ref_id in sorted(evidence_ids):
            ref = refs.get(ref_id)
            if not ref:
                evidence_cards.append(f'<p class="warning">Missing evidence: <code>{escape(ref_id)}</code></p>')
                continue
            path = _markdown_reference_path(ref.get("uri"), reference_prefix)
            suffix = Path(str(ref.get("uri", ""))).suffix.lower()
            image = f'<img src="{escape(path, quote=True)}" alt="{escape(str(ref.get("title", ref_id)), quote=True)}">' if path and suffix in ANALYSIS_IMAGE_EXTS else ""
            source_url = _safe_web_link(ref.get("source_url"))
            source = f'<a href="{escape(source_url, quote=True)}">source</a>' if source_url else "source unverified"
            evidence_cards.append(
                f'<figure>{image}<figcaption><code>{escape(ref_id)}</code> · {escape(str(ref.get("title", "")))} · {source}<br>'
                f'SHA-256 {escape(str(ref.get("sha256", "unavailable")))}</figcaption></figure>'
            )
        screen_cards.append(
            f'<section id="screen-{escape(str(screen.get("id")))}"><h2>{escape(str(screen.get("name", screen.get("id"))))}</h2>'
            f'<p class="status">{escape(str(screen.get("status", "draft")))} · revision {escape(str(screen.get("revision", "?")))}</p>'
            f'<p>{escape(str(screen.get("purpose") or "Purpose not authored yet."))}</p>'
            f'<p><strong>Player goal:</strong> {escape(str(screen.get("player_goal") or "Not authored yet."))}</p>'
            f'<div class="evidence">{"".join(evidence_cards)}</div>{wireframe}'
            '<table><thead><tr><th>ID</th><th>Element</th><th>Type</th><th>Rect</th><th>Binding</th><th>Input</th><th>UX intent</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><details><summary>Canonical screen JSON</summary><pre>{escape(_compact_json(screen))}</pre></details></section>'
        )
    raw_json = escape(json.dumps(ir, ensure_ascii=False))
    locale = str(project.get("default_locale", "en") or "en")
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*", locale):
        locale = "en"
    locale = locale.replace("_", "-")
    return f'''<!doctype html>
<html lang="{escape(locale, quote=True)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' data:; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'none'">
<title>{escape(str(project.get('name', 'Game')))} UX/UI Design Contract</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;margin:0;background:#10151d;color:#edf2f7}}main{{max-width:1400px;margin:auto;padding:32px}}h1,h2{{color:#f1c75b}}section{{margin:28px 0;padding:24px;background:#19222e;border:1px solid #35465a;border-radius:14px}}img{{max-width:100%;background:#0c1118;border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:9px;border-bottom:1px solid #344457;text-align:left;vertical-align:top}}code{{color:#68dbc8}}a{{color:#65d6c4}}.status{{display:inline-block;padding:3px 9px;border-radius:999px;background:#2c5365}}.evidence{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:18px 0}}figure{{margin:0;padding:10px;background:#111923;border:1px solid #35465a;border-radius:9px}}figure img{{width:100%}}figcaption{{padding-top:8px;font-size:13px;word-break:break-word}}.warning{{color:#ffb3bd}}details{{margin-top:30px}}pre{{white-space:pre-wrap;word-break:break-word}}</style></head>
<body><main><h1>{escape(str(project.get('name', 'Game')))} — UX/UI Design Contract</h1>
<p>Generated from validated, evidence-linked contracts on {escape(ir['compiled_at'])}.</p>
{''.join(screen_cards)}
<details><summary>Canonical compiled JSON</summary><pre>{raw_json}</pre></details></main></body></html>
'''


def _render_ir_wireframes(ir: dict[str, Any], design_root: Path, output_directory: Path) -> list[str]:
    rendered: list[str] = []
    for screen in ir["screens"]:
        value = screen.get("wireframe")
        if not value:
            continue
        source_path = _resolve_design_path(design_root, str(value), f"screen {screen.get('id')} wireframe")
        if not source_path.exists():
            continue
        try:
            document = parse_uiwire(_read_text(source_path))
            target = output_directory / f"{screen['id']}.svg"
            _write_text(target, render_uiwire_svg(document))
            rendered.append(target.name)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot render {source_path}: {exc}") from exc
    return rendered


def command_design_build(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    output_root = Path(args.output).resolve() if args.output else design_root / "build"
    if output_root.exists() or output_root.is_symlink():
        if not output_root.is_dir() or output_root.is_symlink():
            print(f"ERROR Refusing to replace a non-directory build output path: {output_root}")
            return 1
        if args.output and any(output_root.iterdir()) and not args.force:
            raise SystemExit(f"Build directory is not empty: {output_root}. Use --force to refresh generated files.")
    output_root.mkdir(parents=True, exist_ok=True)
    wireframe_stage = Path(tempfile.mkdtemp(prefix=".wireframes.stage-", dir=str(output_root)))
    try:
        ir = compile_design_ir(design_root, project_root=_project_root(args))
        rendered_names = _render_ir_wireframes(ir, design_root, wireframe_stage)
    except (OSError, ValueError) as exc:
        if wireframe_stage.exists() and wireframe_stage.resolve().parent == output_root.resolve():
            shutil.rmtree(wireframe_stage)
        print(f"ERROR Cannot build: {exc}")
        return 1
    try:
        reference_prefix = os.path.relpath(str(_project_root(args)), str(output_root)).replace("\\", "/")
    except ValueError:
        reference_prefix = ""
        print("WARNING Reference images are on a different filesystem root and cannot be embedded portably in this build.")
    markdown = design_ir_markdown(ir, reference_prefix=reference_prefix)
    html = design_ir_html(ir, markdown, reference_prefix=reference_prefix)
    _write_json(output_root / "design.ir.json", ir)
    _write_text(output_root / "design-spec.md", markdown)
    _write_text(output_root / "design-spec.html", html)
    try:
        _replace_generated_directory(wireframe_stage, output_root / "wireframes")
    except (OSError, ValueError) as exc:
        print(f"ERROR Cannot replace generated wireframes; prior output was preserved: {exc}")
        return 1
    rendered = [str(output_root / "wireframes" / name) for name in rendered_names]
    manifest = {
        "build_version": DESIGN_SCHEMA_VERSION,
        "built_at": ir["compiled_at"],
        "source_hashes": ir["source_hashes"],
        "outputs": {},
    }
    build_outputs = [output_root / "design.ir.json", output_root / "design-spec.md", output_root / "design-spec.html"]
    build_outputs.extend(Path(value) for value in rendered)
    for path in sorted(build_outputs):
        if path.is_file():
            manifest["outputs"][_rel(output_root, path)] = _sha256(path)
    _write_json(output_root / "build-manifest.json", manifest)
    print(f"Built design specification: {output_root / 'design-spec.md'}")
    print(f"Readable HTML: {output_root / 'design-spec.html'}")
    print(f"Rendered wireframes: {len(rendered)}")
    return 0


def _find_artifact(design_root: Path, kind: str, artifact_id: str) -> Path:
    folder = "screens" if kind == "screen" else "components"
    path = design_root / folder / f"{_portable_id(artifact_id, kind)}.json"
    if not path.exists():
        raise SystemExit(f"{kind.title()} contract not found: {path}")
    return path


def _candidate_errors(design_root: Path, path: Path, candidate: dict[str, Any], project_root: Path) -> list[ValidationIssue]:
    workspace_issues, _ = validate_design_workspace(design_root, strict=False, project_root=project_root)
    issues = [item for item in workspace_issues if item.severity == "error"]
    try:
        references = _read_json(design_root / "references.json")
        known_refs = {
            str(item.get("id")) for item in references.get("sources", [])
            if isinstance(item, dict) and item.get("id")
        }
        unavailable_refs = set()
        for item in references.get("sources", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            actual_state = _reference_actual_state(item, project_root)
            if item.get("sync_state") in {"missing", "invalid_path", "hash_mismatch"} or actual_state in {"missing", "invalid_path", "hash_mismatch", "hash_missing", "unsupported_type"}:
                unavailable_refs.add(str(item["id"]))
    except (OSError, json.JSONDecodeError, AttributeError):
        known_refs = set()
        unavailable_refs = set()
    known_screens = {
        str(data.get("id"))
        for screen_path in _json_files(design_root / "screens")
        for data in [_read_json(screen_path)]
        if isinstance(data, dict) and data.get("id")
    }
    screen_scenarios: dict[str, set[str]] = {}
    for screen_path in _json_files(design_root / "screens"):
        data = _read_json(screen_path)
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            screen_scenarios[str(data["id"])] = _screen_scenario_names(data)
    candidate_id = candidate.get("id")
    if isinstance(candidate_id, str):
        known_screens.add(candidate_id)
        screen_scenarios[candidate_id] = _screen_scenario_names(candidate)
    try:
        project = _read_json(design_root / "project.json")
        project_meta = project.get("project", {}) if isinstance(project, dict) and isinstance(project.get("project"), dict) else {}
        required_inputs = {str(value) for value in project_meta.get("input_devices", []) if isinstance(value, str) and value}
        raw_quality_gates = project.get("quality_gates", {}) if isinstance(project, dict) else {}
        if not isinstance(raw_quality_gates, dict):
            raw_quality_gates = {}
        quality_gates = {
            gate_name: raw_quality_gates.get(gate_name, default)
            if isinstance(raw_quality_gates.get(gate_name, default), bool)
            else default
            for gate_name, default in QUALITY_GATE_DEFAULTS.items()
        }
    except (OSError, json.JSONDecodeError):
        required_inputs = set()
        quality_gates = {}
    component_statuses = {
        str(data.get("id")): str(data.get("status", ""))
        for component_path in _json_files(design_root / "components")
        for data in [_read_json(component_path)]
        if isinstance(data, dict) and data.get("id")
    }
    if candidate.get("kind") == "screen":
        _validate_screen(path, candidate, known_refs, unavailable_refs, known_screens, screen_scenarios, component_statuses, required_inputs, quality_gates, issues, True)
    else:
        _validate_component(path, candidate, known_refs, unavailable_refs, required_inputs, quality_gates, issues, True)
    unique: list[ValidationIssue] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in issues:
        key = (item.severity, item.code, item.path, item.message)
        if item.severity == "error" and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def command_design_transition(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    actor = str(args.by or "").strip()
    note = str(args.note or "").strip()
    if not actor:
        raise SystemExit("--by must name the human or agent responsible for the lifecycle transition.")
    if not note:
        raise SystemExit("--note must explain the lifecycle transition.")
    path = _find_artifact(design_root, args.kind, args.artifact_id)
    contract = _read_json(path)
    current = contract.get("status", "draft")
    target = args.to
    if current not in ALLOWED_TRANSITIONS or target not in ALLOWED_TRANSITIONS[current]:
        raise SystemExit(f"Invalid status transition: {current} -> {target}")
    if target == "approved" and not args.human_confirmed:
        raise SystemExit("Final approval is human-owned. Re-run with --human-confirmed after the named reviewer approves this revision.")

    approvals_path = design_root / "approvals.json"
    decisions_path = design_root / "decisions.json"
    try:
        approval_document = _read_json(approvals_path)
        decisions = _read_json(decisions_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR Lifecycle ledgers are invalid; no files were changed: {exc}")
        return 1
    if (
        not isinstance(approval_document, dict)
        or approval_document.get("kind") != "approvals"
        or not isinstance(approval_document.get("approvals"), list)
        or not isinstance(decisions, dict)
        or decisions.get("kind") != "decisions"
        or not isinstance(decisions.get("decisions"), list)
    ):
        print("ERROR Lifecycle ledgers have an invalid root shape; no files were changed.")
        return 1
    if target in {"reviewed", "approved"}:
        candidate = json.loads(json.dumps(contract))
        candidate["status"] = target
        candidate["revision"] = int(candidate.get("revision", 0)) + 1
        errors = _candidate_errors(design_root, path, candidate, _project_root(args))
        if errors:
            for item in errors:
                print(f"ERROR [{item.code}] {item.path}: {item.message}")
            print("Status was not changed because the artifact does not satisfy the review gate.")
            return 1
    else:
        candidate = json.loads(json.dumps(contract))
        candidate["status"] = target
        candidate["revision"] = int(candidate.get("revision", 0)) + 1

    transition = {
        "from": current,
        "to": target,
        "revision": candidate["revision"],
        "actor": actor,
        "actor_type": "human" if args.human_confirmed else "agent",
        "at": _now(),
        "note": note,
    }
    candidate.setdefault("review_history", []).append(transition)
    content_hash = hashlib.sha256(_json_text(candidate).encode("utf-8")).hexdigest()

    existing_approval_ids = {
        str(item.get("id")) for item in approval_document["approvals"] if isinstance(item, dict) and item.get("id")
    }
    approval_number = len(approval_document["approvals"]) + 1
    while f"approval-{approval_number:04d}" in existing_approval_ids:
        approval_number += 1
    ledger_entry = {
        "id": f"approval-{approval_number:04d}",
        "artifact_kind": args.kind,
        "artifact_id": candidate.get("id"),
        "revision": candidate["revision"],
        "status": target,
        "actor": actor,
        "actor_type": transition["actor_type"],
        "recorded_at": transition["at"],
        "note": note,
        "content_sha256": content_hash,
        "dependency_sha256": _dependency_snapshot(design_root, candidate),
    }
    approval_document["approvals"].append(ledger_entry)

    existing_decision_ids = {
        str(item.get("id")) for item in decisions["decisions"] if isinstance(item, dict) and item.get("id")
    }
    decision_number = len(decisions["decisions"]) + 1
    while f"decision-{decision_number:04d}" in existing_decision_ids:
        decision_number += 1
    decisions["decisions"].append(
        {
            "id": f"decision-{decision_number:04d}",
            "status": "locked" if target == "approved" else "recorded",
            "statement": f"{args.kind} {candidate.get('id')} revision {candidate['revision']}: {current} -> {target}",
            "rationale": note,
            "author": actor,
            "created_at": transition["at"],
            "source_refs": [],
        }
    )
    try:
        _write_json_transaction([(path, candidate), (approvals_path, approval_document), (decisions_path, decisions)])
    except (OSError, ValueError) as exc:
        print(f"ERROR Lifecycle update could not be committed; original files were restored: {exc}")
        return 1
    print(f"Transitioned {args.kind} {candidate.get('id')}: {current} -> {target} (revision {candidate['revision']})")
    print(f"Content hash: {content_hash}")
    return 0


def _element_target(element: dict[str, Any]) -> str:
    for interaction in element.get("interactions", []) or []:
        if isinstance(interaction, dict) and interaction.get("target_screen"):
            return str(interaction["target_screen"])
    return ""


def _prototype_screen(
    screen: dict[str, Any],
    screen_ids: set[str],
    authored_flow_actions: list[dict[str, Any]] | None = None,
) -> str:
    viewport = screen.get("viewport", {})
    width = float(viewport.get("width", 1920) or 1920)
    height = float(viewport.get("height", 1080) or 1080)
    default_scenario = str(screen.get("default_scenario") or "default")
    elements = [item for item in screen.get("elements", []) if isinstance(item, dict)]
    element_map = {str(item.get("id")): item for item in elements if item.get("id")}

    def layer_depth(element: dict[str, Any]) -> int:
        depth = 0
        parent = element.get("parent")
        visited: set[str] = set()
        while isinstance(parent, str) and parent in element_map and parent not in visited:
            visited.add(parent)
            depth += 1
            parent = element_map[parent].get("parent")
        return depth

    # Containers must paint before their children. Authors may add a small
    # explicit z_index for overlays that intentionally sit above later peers.
    # Keyboard order remains independent via focus_order.
    source_order = {id(item): index for index, item in enumerate(elements)}
    def visual_z(element: dict[str, Any]) -> int:
        authored = element.get("z_index", 0)
        return layer_depth(element) + (authored if isinstance(authored, int) and not isinstance(authored, bool) else 0)

    elements.sort(key=lambda item: (visual_z(item), source_order[id(item)]))

    def navigation_interactions(item: dict[str, Any], target: str, label: str) -> list[dict[str, Any]]:
        """Prefer the screen control contract over a looser navigation summary.

        Exit paths and flow steps are useful traceability summaries, but the
        element interaction is the source of truth for role/scenario/mode
        gates. Reusing it prevents prototype-only navigation controls from
        bypassing the same authority rules as the visible UI.
        """
        action = str(item.get("action") or item.get("action_id") or label)
        matching: list[dict[str, Any]] = []
        for element in elements:
            for interaction in element.get("interactions", []) or []:
                if not isinstance(interaction, dict):
                    continue
                interaction_action = str(interaction.get("action") or interaction.get("action_id") or "")
                interaction_target = str(interaction.get("target_screen") or "")
                if interaction_action == action and interaction_target == target:
                    routed = dict(interaction)
                    routed["_source_element"] = str(element.get("id") or "")
                    matching.append(routed)
        if matching:
            return matching
        if not item.get("flow_id"):
            for flow_item in authored_flow_actions or []:
                flow_action = str(flow_item.get("action") or flow_item.get("action_id") or flow_item.get("label") or "")
                flow_target = str(flow_item.get("target") or "")
                if flow_action != action or flow_target != target:
                    continue
                route: dict[str, Any] = {"action": flow_action, "target_screen": flow_target}
                for key in ("target_scenario", "target_scenario_by_mode", "source_scenarios", "source_modes", "restore_history", "_source_contexts"):
                    value = flow_item.get(key)
                    if value not in (None, "", [], {}):
                        route[key] = value
                matching.append(route)
        if matching:
            return matching
        interaction: dict[str, Any] = {"action": action, "target_screen": target}
        for key in ("target_scenario", "target_scenario_by_mode", "source_scenarios", "source_modes", "restore_history", "_source_contexts"):
            value = item.get(key)
            if value not in (None, "", [], {}):
                interaction[key] = value
        return [interaction]

    boxes: list[str] = []
    for element in elements:
        rect = _rect_for_scenario(element, default_scenario)
        try:
            left = float(rect.get("x", 0)) / width * 100
            top = float(rect.get("y", 0)) / height * 100
            box_width = float(rect.get("width", 100)) / width * 100
            box_height = float(rect.get("height", 60)) / height * 100
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        element_type = str(element.get("type", "rect"))
        interactive = element_type in INTERACTIVE_TYPES or bool(element.get("interactions"))
        tag = "button" if interactive else "div"
        raw_interactions = [item for item in element.get("interactions", []) or [] if isinstance(item, dict)]
        target = _element_target(element)
        target_attr = f' data-target="{escape(target)}"' if target in screen_ids else ""
        first_routed = next((item for item in raw_interactions if item.get("target_screen")), {})
        target_scenario = str(first_routed.get("target_scenario", ""))
        scenario_target_attr = f' data-target-scenario="{escape(target_scenario)}"' if target_scenario else ""
        target_scenario_by_mode = first_routed.get("target_scenario_by_mode")
        scenario_mode_attr = (
            f' data-target-scenario-by-mode="{escape(json.dumps(target_scenario_by_mode, ensure_ascii=False, separators=(",", ":")), quote=True)}"'
            if isinstance(target_scenario_by_mode, dict) and target_scenario_by_mode else ""
        )
        interactions_attr = (
            f' data-interactions="{escape(json.dumps(raw_interactions, ensure_ascii=False, separators=(",", ":")), quote=True)}"'
            if raw_interactions else ""
        )
        parent = str(element.get("parent", ""))
        parent_attr = f' data-parent="{escape(parent)}"' if parent else ""
        focus_attr = "" if interactive else ' tabindex="-1"'
        focus_order = element.get("accessibility", {}).get("focus_order") if isinstance(element.get("accessibility"), dict) else None
        focus_order_attr = f' data-focus-order="{focus_order}"' if isinstance(focus_order, int) and not isinstance(focus_order, bool) else ""
        label = str(element.get("name", element.get("id", "element")))
        accessible = str(element.get("accessibility", {}).get("label") or label)
        binding = ", ".join(str(item.get("path", "")) for item in element.get("data_bindings", []))
        state_map = {
            str(name): _state_applicable(definition)
            for name, definition in (element.get("states", {}) if isinstance(element.get("states"), dict) else {}).items()
        }
        state_attr = escape(json.dumps(state_map, ensure_ascii=False, separators=(",", ":")), quote=True)
        rect_map: dict[str, dict[str, float]] = {}
        override_names = list((element.get("rect_overrides") or {}).keys()) if isinstance(element.get("rect_overrides"), dict) else []
        for rect_scenario in ["default", *override_names]:
            scenario_rect = _rect_for_scenario(element, str(rect_scenario))
            try:
                rect_map[str(rect_scenario)] = {
                    "x": float(scenario_rect.get("x", 0)) / width * 100,
                    "y": float(scenario_rect.get("y", 0)) / height * 100,
                    "w": float(scenario_rect.get("width", 100)) / width * 100,
                    "h": float(scenario_rect.get("height", 60)) / height * 100,
                }
            except (TypeError, ValueError, ZeroDivisionError):
                rect_map = {"default": {"x": left, "y": top, "w": box_width, "h": box_height}}
                break
        rect_attr = escape(json.dumps(rect_map, ensure_ascii=False, separators=(",", ":")), quote=True)
        boxes.append(
            f'<{tag} class="proto-element type-{escape(element_type)}" style="--x:{left:.4f}%;--y:{top:.4f}%;--w:{box_width:.4f}%;--h:{box_height:.4f}%;--z:{visual_z(element)}"'
            f' data-element="{escape(str(element.get("id", "")))}" data-component-id="{escape(str(element.get("component_id", "")))}" data-state-map="{state_attr}" data-rect-map="{rect_attr}" aria-label="{escape(accessible)}"{parent_attr}{target_attr}{scenario_target_attr}{scenario_mode_attr}{interactions_attr}{focus_order_attr}{focus_attr}>'
            f'<span class="element-id">{escape(str(element.get("id", "")))}</span><span class="element-name">{escape(label)}</span>'
            f'{f"<small>{escape(binding)}</small>" if binding else ""}</{tag}>'
        )
    exits: list[str] = []
    exit_keys: set[tuple[str, str]] = set()
    for item in screen.get("exit_paths", []) or []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target_screen", ""))
        if target in screen_ids:
            label = str(item.get("label") or item.get("action") or item.get("action_id") or f"Go to {target}")
            interactions = navigation_interactions(item, target, label)
            interaction_attr = escape(json.dumps(interactions, ensure_ascii=False, separators=(",", ":")), quote=True)
            exits.append(f'<button class="flow-action" data-target="{escape(target)}" data-interactions="{interaction_attr}">{escape(label)} → {escape(target)}</button>')
            exit_keys.add((target, label))
    for item in authored_flow_actions or []:
        target = str(item.get("target", ""))
        label = str(item.get("label") or f"Go to {target}")
        if target not in screen_ids or (target, label) in exit_keys:
            continue
        flow_id = str(item.get("flow_id", ""))
        interactions = navigation_interactions(item, target, label)
        interaction_attr = escape(json.dumps(interactions, ensure_ascii=False, separators=(",", ":")), quote=True)
        exits.append(
            f'<button class="flow-action" data-target="{escape(target)}" data-flow-id="{escape(flow_id)}" data-interactions="{interaction_attr}">'
            f'{escape(label)} → {escape(target)}</button>'
        )
        exit_keys.add((target, label))
    safe = viewport.get("safe_area", {}) if isinstance(viewport.get("safe_area"), dict) else {}
    safe_style = ";".join(
        f"--safe-{key}:{float(safe.get(key, 0)) / (width if key in {'left', 'right'} else height) * 100:.4f}%"
        for key in ("left", "top", "right", "bottom")
    )
    scenarios = sorted(_screen_scenario_names(screen), key=lambda value: (value not in {"default", "loading", "empty", "error", "disabled"}, value))
    if default_scenario not in scenarios:
        scenarios.append(default_scenario)
    options = "".join(
        f'<option value="{value}"{" selected" if value == default_scenario else ""}>{value}</option>'
        for value in scenarios
    )
    return (
        f'<section class="proto-screen" id="screen-{escape(str(screen.get("id")))}" data-screen="{escape(str(screen.get("id")))}" hidden>'
        f'<header><div><strong>{escape(str(screen.get("name", screen.get("id"))))}</strong> <code>{escape(str(screen.get("id")))}</code></div>'
        f'<span class="status status-{escape(str(screen.get("status", "draft")))}">{escape(str(screen.get("status", "draft")))}</span>'
        f'<label>Scenario <select class="scenario-select">{options}</select></label></header>'
        f'<div class="viewport-shell"><div class="viewport" style="aspect-ratio:{width}/{height};--aspect:{width / height:.8f};{safe_style}" data-scenario="{escape(default_scenario)}" data-default-scenario="{escape(default_scenario)}">'
        f'<div class="safe-area" aria-hidden="true"></div>{"".join(boxes)}</div></div>'
        f'<p class="purpose">{escape(str(screen.get("purpose") or "Purpose not authored yet."))}</p>'
        f'<nav class="flow-actions">{"".join(exits) or "<span>No authored exit paths.</span>"}</nav>'
        '</section>'
    )


PROTOTYPE_CSS = """*{box-sizing:border-box}body{margin:0;background:#0c1118;color:#edf2f7;font:15px/1.45 system-ui,sans-serif}button,select{font:inherit}button{cursor:pointer}header.app{display:flex;align-items:center;gap:18px;padding:12px 18px;background:#141d28;border-bottom:1px solid #314257;position:sticky;top:0;z-index:5}header.app h1{font-size:18px;margin:0;color:#f1c75b}#screen-picker{min-width:220px;background:#202d3b;color:#fff;border:1px solid #52677f;padding:7px;border-radius:7px}.app-status{margin-left:auto;color:#9eafc2}.layout{max-width:1500px;margin:auto;padding:20px}.proto-screen>header{display:flex;gap:14px;align-items:center;margin-bottom:12px}.proto-screen>header label{margin-left:auto}.status{padding:3px 9px;border-radius:999px;background:#33465a}.status-approved{background:#22624f}.status-reviewed{background:#655725}.status-draft{background:#5b3743}.viewport-shell{display:flex;justify-content:center;padding:10px;background:#1a2531;border:1px solid #35485d;border-radius:12px}.viewport{position:relative;width:min(100%,calc(78vh * var(--aspect)));background:#101720;overflow:hidden}.safe-area{position:absolute;left:var(--safe-left);top:var(--safe-top);right:var(--safe-right);bottom:var(--safe-bottom);border:1px dashed #f1c75b88;pointer-events:none}.proto-element{position:absolute;left:var(--x);top:var(--y);width:var(--w);height:var(--h);z-index:var(--z);min-width:18px;min-height:16px;border:2px solid #7890aa;background:#26384b;color:#fff;border-radius:5px;display:flex;align-items:center;justify-content:center;gap:5px;padding:3px;overflow:hidden}.proto-element[hidden]{display:none}.proto-element:focus{outline:4px solid #f1c75b;outline-offset:2px;z-index:100}.proto-element[data-target]{border-color:#62dbc6;background:#31566a}.proto-element:disabled{opacity:.55;filter:grayscale(.45);cursor:not-allowed;border-style:dashed}.type-bar{background:linear-gradient(90deg,#55d6be 65%,#1d2937 65%)}.type-image{border-style:dashed;background:#1a2430}.type-text{background:transparent;border-color:#61758b}.element-id{position:absolute;left:2px;top:1px;font:700 10px ui-monospace,monospace;color:#f1c75b}.element-name{font-weight:650;text-align:center}.proto-element small{display:block;color:#b5c3d2;font:10px ui-monospace,monospace}.purpose{color:#b9c6d4}.flow-actions{display:flex;gap:9px;flex-wrap:wrap}.flow-action{border:1px solid #62dbc6;background:#1d3742;color:#fff;border-radius:7px;padding:7px 11px}.flow-action:disabled{opacity:.5;filter:grayscale(.5);cursor:not-allowed;border-style:dashed}.viewport[data-scenario=loading]::after,.viewport[data-scenario=empty]::after,.viewport[data-scenario=error]::after{content:attr(data-scenario);position:absolute;inset:20% 25%;z-index:200;display:grid;place-items:center;background:#111d2bea;border:2px solid #8195aa;border-radius:12px;text-transform:uppercase;font-size:26px}.viewport[data-scenario=error]::after{border-color:#ff5d73;color:#ff9aaa}.viewport[data-scenario=disabled] .proto-element{filter:grayscale(1);opacity:.5}footer{padding:20px;color:#8395aa;text-align:center}@media(max-width:700px){.element-name{font-size:10px}.proto-element small{display:none}header.app{flex-wrap:wrap}.app-status{margin-left:0}}"""


PROTOTYPE_JS = """(() => {
  const screens = [...document.querySelectorAll('.proto-screen')];
  const picker = document.getElementById('screen-picker');
  const history = [];
  const DEBUG_VISIBILITY_SCENARIOS = new Set(['empty', 'error', 'disabled']);

  function parseJSON(value, fallback) {
    try { return JSON.parse(value || ''); } catch (_) { return fallback; }
  }
  function interactionsFor(element) {
    const authored = parseJSON(element?.dataset.interactions, []);
    if (Array.isArray(authored) && authored.length) return authored;
    return element?.dataset.target ? [{target_screen: element.dataset.target}] : [];
  }
  function inferMode(...values) {
    return values.some(value => String(value || '').includes('local_demo')) ? 'local_demo' : 'online';
  }
  function currentMode(screen, scenario = '', baseScenario = '') {
    return screen?.dataset.mode || inferMode(scenario, baseScenario);
  }
  function routeScore(interaction, scenario, baseScenario, mode, contextScreen = '', contextScenario = '') {
    const scenarios = Array.isArray(interaction.source_scenarios) ? interaction.source_scenarios : [];
    const modes = Array.isArray(interaction.source_modes) ? interaction.source_modes : [];
    if (scenarios.length && !scenarios.includes(scenario) && !(baseScenario && scenarios.includes(baseScenario))) return -1;
    if (modes.length && !modes.includes(mode)) return -1;
    let score = 1;
    if (scenarios.includes(scenario)) score = 4;
    else if (baseScenario && scenarios.includes(baseScenario)) score = 3;
    else if (modes.includes(mode)) score = 2;
    const contexts = Array.isArray(interaction._source_contexts) ? interaction._source_contexts : [];
    if (contexts.some(context => context?.screen === contextScreen && context?.scenario === contextScenario)) score += 8;
    return score;
  }
  function sourceElementAvailable(owner, interaction) {
    const sourceId = String(interaction?._source_element || '');
    if (!sourceId) return true;
    const screen = owner?.closest('.proto-screen');
    const source = screen?.querySelector(`[data-element="${CSS.escape(sourceId)}"]`);
    return Boolean(source && !source.hidden && !source.disabled);
  }
  function resolveInteraction(element, scenario, baseScenario, mode) {
    const screen = element?.closest('.proto-screen');
    const contextScreen = screen?.dataset.sourceScreen || '';
    const contextScenario = screen?.dataset.sourceScenario || '';
    return interactionsFor(element)
      .map((interaction, index) => ({interaction, index, score: routeScore(interaction, scenario, baseScenario, mode, contextScreen, contextScenario)}))
      .filter(item => item.score >= 0 && sourceElementAvailable(element, item.interaction))
      .sort((a, b) => b.score - a.score || a.index - b.index)[0]?.interaction || null;
  }
  function stateMap(element) { return parseJSON(element.dataset.stateMap, {}); }
  function owns(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
  function visibleFor(element, scenario, baseScenario, mode) {
    const states = stateMap(element);
    if (owns(states, scenario)) return states[scenario];
    if (baseScenario && owns(states, baseScenario)) return states[baseScenario];
    if (mode === 'local_demo' && owns(states, 'local_demo')) return states.local_demo;
    return owns(states, 'default') ? states.default : true;
  }
  function activeModalFor(screen) {
    return [...(screen?.querySelectorAll('.proto-element[data-component-id="system-modal"]') || [])]
      .filter(element => !element.hidden).at(-1) || null;
  }
  function modalMembers(screen, modal) {
    const members = new Set();
    if (!screen || !modal) return members;
    const viewport = screen.querySelector('.viewport');
    const scenario = viewport?.dataset.scenario || 'default';
    const elements = [...screen.querySelectorAll('.proto-element')];
    const byId = new Map(elements.map(element => [element.dataset.element, element]));
    elements.forEach(element => {
      let parentId = element.dataset.parent || '';
      const visited = new Set();
      while (parentId && !visited.has(parentId)) {
        visited.add(parentId);
        if (parentId === modal.dataset.element) { members.add(element); break; }
        parentId = byId.get(parentId)?.dataset.parent || '';
      }
      const states = stateMap(element);
      if (!element.hidden && owns(states, scenario) && states[scenario] === true) members.add(element);
    });
    members.add(modal);
    return members;
  }
  function orderedFocusable(screen) {
    const modal = activeModalFor(screen);
    const members = modalMembers(screen, modal);
    return [...screen.querySelectorAll('button:not([disabled]):not([hidden]):not([inert]),select:not([disabled]):not([inert])')]
      .filter(element => !modal || members.has(element))
      .map((element, index) => ({element, index, order: Number(element.dataset.focusOrder || 999999)}))
      .sort((a, b) => a.order - b.order || a.index - b.index)
      .map(item => item.element);
  }
  function focusFirst(screen) {
    const first = orderedFocusable(screen)[0];
    if (first) { first.focus({preventScroll: true}); return; }
    const modal = activeModalFor(screen);
    if (modal) {
      modal.tabIndex = -1;
      modal.focus({preventScroll: true});
    }
  }
  function applyScenario(viewport, scenario, baseScenario = '') {
    viewport.dataset.scenario = scenario;
    if (baseScenario && baseScenario !== scenario) viewport.dataset.baseScenario = baseScenario;
    else delete viewport.dataset.baseScenario;
    const screen = viewport.closest('.proto-screen');
    const elements = [...viewport.querySelectorAll('.proto-element')];
    const mode = currentMode(screen, scenario, baseScenario);
    const visibilityScenario = DEBUG_VISIBILITY_SCENARIOS.has(scenario)
      ? (baseScenario || viewport.dataset.defaultScenario || 'default') : scenario;
    const visibilityBase = DEBUG_VISIBILITY_SCENARIOS.has(scenario) ? '' : baseScenario;
    elements.forEach(element => {
      element.hidden = !visibleFor(element, visibilityScenario, visibilityBase, mode);
      const rects = parseJSON(element.dataset.rectMap, {});
      const rect = rects[scenario] || (baseScenario ? rects[baseScenario] : null) || rects.default;
      if (rect) {
        element.style.setProperty('--x', `${rect.x}%`);
        element.style.setProperty('--y', `${rect.y}%`);
        element.style.setProperty('--w', `${rect.w}%`);
        element.style.setProperty('--h', `${rect.h}%`);
      }
    });
    const byId = new Map(elements.map(element => [element.dataset.element, element]));
    let changed = true;
    while (changed) {
      changed = false;
      elements.forEach(element => {
        const parent = byId.get(element.dataset.parent || '');
        if (!element.hidden && parent?.hidden) { element.hidden = true; changed = true; }
      });
    }
    elements.forEach(element => {
      if (!(element instanceof HTMLButtonElement)) return;
      const authored = interactionsFor(element);
      const unavailable = authored.length > 0 && !resolveInteraction(element, scenario, baseScenario, mode);
      element.disabled = unavailable;
      element.inert = unavailable;
      if (unavailable) element.setAttribute('aria-disabled', 'true');
      else element.removeAttribute('aria-disabled');
    });
    const activeModal = activeModalFor(screen);
    const members = modalMembers(screen, activeModal);
    elements.forEach(element => {
      if (!(element instanceof HTMLButtonElement)) return;
      const routeUnavailable = element.disabled;
      const suppressed = Boolean(activeModal) && !members.has(element);
      element.inert = routeUnavailable || suppressed;
      if (suppressed) element.dataset.modalSuppressed = 'true';
      else delete element.dataset.modalSuppressed;
    });
    screen?.querySelectorAll('.flow-action').forEach(element => {
      const authored = interactionsFor(element);
      const unavailable = authored.length > 0 && !resolveInteraction(element, scenario, baseScenario, mode);
      element.disabled = unavailable;
      element.inert = unavailable || Boolean(activeModal);
      if (unavailable) element.setAttribute('aria-disabled', 'true');
      else element.removeAttribute('aria-disabled');
    });
    const scenarioSelect = screen?.querySelector('.scenario-select');
    if (scenarioSelect) { scenarioSelect.disabled = Boolean(activeModal); scenarioSelect.inert = Boolean(activeModal); }
    if (picker) { picker.disabled = Boolean(activeModal); picker.inert = Boolean(activeModal); }
    elements.filter(element => element.dataset.componentId === 'system-modal').forEach(element => {
      if (element === activeModal) {
        element.setAttribute('role', 'dialog');
        element.setAttribute('aria-modal', 'true');
        element.tabIndex = -1;
      } else {
        element.removeAttribute('role');
        element.removeAttribute('aria-modal');
      }
    });
    if (activeModal) screen.dataset.activeModal = activeModal.dataset.element || 'modal';
    else if (screen) delete screen.dataset.activeModal;
  }
  function snapshot(screen) {
    const viewport = screen?.querySelector('.viewport');
    return {
      id: screen?.dataset.screen || '',
      scenario: viewport?.dataset.scenario || 'default',
      baseScenario: viewport?.dataset.baseScenario || '',
      mode: currentMode(screen, viewport?.dataset.scenario, viewport?.dataset.baseScenario),
      sourceScreen: screen?.dataset.sourceScreen || '',
      sourceScenario: screen?.dataset.sourceScenario || '',
    };
  }
  function setScenario(screen, scenario, baseScenario = '') {
    const select = screen?.querySelector('.scenario-select');
    const viewport = screen?.querySelector('.viewport');
    if (!select || !viewport || ![...select.options].some(option => option.value === scenario)) return false;
    select.value = scenario;
    applyScenario(viewport, scenario, baseScenario);
    return true;
  }
  function show(id, remember = true, mode = '', scenario = '', baseScenario = '', sourceContext = null) {
    const next = document.querySelector(`[data-screen="${CSS.escape(id)}"]`);
    if (!next) return;
    const current = screens.find(screen => !screen.hidden);
    if (remember && current && current.dataset.screen !== id) history.push(snapshot(current));
    screens.forEach(screen => { screen.hidden = screen !== next; });
    picker.value = id;
    location.hash = `screen=${encodeURIComponent(id)}`;
    const viewport = next.querySelector('.viewport');
    const defaultScenario = viewport?.dataset.defaultScenario || 'default';
    next.dataset.mode = inferMode(scenario, baseScenario) === 'local_demo'
      ? 'local_demo' : (mode || inferMode(defaultScenario));
    if (sourceContext?.screen) next.dataset.sourceScreen = sourceContext.screen;
    else delete next.dataset.sourceScreen;
    if (sourceContext?.scenario) next.dataset.sourceScenario = sourceContext.scenario;
    else delete next.dataset.sourceScenario;
    delete next.dataset.previousScenario;
    setScenario(next, scenario || defaultScenario, baseScenario);
    focusFirst(next);
  }
  function restoreSnapshot(item) {
    if (!item?.id) return;
    show(item.id, false, item.mode, item.scenario, item.baseScenario, {
      screen: item.sourceScreen || '', scenario: item.sourceScenario || '',
    });
  }
  function requestedScenario(interaction, mode) {
    let requested = String(interaction?.target_scenario || '');
    const byMode = interaction?.target_scenario_by_mode;
    if (requested !== '@base' && byMode && typeof byMode === 'object') requested = String(byMode[mode] || requested);
    return requested;
  }
  function navigate(element) {
    if (!element || element.disabled || element.inert) return;
    const sourceScreen = element.closest('.proto-screen');
    if (!sourceScreen) return;
    const viewport = sourceScreen.querySelector('.viewport');
    const sourceScenario = viewport?.dataset.scenario || 'default';
    const sourceBaseScenario = viewport?.dataset.baseScenario || '';
    const mode = currentMode(sourceScreen, sourceScenario, sourceBaseScenario);
    const interaction = resolveInteraction(element, sourceScenario, sourceBaseScenario, mode);
    const targetId = String(interaction?.target_screen || element.dataset.target || '');
    if (!interaction || !targetId) return;
    let nextScenario = requestedScenario(interaction, mode);
    const sameScreen = sourceScreen.dataset.screen === targetId;
    if (!sameScreen) {
      const previous = history.at(-1);
      if (interaction.restore_history === true && previous?.id === targetId) {
        restoreSnapshot(history.pop());
        return;
      }
      const backward = /^(back|close|leave)(_|$)/i.test(String(interaction.action || ''));
      if (backward && previous?.id === targetId) {
        restoreSnapshot(history.pop());
      } else {
        show(targetId, !backward, mode, nextScenario === '@base' ? '' : nextScenario, '', {
          screen: sourceScreen.dataset.screen || '',
          scenario: sourceBaseScenario || sourceScenario,
        });
      }
      return;
    }
    if (!nextScenario) return;
    const hadModal = activeModalFor(sourceScreen);
    let nextBase = '';
    if (nextScenario === '@base') {
      nextScenario = sourceBaseScenario || sourceScreen.dataset.previousScenario || viewport?.dataset.defaultScenario || 'default';
      delete sourceScreen.dataset.previousScenario;
    } else if (hadModal && nextScenario === (viewport?.dataset.defaultScenario || 'default')) {
      nextScenario = sourceBaseScenario || sourceScreen.dataset.previousScenario || nextScenario;
      delete sourceScreen.dataset.previousScenario;
    } else if (nextScenario !== sourceScenario) {
      const previous = sourceBaseScenario || sourceScenario;
      sourceScreen.dataset.previousScenario = previous;
      const opensModal = [...sourceScreen.querySelectorAll('.proto-element[data-component-id="system-modal"]')]
        .some(modal => stateMap(modal)[nextScenario] === true);
      nextBase = opensModal ? previous : '';
      sourceScreen.dataset.modalOpener = element.dataset.element || '';
    }
    if (!setScenario(sourceScreen, nextScenario, nextBase)) return;
    const activeModal = activeModalFor(sourceScreen);
    if (activeModal) {
      focusFirst(sourceScreen);
    } else if (hadModal) {
      const openerId = sourceScreen.dataset.modalOpener || '';
      const opener = openerId ? sourceScreen.querySelector(`[data-element="${CSS.escape(openerId)}"]`) : null;
      delete sourceScreen.dataset.modalOpener;
      if (opener && !opener.hidden && !opener.disabled) opener.focus({preventScroll: true});
      else focusFirst(sourceScreen);
    } else {
      focusFirst(sourceScreen);
    }
  }
  function cancelModal(screen) {
    const modal = activeModalFor(screen);
    if (!modal) return false;
    const viewport = screen.querySelector('.viewport');
    const scenario = viewport?.dataset.scenario || 'default';
    const baseScenario = viewport?.dataset.baseScenario || '';
    const mode = currentMode(screen, scenario, baseScenario);
    const cancel = orderedFocusable(screen).find(element => {
      const route = resolveInteraction(element, scenario, baseScenario, mode);
      return route && route.target_screen === screen.dataset.screen && /(cancel|dismiss|close)/i.test(String(route.action || ''));
    });
    if (cancel) { cancel.click(); return true; }
    // A modal without an authored cancel route represents an authoritative
    // in-flight operation. Consume cancel input without fabricating a close.
    return true;
  }
  function invokeBackRoute(screen) {
    if (!screen) return false;
    const viewport = screen.querySelector('.viewport');
    const scenario = viewport?.dataset.scenario || 'default';
    const baseScenario = viewport?.dataset.baseScenario || '';
    const mode = currentMode(screen, scenario, baseScenario);
    const control = orderedFocusable(screen).find(element => {
      const route = resolveInteraction(element, scenario, baseScenario, mode);
      return route && /^(back|close|leave)(_|$)/i.test(String(route.action || ''));
    });
    if (!control) return false;
    navigate(control);
    return true;
  }
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-interactions],[data-target]');
    if (target) navigate(target);
  });
  document.addEventListener('change', event => {
    if (event.target === picker) show(picker.value);
    if (event.target.matches('.scenario-select')) {
      const screen = event.target.closest('.proto-screen');
      delete screen.dataset.previousScenario;
      delete screen.dataset.modalOpener;
      screen.dataset.mode = inferMode(event.target.value);
      applyScenario(screen.querySelector('.viewport'), event.target.value);
      focusFirst(screen);
    }
  });
  document.addEventListener('keydown', event => {
    const activeScreen = screens.find(screen => !screen.hidden);
    if (!activeScreen) return;
    if (event.key === 'Escape') {
      if (cancelModal(activeScreen)) { event.preventDefault(); return; }
      if (invokeBackRoute(activeScreen)) { event.preventDefault(); return; }
      if (history.length) { event.preventDefault(); restoreSnapshot(history.pop()); return; }
    }
    const focusable = orderedFocusable(activeScreen);
    if (event.key === 'Tab' && activeModalFor(activeScreen)) {
      event.preventDefault();
      if (!focusable.length) {
        activeModalFor(activeScreen).focus({preventScroll: true});
        return;
      }
      const index = focusable.indexOf(document.activeElement);
      const delta = event.shiftKey ? -1 : 1;
      focusable[(index + delta + focusable.length) % focusable.length].focus();
      return;
    }
    if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
    const index = focusable.indexOf(document.activeElement);
    if (index < 0 || focusable.length < 2) return;
    event.preventDefault();
    const delta = ['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1;
    focusable[(index + delta + focusable.length) % focusable.length].focus();
  });
  let previousButtons = [];
  function pollGamepads() {
    const pad = navigator.getGamepads ? [...navigator.getGamepads()].find(Boolean) : null;
    if (pad) {
      const pressed = pad.buttons.map(button => button.pressed);
      if (pressed[0] && !previousButtons[0] && document.activeElement instanceof HTMLElement) document.activeElement.click();
      if (pressed[1] && !previousButtons[1]) {
        const activeScreen = screens.find(screen => !screen.hidden);
        if (!cancelModal(activeScreen) && !invokeBackRoute(activeScreen) && history.length) restoreSnapshot(history.pop());
      }
      previousButtons = pressed;
    }
    requestAnimationFrame(pollGamepads);
  }
  const hashId = decodeURIComponent((location.hash.match(/screen=([^&]+)/) || [])[1] || '');
  const authoredEntry = document.querySelector('.layout')?.dataset.entryScreen || '';
  const initialId = document.querySelector(`[data-screen="${CSS.escape(hashId)}"]`)
    ? hashId
    : (document.querySelector(`[data-screen="${CSS.escape(authoredEntry)}"]`) ? authoredEntry : screens[0]?.dataset.screen || '');
  show(initialId, false);
  pollGamepads();
})();
"""


def build_prototype(ir: dict[str, Any], output_root: Path, *, release: bool = False) -> None:
    screens = ir["screens"]
    if release:
        if not screens:
            raise ValueError("Release prototype requires at least one approved screen.")
        unapproved = [screen.get("id") for screen in screens if screen.get("status") != "approved"]
        if unapproved:
            raise ValueError(f"Release prototype requires approved screens: {', '.join(str(value) for value in unapproved)}")
        if ir["validation"].get("errors"):
            raise ValueError("Release prototype requires a clean validation report.")
    screen_ids = {str(screen.get("id")) for screen in screens}
    flow_actions: dict[str, list[dict[str, Any]]] = {}
    authored_entry = ""
    screen_defaults = {
        str(screen.get("id")): str(screen.get("default_scenario") or "default")
        for screen in screens
        if screen.get("id")
    }
    raw_flows = ir.get("flows", {}).get("flows", []) if isinstance(ir.get("flows"), dict) else []
    flow_ids: list[str] = []
    for flow in raw_flows if isinstance(raw_flows, list) else []:
        if not isinstance(flow, dict):
            continue
        flow_id = str(flow.get("id", ""))
        if flow_id:
            flow_ids.append(flow_id)
        entry = str(flow.get("entry_screen", ""))
        if not authored_entry and entry in screen_ids:
            authored_entry = entry
        current_screen = entry
        current_scenario = str(flow.get("entry_scenario") or screen_defaults.get(entry, "default"))
        source_context_screen = ""
        source_context_scenario = ""
        for step in flow.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            source = str(step.get("screen", ""))
            target = str(step.get("next_screen", ""))
            if source not in screen_ids or target not in screen_ids:
                continue
            action_id = str(step.get("action") or step.get("action_id") or f"Go to {target}")
            label = str(step.get("label") or action_id)
            action: dict[str, Any] = {"target": target, "label": label, "action": action_id, "flow_id": flow_id}
            source_scenarios = step.get("source_scenarios")
            if isinstance(source_scenarios, list) and source_scenarios:
                action["source_scenarios"] = source_scenarios
            elif source == current_screen and current_scenario:
                action["source_scenarios"] = [current_scenario]
            source_modes = step.get("source_modes")
            if isinstance(source_modes, list) and source_modes:
                action["source_modes"] = source_modes
            if source_context_screen and source_context_scenario:
                action["_source_contexts"] = [{
                    "screen": source_context_screen,
                    "scenario": source_context_scenario,
                }]
            target_scenario = step.get("target_scenario")
            if isinstance(target_scenario, str) and target_scenario:
                action["target_scenario"] = target_scenario
            target_scenario_by_mode = step.get("target_scenario_by_mode")
            if isinstance(target_scenario_by_mode, dict) and target_scenario_by_mode:
                action["target_scenario_by_mode"] = target_scenario_by_mode
            if step.get("restore_history") is True:
                action["restore_history"] = True
            flow_actions.setdefault(source, []).append(action)
            if target != source:
                source_context_screen = source
                source_context_scenario = current_scenario
                current_scenario = str(target_scenario or screen_defaults.get(target, "default"))
            elif isinstance(target_scenario, str) and target_scenario and target_scenario != "@base":
                current_scenario = target_scenario
            current_screen = target
    options = "".join(f'<option value="{escape(str(screen.get("id")))}">{escape(str(screen.get("name", screen.get("id"))))}</option>' for screen in screens)
    sections = "".join(_prototype_screen(screen, screen_ids, flow_actions.get(str(screen.get("id")), [])) for screen in screens)
    project = ir["project"].get("project", {})
    source_hash = hashlib.sha256(json.dumps(ir.get("source_hashes", {}), sort_keys=True).encode("utf-8")).hexdigest()[:12]
    html = f'''<!doctype html><html lang="{escape(str(project.get('default_locale', 'en')))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'none'">
<title>{escape(str(project.get('name', 'Game')))} UX prototype</title><link rel="stylesheet" href="prototype.css"></head><body>
<header class="app"><h1>{escape(str(project.get('name', 'Game')))} UX prototype</h1><label>Screen <select id="screen-picker">{options}</select></label><span class="app-status">contract {source_hash}</span></header>
<main class="layout" data-entry-screen="{escape(authored_entry, quote=True)}">{sections or '<p>No screen contracts found.</p>'}</main><footer>Generated from game UX/UI contracts. Edit source JSON, not this prototype.</footer><script src="prototype.js"></script></body></html>'''
    _write_text(output_root / "index.html", html)
    _write_text(output_root / "prototype.css", PROTOTYPE_CSS)
    _write_text(output_root / "prototype.js", PROTOTYPE_JS)
    _write_json(
        output_root / "prototype-manifest.json",
        {
            "prototype_version": DESIGN_SCHEMA_VERSION,
            "built_at": _now(),
            "release": release,
            "screens": sorted(screen_ids),
            "flows": sorted(set(flow_ids)),
            "entry_screen": authored_entry,
            "source_hashes": ir.get("source_hashes", {}),
        },
    )


def command_prototype_build(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    output = Path(args.output).resolve() if args.output else design_root / "build" / "prototype"
    if args.output and (output.exists() or output.is_symlink()):
        if not output.is_dir() or output.is_symlink():
            print(f"ERROR Refusing to replace a non-directory output path: {output}")
            return 1
        if any(output.iterdir()) and not args.force:
            raise SystemExit(f"Prototype directory is not empty: {output}. Use --force to refresh generated files.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=str(output.parent)))
    try:
        ir = compile_design_ir(design_root, project_root=_project_root(args))
        build_prototype(ir, staging, release=args.release)
        _replace_generated_directory(staging, output)
    except (OSError, ValueError) as exc:
        if staging.exists() and staging.resolve().parent == output.parent.resolve():
            shutil.rmtree(staging)
        print(f"ERROR Cannot build prototype: {exc}")
        return 1
    print(f"Built interactive UX prototype: {output / 'index.html'}")
    return 0


def _engine_node(element: dict[str, Any]) -> dict[str, Any]:
    element_type = str(element.get("type", "rect"))
    type_map = {
        "text": "label",
        "button": "button",
        "bar": "progress",
        "image": "image",
        "icon": "image",
        "input": "input",
        "toggle": "toggle",
        "slider": "slider",
    }
    return {
        "id": element.get("id"),
        "name": element.get("name"),
        "node_type": type_map.get(element_type, "container"),
        "source_type": element_type,
        "parent": element.get("parent"),
        "rect": element.get("rect", {}),
        "rect_overrides": element.get("rect_overrides", {}),
        "states": element.get("states", {}),
        "bindings": element.get("data_bindings", []),
        "interactions": element.get("interactions", []),
        "accessibility": element.get("accessibility", {}),
        "asset_ref": element.get("asset_ref"),
        "component_id": element.get("component_id"),
        "z_index": element.get("z_index", 0),
        "control_contracts": element.get("control_contracts", []),
    }


def _engine_nodes_for_screen(screen: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [element for element in screen.get("elements", []) if isinstance(element, dict)]
    by_id = {str(element.get("id")): element for element in elements}
    nodes: list[dict[str, Any]] = []
    for element in elements:
        node = _engine_node(element)
        absolute = dict(element.get("rect", {}))
        parent_id = str(element.get("parent", ""))
        local = dict(absolute)
        if parent_id and parent_id in by_id:
            parent_rect = by_id[parent_id].get("rect", {})
            local["x"] = float(absolute.get("x", 0)) - float(parent_rect.get("x", 0))
            local["y"] = float(absolute.get("y", 0)) - float(parent_rect.get("y", 0))
        node["rect"] = local
        node["absolute_rect"] = absolute
        node["coordinate_space"] = "parent_local" if parent_id else "viewport_absolute"
        nodes.append(node)
    return nodes


def build_engine_ir(ir: dict[str, Any], *, release: bool = False, screen_filter: str | None = None) -> dict[str, Any]:
    screens = [screen for screen in ir["screens"] if not screen_filter or screen.get("id") == screen_filter]
    if screen_filter and not screens:
        raise ValueError(f"Unknown screen: {screen_filter}")
    if release:
        if not screens:
            raise ValueError("Release export requires at least one approved screen.")
        unapproved = [str(screen.get("id")) for screen in screens if screen.get("status") != "approved"]
        if unapproved:
            raise ValueError(f"Release export requires approved screens: {', '.join(unapproved)}")
    return {
        "engine_ir_version": DESIGN_SCHEMA_VERSION,
        "generated_at": _now(),
        "project": ir["project"].get("project", {}),
        "tokens": ir["tokens"],
        "screens": [
            {
                "id": screen.get("id"),
                "name": screen.get("name"),
                "revision": screen.get("revision"),
                "status": screen.get("status"),
                "viewport": screen.get("viewport", {}),
                "nodes": _engine_nodes_for_screen(screen),
                "entry_conditions": screen.get("entry_conditions", []),
                "exit_paths": screen.get("exit_paths", []),
            }
            for screen in screens
        ],
        "source_hashes": ir.get("source_hashes", {}),
    }


def _unity_tag(node_type: str) -> str:
    return {
        "label": "ui:Label",
        "button": "ui:Button",
        "progress": "ui:ProgressBar",
        "image": "ui:VisualElement",
        "input": "ui:TextField",
        "toggle": "ui:Toggle",
        "slider": "ui:Slider",
        "container": "ui:VisualElement",
    }.get(node_type, "ui:VisualElement")


def _export_unity_uitoolkit(engine_ir: dict[str, Any], output: Path) -> dict[str, Any]:
    unsupported: list[dict[str, str]] = []
    for screen in engine_ir["screens"]:
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<ui:UXML xmlns:ui="UnityEngine.UIElements">',
            f'  <ui:VisualElement name="{escape(str(screen["id"]), quote=True)}" class="screen-root">',
        ]
        bindings: list[dict[str, Any]] = []
        children: dict[str, list[dict[str, Any]]] = {}
        for node in screen["nodes"]:
            children.setdefault(str(node.get("parent") or ""), []).append(node)
            rect = node.get("rect", {})
            bindings.append(
                {
                    "node": node.get("id"),
                    "bindings": node.get("bindings", []),
                    "interactions": node.get("interactions", []),
                    "states": node.get("states", {}),
                    "accessibility": node.get("accessibility", {}),
                    "asset_ref": node.get("asset_ref"),
                    "component_id": node.get("component_id"),
                    "zIndex": node.get("z_index", 0),
                    "controlContracts": node.get("control_contracts", []),
                }
            )
            for interaction in node.get("interactions", []):
                feedback = interaction.get("feedback") if isinstance(interaction, dict) else None
                if feedback and any(key in feedback for key in ("audio", "haptic")):
                    unsupported.append({"screen": str(screen["id"]), "node": str(node.get("id")), "feature": "audio/haptic feedback", "handling": "manual binding required"})

        def append_node(node: dict[str, Any], depth: int) -> None:
            rect = node.get("rect", {})
            tag = _unity_tag(str(node.get("node_type")))
            text_attr = f' text="{escape(str(node.get("name", "")), quote=True)}"' if node.get("node_type") in {"label", "button", "input", "toggle"} else ""
            style = (
                "position:absolute;"
                f"left:{rect.get('x', 0)}px;top:{rect.get('y', 0)}px;"
                f"width:{rect.get('width', 100)}px;height:{rect.get('height', 60)}px;"
            )
            indent = "  " * depth
            node_children = children.get(str(node.get("id")), [])
            opening = f'{indent}<{tag} name="{escape(str(node.get("id", "")), quote=True)}"{text_attr} style="{escape(style, quote=True)}"'
            if not node_children:
                lines.append(opening + " />")
                return
            lines.append(opening + ">")
            for child in node_children:
                append_node(child, depth + 1)
            lines.append(f"{indent}</{tag}>")

        for node in children.get("", []):
            append_node(node, 2)
        lines.extend(["  </ui:VisualElement>", "</ui:UXML>"])
        _write_text(output / f"{screen['id']}.uxml", "\n".join(lines) + "\n")
        _write_json(output / f"{screen['id']}.bindings.json", {"screen": screen["id"], "entries": bindings})
    colors = engine_ir.get("tokens", {}).get("color", {})
    css_lines = [":root {"]
    for key, value in colors.items() if isinstance(colors, dict) else []:
        token = value.get("value") if isinstance(value, dict) else value
        css_lines.append(f"  --ui-{_slug(str(key))}: {token};")
    css_lines.extend(["}", ".screen-root { position: absolute; left: 0; top: 0; right: 0; bottom: 0; }"])
    _write_text(output / "tokens.uss", "\n".join(css_lines) + "\n")
    return {"supported": ["viewport-absolute contract with nested local export", "element hierarchy", "label", "button", "progress", "image placeholder", "input", "toggle", "slider", "token variables"], "manual_or_lossy": unsupported}


def _export_unity_ugui(engine_ir: dict[str, Any], output: Path) -> dict[str, Any]:
    type_map = {"label": "Text", "button": "Button", "progress": "Slider", "image": "Image", "input": "InputField", "toggle": "Toggle", "slider": "Slider", "container": "RectTransform"}
    for screen in engine_ir["screens"]:
        nodes = []
        for node in screen["nodes"]:
            nodes.append(
                {
                    "name": node.get("id"),
                    "component": type_map.get(str(node.get("node_type")), "RectTransform"),
                    "rectTransform": node.get("rect", {}),
                    "absoluteRect": node.get("absolute_rect", {}),
                    "rectOverrides": node.get("rect_overrides", {}),
                    "coordinateSpace": node.get("coordinate_space"),
                    "parent": node.get("parent") or screen["id"],
                    "asset": node.get("asset_ref"),
                    "bindings": node.get("bindings", []),
                    "events": node.get("interactions", []),
                    "accessibility": node.get("accessibility", {}),
                    "states": node.get("states", {}),
                    "component_id": node.get("component_id"),
                    "zIndex": node.get("z_index", 0),
                    "controlContracts": node.get("control_contracts", []),
                }
            )
        _write_json(output / f"{screen['id']}.ugui.json", {"format": "ui-ref-unity-ugui/1", "screen": screen, "hierarchy": nodes})
    return {"supported": ["RectTransform hierarchy handoff", "viewport-absolute and parent-local geometry", "uGUI component mapping", "binding/event manifest"], "manual_or_lossy": [{"feature": "Unity prefab serialization", "handling": "create prefab in Unity from the generated handoff JSON"}]}


def _godot_type(node_type: str) -> str:
    return {"label": "Label", "button": "Button", "progress": "ProgressBar", "image": "TextureRect", "input": "LineEdit", "toggle": "CheckButton", "slider": "HSlider", "container": "Control"}.get(node_type, "Control")


def _gd_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _export_godot(engine_ir: dict[str, Any], output: Path) -> dict[str, Any]:
    for screen in engine_ir["screens"]:
        lines = ["[gd_scene format=3]", "", f'[node name={_gd_quote(screen["id"])} type="Control"]', "layout_mode = 3", "anchors_preset = 0"]
        bindings: list[dict[str, Any]] = []
        by_id = {str(node.get("id")): node for node in screen["nodes"]}
        children: dict[str, list[dict[str, Any]]] = {}
        for node in screen["nodes"]:
            children.setdefault(str(node.get("parent") or ""), []).append(node)

        ordered: list[dict[str, Any]] = []
        def append_tree(parent_id: str) -> None:
            for child in children.get(parent_id, []):
                ordered.append(child)
                append_tree(str(child.get("id")))
        append_tree("")

        def node_path(node_id: str) -> str:
            node = by_id[node_id]
            parent_id = str(node.get("parent") or "")
            return f"{node_path(parent_id)}/{node_id}" if parent_id else node_id

        for node in ordered:
            rect = node.get("rect", {})
            node_id = str(node.get("id", "Node"))
            parent_id = str(node.get("parent") or "")
            parent_path = node_path(parent_id) if parent_id else "."
            lines.extend(
                [
                    "",
                    f'[node name={_gd_quote(node_id)} type="{_godot_type(str(node.get("node_type")))}" parent={_gd_quote(parent_path)}]',
                    f"offset_left = {float(rect.get('x', 0))}",
                    f"offset_top = {float(rect.get('y', 0))}",
                    f"offset_right = {float(rect.get('x', 0)) + float(rect.get('width', 100))}",
                    f"offset_bottom = {float(rect.get('y', 0)) + float(rect.get('height', 60))}",
                ]
            )
            if node.get("node_type") in {"label", "button", "input", "toggle"}:
                lines.append(f"text = {_gd_quote(node.get('name', ''))}")
            bindings.append(
                {
                    "node": node.get("id"),
                    "bindings": node.get("bindings", []),
                    "interactions": node.get("interactions", []),
                    "states": node.get("states", {}),
                    "accessibility": node.get("accessibility", {}),
                    "asset_ref": node.get("asset_ref"),
                    "component_id": node.get("component_id"),
                    "z_index": node.get("z_index", 0),
                    "control_contracts": node.get("control_contracts", []),
                }
            )
        _write_text(output / f"{screen['id']}.tscn", "\n".join(lines) + "\n")
        _write_json(output / f"{screen['id']}.bindings.json", {"screen": screen["id"], "entries": bindings})
    return {"supported": ["Godot Control scene", "element hierarchy with parent-local geometry", "common controls", "binding/event manifest"], "manual_or_lossy": [{"feature": "Theme resources and runtime scripts", "handling": "bind generated scene to project Theme and GDScript"}]}


def _export_cocos(engine_ir: dict[str, Any], output: Path) -> dict[str, Any]:
    type_map = {"label": "cc.Label", "button": "cc.Button", "progress": "cc.ProgressBar", "image": "cc.Sprite", "input": "cc.EditBox", "toggle": "cc.Toggle", "slider": "cc.Slider", "container": "cc.Node"}
    for screen in engine_ir["screens"]:
        nodes = []
        for node in screen["nodes"]:
            nodes.append(
                {
                    "name": node.get("id"),
                    "components": [
                        {"type": "cc.UITransform", "rect": node.get("rect", {})},
                        {"type": type_map.get(str(node.get("node_type")), "cc.Node")},
                    ],
                    "parent": node.get("parent") or screen["id"],
                    "absoluteRect": node.get("absolute_rect", {}),
                    "coordinateSpace": node.get("coordinate_space"),
                    "asset": node.get("asset_ref"),
                    "bindings": node.get("bindings", []),
                    "events": node.get("interactions", []),
                    "states": node.get("states", {}),
                    "accessibility": node.get("accessibility", {}),
                    "component_id": node.get("component_id"),
                    "zIndex": node.get("z_index", 0),
                    "controlContracts": node.get("control_contracts", []),
                }
            )
        _write_json(output / f"{screen['id']}.cocos.json", {"format": "ui-ref-cocos/1", "screen": screen, "nodes": nodes})
    return {"supported": ["Cocos node/component hierarchy handoff", "viewport-absolute and parent-local UITransform geometry", "binding/event manifest"], "manual_or_lossy": [{"feature": "version-specific .prefab serialization", "handling": "import JSON through a project-side editor adapter"}]}


def _engine_manual_gaps(engine_ir: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node for screen in engine_ir.get("screens", []) for node in screen.get("nodes", [])]
    gaps: list[dict[str, Any]] = []

    def add(feature: str, handling: str, affected: list[dict[str, Any]], preserved_in: str = "engine-ir.json") -> None:
        if affected:
            gaps.append(
                {
                    "classification": "manual",
                    "feature": feature,
                    "handling": handling,
                    "affected_nodes": [str(node.get("id")) for node in affected],
                    "preserved_in": preserved_in,
                }
            )

    add("runtime state styling and transitions", "Implement engine-native state selectors/animations from the preserved state contract.", [node for node in nodes if node.get("states")])
    add("accessibility semantics and focus behavior", "Map labels, roles, focus order, and non-color cues to the target project's accessibility layer.", [node for node in nodes if node.get("accessibility")])
    add("project asset resolution", "Resolve asset_ref through the target project's asset database/import pipeline.", [node for node in nodes if node.get("asset_ref")])
    add("reusable component instantiation", "Map component_id to a project prefab/scene/component implementation.", [node for node in nodes if node.get("component_id")])
    add("runtime data and event binding", "Connect the generated binding/event manifest to project runtime code.", [node for node in nodes if node.get("bindings") or node.get("interactions")])
    if any(screen.get("entry_conditions") or screen.get("exit_paths") for screen in engine_ir.get("screens", [])):
        gaps.append(
            {
                "classification": "manual",
                "feature": "screen flow/router integration",
                "handling": "Connect entry conditions and exit paths to the project's screen/navigation controller.",
                "preserved_in": "engine-ir.json",
            }
        )
    return gaps


def export_engine(engine_ir: dict[str, Any], engine: str, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "engine-ir.json", engine_ir)
    if engine == "unity-uitoolkit":
        capabilities = _export_unity_uitoolkit(engine_ir, output)
    elif engine == "unity-ugui":
        capabilities = _export_unity_ugui(engine_ir, output)
    elif engine == "godot":
        capabilities = _export_godot(engine_ir, output)
    elif engine == "cocos":
        capabilities = _export_cocos(engine_ir, output)
    else:
        raise ValueError(f"Unsupported engine: {engine}")
    combined_gaps = [*capabilities.get("manual_or_lossy", []), *_engine_manual_gaps(engine_ir)]
    deduplicated_gaps: list[dict[str, Any]] = []
    seen_features: set[tuple[str, str]] = set()
    for item in combined_gaps:
        key = (str(item.get("feature", "")), str(item.get("handling", "")))
        if key not in seen_features:
            seen_features.add(key)
            deduplicated_gaps.append(item)
    capabilities["manual_or_lossy"] = deduplicated_gaps
    report = {
        "engine": engine,
        "adapter_version": DESIGN_SCHEMA_VERSION,
        "generated_at": _now(),
        **capabilities,
        "guarantee": "Generated files are implementation handoff scaffolds; runtime bindings and project-specific assets remain explicit manual work.",
    }
    _write_json(output / "capability-report.json", report)
    manifest = {
        "engine": engine,
        "generated_at": _now(),
        "source_hashes": engine_ir.get("source_hashes", {}),
        "outputs": {},
    }
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "export-manifest.json":
            manifest["outputs"][_rel(output, path)] = _sha256(path)
    _write_json(output / "export-manifest.json", manifest)
    return report


def command_export_engine(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    engine = args.engine
    output = Path(args.output).resolve() if args.output else design_root / "build" / "exports" / engine
    if args.output and (output.exists() or output.is_symlink()):
        if not output.is_dir() or output.is_symlink():
            print(f"ERROR Refusing to replace a non-directory output path: {output}")
            return 1
        if any(output.iterdir()) and not args.force:
            raise SystemExit(f"Export directory is not empty: {output}. Use --force to refresh generated files.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=str(output.parent)))
    try:
        ir = compile_design_ir(design_root, project_root=_project_root(args))
        engine_ir = build_engine_ir(ir, release=args.release, screen_filter=args.screen)
        report = export_engine(engine_ir, engine, staging)
        _replace_generated_directory(staging, output)
    except (OSError, ValueError) as exc:
        if staging.exists() and staging.resolve().parent == output.parent.resolve():
            shutil.rmtree(staging)
        print(f"ERROR Cannot export: {exc}")
        return 1
    print(f"Exported {len(engine_ir['screens'])} screen(s) for {engine}: {output}")
    print(f"Manual/lossy capability notes: {len(report.get('manual_or_lossy', []))}")
    return 0


ANALYSIS_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ANALYSIS_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}


def _media_files(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        path = Path(raw).resolve()
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() in ANALYSIS_IMAGE_EXTS | ANALYSIS_VIDEO_EXTS and candidate not in seen:
                files.append(candidate)
                seen.add(candidate)
    return files


def _extract_video_frames(video: Path, output: Path, interval: float, limit: int) -> tuple[list[Path], str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return [], "ffmpeg was not found; install FFmpeg to extract video frames"
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{_slug(video.stem)}_%06d.jpg"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"fps=1/{interval}",
        "-frames:v",
        str(limit),
        "-q:v",
        "3",
        "-y",
        str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        return [], (result.stderr or "ffmpeg failed").strip()
    return sorted(output.glob(f"{_slug(video.stem)}_*.jpg")), ""


def _analysis_contact_sheet(output: Path, records: list[dict[str, Any]]) -> None:
    cards: list[str] = []
    for item in records:
        if item.get("media_type") != "image" or not item.get("absolute_path"):
            continue
        path = Path(item["absolute_path"])
        try:
            source = path.relative_to(output.parent).as_posix()
        except ValueError:
            source = path.as_uri()
        cards.append(
            f'<figure><img src="{escape(source, quote=True)}" alt="{escape(str(item.get("id")), quote=True)}">'
            f'<figcaption><code>{escape(str(item.get("id")))}</code><br>{escape(str(item.get("path")))}</figcaption></figure>'
        )
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'self' file:; img-src 'self' file: data:; style-src 'unsafe-inline'">
<title>UI reverse-engineering evidence</title><style>body{{background:#10151d;color:#eef3f8;font:14px system-ui;margin:24px}}h1{{color:#f1c75b}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}figure{{margin:0;padding:9px;background:#1b2633;border:1px solid #394b60;border-radius:9px}}img{{width:100%;height:auto;display:block}}figcaption{{padding-top:7px;word-break:break-word}}code{{color:#64dcc7}}</style></head>
<body><h1>UI reverse-engineering evidence</h1><p>{len(cards)} unique frame/image candidate(s). Facts, inferences, and unknowns must remain separate.</p><main>{''.join(cards)}</main></body></html>'''
    _write_text(output, html)


def _analysis_prompt(packet_path: Path, packet: dict[str, Any]) -> str:
    packet_sha256 = _sha256(packet_path)
    return f"""# Game UI reverse-engineering task

Analyze the evidence listed in `{packet_path.name}` and produce JSON only. Treat visual output as design input, not proof of hidden runtime behavior.

## Non-negotiable evidence rules

- `observed`: directly visible in a cited evidence image/frame.
- `inferred`: a reasoned interpretation; include confidence and a transfer/ambiguity note.
- `unknown`: cannot be established visually, such as whether gameplay pauses, initial gamepad focus, cancellation, network failure, or the canonical runtime event name.
- Every claim must cite one or more evidence IDs from the packet.
- Never promote the result beyond `draft`.
- Do not invent GDD fields, events, API names, input mappings, timings, or measurements.

## Required output shape

```json
{{
  "analysis_schema_version": "1.0",
  "provider": "<provider>",
  "model": "<model>",
  "prompt_version": "reverse-engineer/1.0",
  "input_sha256": "{packet_sha256}",
  "screens": [
    {{
      "id": "screen-id",
      "name": "Screen name",
      "purpose": "Visible or carefully inferred purpose",
      "player_goal": "",
      "evidence_ids": ["evidence-0001"],
      "claims": [
        {{"classification": "observed", "claim": "...", "confidence": 1.0, "evidence_ids": ["evidence-0001"]}},
        {{"classification": "unknown", "claim": "Whether gameplay pauses", "confidence": 0.0, "evidence_ids": ["evidence-0001"]}}
      ],
      "elements": [
        {{
          "id": "A1", "name": "Element", "type": "rect",
          "rect": {{"x": 0, "y": 0, "width": 100, "height": 60}},
          "states": {{"default": {{}}}}, "data_bindings": [], "interactions": [],
          "accessibility": {{"label": "", "non_color_cues": []}}, "acceptance": [],
          "reference_ids": []
        }}
      ]
    }}
  ]
}}
```

Packet metadata: {len(packet.get('evidence', []))} evidence item(s), generated {packet.get('generated_at')}, SHA-256 `{packet_sha256}`.
"""


def command_analyze_media(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    if not isinstance(args.interval, (int, float)) or not math.isfinite(args.interval) or args.interval <= 0:
        raise SystemExit("--interval must be a finite number greater than 0.")
    if not isinstance(args.frame_limit, int) or args.frame_limit < 1:
        raise SystemExit("--frame-limit must be at least 1.")
    files = _media_files(args.input)
    if not files:
        raise SystemExit("No supported screenshots or videos found.")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = Path(args.output).resolve() if args.output else design_root / "analysis" / run_id
    if output.exists() or output.is_symlink():
        if not output.is_dir() or output.is_symlink():
            print(f"ERROR Refusing to replace a non-directory analysis output path: {output}")
            return 1
        if any(output.iterdir()) and not args.force:
            raise SystemExit(f"Analysis directory is not empty: {output}. Use --force to refresh it.")
    output.mkdir(parents=True, exist_ok=True)
    project_root = _project_root(args)
    candidates: list[dict[str, Any]] = []
    extraction_errors: list[dict[str, str]] = []
    for source in files:
        if source.suffix.lower() in ANALYSIS_VIDEO_EXTS:
            frames, error_message = _extract_video_frames(source, output / "frames", args.interval, args.frame_limit)
            if error_message:
                extraction_errors.append({"video": _rel(project_root, source), "error": error_message})
            for index, frame in enumerate(frames):
                candidates.append(
                    {
                        "path": _rel(project_root, frame),
                        "absolute_path": str(frame),
                        "media_type": "image",
                        "origin": {"kind": "video_frame", "video": _rel(project_root, source), "timestamp_seconds": round(index * args.interval, 3)},
                    }
                )
            if not frames:
                candidates.append(
                    {
                        "path": _rel(project_root, source),
                        "absolute_path": str(source),
                        "media_type": "video",
                        "origin": {"kind": "video"},
                    }
                )
        else:
            candidates.append(
                {
                    "path": _rel(project_root, source),
                    "absolute_path": str(source),
                    "media_type": "image",
                    "origin": {"kind": "screenshot"},
                }
            )
    unique: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for item in candidates:
        path = Path(item["absolute_path"])
        content_hash = _sha256(path)
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        item["id"] = f"evidence-{len(unique) + 1:04d}"
        item["sha256"] = content_hash
        item["tags"] = sorted({token for token, needles in {
            "hud": ("hud", "combat", "battle"),
            "results": ("result", "reward", "complete"),
            "inventory": ("inventory", "equip", "item"),
            "menu": ("menu", "title", "setting"),
            "levelup": ("level", "upgrade", "skill"),
        }.items() if any(needle in item["path"].lower() for needle in needles)})
        try:
            from ui_ref_cli import image_dimensions  # loaded lazily to keep legacy commands independent
            dims = image_dimensions(path) if item["media_type"] == "image" else None
        except Exception:
            dims = None
        if dims:
            item["width"], item["height"] = dims
        unique.append(item)
    packet = {
        "analysis_schema_version": DESIGN_SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": _now(),
        "prompt_version": "reverse-engineer/1.0",
        "classification_contract": {
            "observed": "directly visible in cited evidence",
            "inferred": "reasoned interpretation with confidence and ambiguity note",
            "unknown": "not established by the evidence",
        },
        "evidence": [{key: value for key, value in item.items() if key != "absolute_path"} for item in unique],
        "extraction_errors": extraction_errors,
        "output_contract": "analysis-result.schema.json",
    }
    packet_path = output / "analysis-packet.json"
    _write_json(packet_path, packet)
    _write_text(output / "analysis-prompt.md", _analysis_prompt(packet_path, packet))
    _analysis_contact_sheet(output / "contact-sheet.html", unique)
    _write_json(
        output / "analysis-result.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Game UI reverse-engineering result",
            "type": "object",
            "required": ["analysis_schema_version", "provider", "model", "prompt_version", "input_sha256", "screens"],
            "properties": {
                "analysis_schema_version": {"const": DESIGN_SCHEMA_VERSION},
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "prompt_version": {"type": "string"},
                "input_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "screens": {"type": "array"},
            },
        },
    )
    print(f"Prepared {len(unique)} unique evidence item(s) for multimodal AI analysis: {packet_path}")
    print(f"Analysis prompt: {output / 'analysis-prompt.md'}")
    if extraction_errors:
        print(f"Warnings: {len(extraction_errors)} video extraction issue(s); see the packet.")
    return 0


def _validate_analysis_result(
    result: Any,
    evidence_ids: set[str],
    *,
    expected_prompt_version: str,
    expected_input_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(result, dict):
        return ["result root must be an object"]
    if result.get("analysis_schema_version") != DESIGN_SCHEMA_VERSION:
        errors.append(f"analysis_schema_version must be {DESIGN_SCHEMA_VERSION}")
    if not result.get("provider") or not result.get("model") or not result.get("prompt_version"):
        errors.append("provider, model, and prompt_version are required")
    if result.get("prompt_version") != expected_prompt_version:
        errors.append(f"prompt_version must match the packet: {expected_prompt_version}")
    if result.get("input_sha256") != expected_input_sha256:
        errors.append("input_sha256 does not match the exact analysis packet")
    if not isinstance(result.get("screens"), list):
        errors.append("screens must be an array")
        return errors
    seen_screen_ids: set[str] = set()
    for screen_index, screen in enumerate(result["screens"]):
        base = f"screens[{screen_index}]"
        if not isinstance(screen, dict) or not screen.get("id") or not screen.get("name"):
            errors.append(f"{base} needs id and name")
            continue
        portable_screen_id = _portable_id(str(screen["id"]), "screen")
        if portable_screen_id in seen_screen_ids:
            errors.append(f"{base}.id collides with another portable screen ID: {portable_screen_id}")
        seen_screen_ids.add(portable_screen_id)
        screen_evidence = screen.get("evidence_ids", [])
        if not isinstance(screen_evidence, list) or any(value not in evidence_ids for value in screen_evidence):
            errors.append(f"{base}.evidence_ids must contain only existing evidence IDs")
        for claim_index, claim in enumerate(screen.get("claims", []) or []):
            claim_base = f"{base}.claims[{claim_index}]"
            if not isinstance(claim, dict) or claim.get("classification") not in {"observed", "inferred", "unknown"}:
                errors.append(f"{claim_base} has an invalid classification")
                continue
            if not str(claim.get("claim", "")).strip():
                errors.append(f"{claim_base}.claim is required")
            cited = claim.get("evidence_ids", [])
            if not cited or any(value not in evidence_ids for value in cited):
                errors.append(f"{claim_base} must cite existing evidence IDs")
            confidence = claim.get("confidence")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                errors.append(f"{claim_base}.confidence must be between 0 and 1")
        elements = screen.get("elements", [])
        if not isinstance(elements, list):
            errors.append(f"{base}.elements must be an array")
            continue
        seen_ids: set[str] = set()
        for element_index, element in enumerate(elements):
            element_base = f"{base}.elements[{element_index}]"
            if not isinstance(element, dict):
                errors.append(f"{element_base} must be an object")
                continue
            element_id = element.get("id")
            if not isinstance(element_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", element_id):
                errors.append(f"{element_base}.id must be a safe immutable ID")
            elif element_id in seen_ids:
                errors.append(f"{element_base}.id is duplicated")
            else:
                seen_ids.add(element_id)
            if not str(element.get("name", "")).strip():
                errors.append(f"{element_base}.name is required")
            rect = element.get("rect")
            if not isinstance(rect, dict) or any(not isinstance(rect.get(key), (int, float)) for key in ("x", "y", "width", "height")):
                errors.append(f"{element_base}.rect needs numeric x, y, width, and height")
            elif not all(math.isfinite(float(rect[key])) for key in ("x", "y", "width", "height")) or rect["width"] <= 0 or rect["height"] <= 0:
                errors.append(f"{element_base}.rect must contain finite, positive dimensions")
            if element.get("data_bindings"):
                errors.append(f"{element_base}.data_bindings must stay empty; visual analysis cannot establish runtime field names")
            if element.get("interactions"):
                errors.append(f"{element_base}.interactions must stay empty; record inferred behavior as a claim/question")
            element_evidence = element.get("reference_ids", [])
            if not isinstance(element_evidence, list) or any(value not in evidence_ids for value in element_evidence):
                errors.append(f"{element_base}.reference_ids must contain only existing evidence IDs")
    return errors


def command_analysis_import(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    result_path = Path(args.result).resolve()
    packet_path = Path(args.packet).resolve()
    result = _read_json(result_path)
    packet = _read_json(packet_path)
    project_root = _project_root(args)
    raw_evidence = packet.get("evidence", []) if isinstance(packet, dict) else []
    packet_errors: list[str] = []
    if not isinstance(raw_evidence, list):
        packet_errors.append("packet.evidence must be an array")
        raw_evidence = []
    evidence_ids: set[str] = set()
    for index, item in enumerate(raw_evidence):
        base = f"packet.evidence[{index}]"
        if not isinstance(item, dict):
            packet_errors.append(f"{base} must be an object")
            continue
        evidence_id = item.get("id")
        if not isinstance(evidence_id, str) or not evidence_id:
            packet_errors.append(f"{base}.id must be a non-empty string")
            continue
        if evidence_id in evidence_ids:
            packet_errors.append(f"{base}.id is duplicated")
            continue
        evidence_ids.add(evidence_id)
        raw_path = item.get("path")
        expected_hash = item.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            packet_errors.append(f"{base}.path must be a non-empty local path")
            continue
        evidence_path = Path(raw_path)
        evidence_path = evidence_path.resolve() if evidence_path.is_absolute() else (project_root / evidence_path).resolve()
        if not evidence_path.is_file():
            packet_errors.append(f"{base}.path is missing: {raw_path}")
            continue
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            packet_errors.append(f"{base}.sha256 must be a lowercase SHA-256 digest")
            continue
        if _sha256(evidence_path) != expected_hash:
            packet_errors.append(f"{base}.sha256 no longer matches the evidence file")
            continue
    if packet_errors:
        for message in packet_errors:
            print(f"ERROR {message}")
        return 1
    packet_sha256 = _sha256(packet_path)
    errors = _validate_analysis_result(
        result,
        evidence_ids,
        expected_prompt_version=str(packet.get("prompt_version", "")),
        expected_input_sha256=packet_sha256,
    )
    if errors:
        for message in errors:
            print(f"ERROR {message}")
        return 1

    # Complete every destructive preflight before adding evidence or writing a
    # single contract. AI imports may refresh only a never-reviewed draft.
    import_candidates: list[tuple[dict[str, Any], Path, Path]] = []
    for raw_screen in result.get("screens", []):
        screen_id = _portable_id(str(raw_screen.get("id")), "screen")
        output = design_root / "screens" / f"{screen_id}.json"
        wireframe_output = design_root / "wireframes" / f"{screen_id}.uiwire"
        if output.exists() or output.is_symlink():
            if not output.is_file() or output.is_symlink():
                print(f"ERROR Existing screen target is not a regular file; no files were changed: {output}")
                return 1
            if not args.force:
                print(f"SKIPPED existing screen: {output}")
                continue
            try:
                existing = _read_json(output)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"ERROR Existing screen cannot be safely replaced: {output}: {exc}")
                return 1
            if not isinstance(existing, dict) or existing.get("status") != "draft" or existing.get("review_history"):
                print(f"ERROR --force can replace only an unreviewed draft screen; preserved existing contract: {output}")
                return 1
        if wireframe_output.exists() or wireframe_output.is_symlink():
            if not wireframe_output.is_file() or wireframe_output.is_symlink():
                print(f"ERROR Existing wireframe target is not a regular file; no files were changed: {wireframe_output}")
                return 1
            if not output.exists() and not args.force:
                print(f"ERROR Orphan wireframe already exists; use --force only after reviewing it: {wireframe_output}")
                return 1
        import_candidates.append((raw_screen, output, wireframe_output))

    refs_path = design_root / "references.json"
    try:
        refs = _read_json(refs_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR Existing reference catalog is invalid; no files were changed: {exc}")
        return 1
    if not isinstance(refs, dict) or refs.get("kind") != "references" or not isinstance(refs.get("sources"), list):
        print("ERROR Existing reference catalog has an invalid root shape; no files were changed.")
        return 1
    existing_refs: dict[str, dict[str, Any]] = {}
    for source_index, source in enumerate(refs["sources"]):
        if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not source.get("id"):
            print(f"ERROR Existing reference catalog has an invalid source at index {source_index}; no files were changed.")
            return 1
        if source["id"] in existing_refs:
            print(f"ERROR Existing reference catalog has duplicate ID {source['id']!r}; no files were changed.")
            return 1
        existing_refs[source["id"]] = source
    evidence_to_ref: dict[str, str] = {}
    run_id = str(packet.get("run_id") or "run")
    for item in raw_evidence:
        evidence_id = str(item["id"])
        evidence_identity = "\0".join((packet_sha256, evidence_id, str(item.get("path", "")), str(item.get("sha256", ""))))
        identity_suffix = hashlib.sha256(evidence_identity.encode("utf-8")).hexdigest()[:16]
        ref_id = f"analysis-{_portable_id(run_id, 'run')[:32]}-{_portable_id(evidence_id, 'evidence')[:32]}-{identity_suffix}"
        evidence_to_ref[evidence_id] = ref_id
        expected_identity = {
            "source_type": "analysis_evidence",
            "uri": item.get("path", ""),
            "sha256": item.get("sha256", ""),
            "analysis_run": run_id,
            "analysis_packet_sha256": packet_sha256,
            "packet_evidence_id": evidence_id,
        }
        existing_source = existing_refs.get(ref_id)
        if existing_source is not None:
            mismatched = [key for key, value in expected_identity.items() if existing_source.get(key) != value]
            if mismatched:
                print(f"ERROR Analysis evidence ID collision for {ref_id}; mismatched fields: {', '.join(mismatched)}. No files were changed.")
                return 1
            continue
        source = {
            "id": ref_id,
            **expected_identity,
            "title": evidence_id,
            "rights": "inherits-source-rights",
            "captured_at": packet.get("generated_at", ""),
            "sync_state": "present",
            "verification": "sha256-and-packet-verified-at-import",
            "verified_at": _now(),
            "evidence_notes": [],
        }
        refs["sources"].append(source)
        existing_refs[ref_id] = source

    widths = [item.get("width") for item in raw_evidence if isinstance(item, dict)]
    heights = [item.get("height") for item in raw_evidence if isinstance(item, dict)]
    width = max((int(value) for value in widths if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 16384), default=1920)
    height = max((int(value) for value in heights if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 16384), default=1080)
    known_screens = {path.stem for path in _json_files(design_root / "screens")}
    known_screens.update(path.stem for _, path, _ in import_candidates)
    screen_scenarios: dict[str, set[str]] = {}
    for existing_screen_path in _json_files(design_root / "screens"):
        try:
            existing_screen = _read_json(existing_screen_path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(existing_screen, dict):
            screen_scenarios[existing_screen_path.stem] = _screen_scenario_names(existing_screen)
    component_statuses: dict[str, str] = {}
    for component_path in _json_files(design_root / "components"):
        try:
            component = _read_json(component_path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(component, dict) and isinstance(component.get("id"), str):
            component_statuses[component["id"]] = str(component.get("status", ""))
    known_refs = set(existing_refs)
    prepared: list[tuple[Path, str]] = []
    for raw_screen, output, wireframe_output in import_candidates:
        screen_id = output.stem
        elements = json.loads(json.dumps(raw_screen.get("elements", []))) if isinstance(raw_screen.get("elements"), list) else []
        for element in elements:
            if isinstance(element, dict):
                element["reference_ids"] = [
                    evidence_to_ref[value]
                    for value in element.get("reference_ids", [])
                    if value in evidence_to_ref
                ]
        screen = _screen_template(screen_id, str(raw_screen.get("name")), width, height, f"{result.get('provider')}/{result.get('model')}")
        screen["purpose"] = raw_screen.get("purpose", "")
        screen["player_goal"] = raw_screen.get("player_goal", "")
        screen["elements"] = elements
        screen["analysis_claims"] = raw_screen.get("claims", [])
        cited = set(raw_screen.get("evidence_ids", []) or [])
        for claim in raw_screen.get("claims", []) or []:
            if isinstance(claim, dict):
                cited.update(claim.get("evidence_ids", []) or [])
                if claim.get("classification") in {"inferred", "unknown"}:
                    screen["provenance"]["assumptions"].append(str(claim.get("claim", "")))
        screen["reference_ids"] = [evidence_to_ref[value] for value in sorted(cited) if value in evidence_to_ref]
        screen["provenance"]["source_files"] = [_rel(_project_root(args), result_path), _rel(_project_root(args), packet_path)]
        screen["provenance"]["analysis"] = {
            "provider": result.get("provider"),
            "model": result.get("model"),
            "prompt_version": result.get("prompt_version"),
            "input_sha256": result.get("input_sha256"),
        }
        candidate_screen_scenarios = dict(screen_scenarios)
        candidate_screen_scenarios[screen_id] = _screen_scenario_names(screen)
        screen_issues: list[ValidationIssue] = []
        _validate_screen(
            output,
            screen,
            known_refs,
            set(),
            known_screens,
            candidate_screen_scenarios,
            component_statuses,
            set(),
            QUALITY_GATE_DEFAULTS,
            screen_issues,
            False,
        )
        screen_errors = [item for item in screen_issues if item.severity == "error"]
        if screen_errors:
            for item in screen_errors:
                print(f"ERROR [{item.code}] {item.path}: {item.message}")
            print("AI import was rejected before writing any files.")
            return 1
        try:
            wireframe = _wireframe_from_screen(screen)
            _node_rects(parse_uiwire(wireframe))
        except ValueError as exc:
            print(f"ERROR Cannot generate a valid wireframe for {screen_id}: {exc}. No files were changed.")
            return 1
        prepared.extend(((output, _json_text(screen)), (wireframe_output, wireframe)))

    try:
        _write_text_transaction([(refs_path, _json_text(refs)), *prepared])
    except (OSError, ValueError) as exc:
        print(f"ERROR AI import transaction failed; prior files were preserved: {exc}")
        return 1
    print(f"Imported {len(import_candidates)} AI-analyzed screen draft(s). All remain draft pending human review.")
    return 0


def command_design_import_references(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    imported = _import_reference_manifest(_project_root(args), design_root)
    print(f"Synchronized {imported} local reference item(s) into: {design_root / 'references.json'}")
    print("Existing IDs and human evidence notes were preserved; missing files were marked, not deleted.")
    return 0


def command_design_check(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    issues, summary = validate_design_workspace(design_root, strict=args.strict, project_root=_project_root(args))
    wire_errors: list[dict[str, str]] = []
    owned_wireframes: set[Path] = set()
    for screen_path in _json_files(design_root / "screens"):
        path = screen_path
        try:
            screen = _read_json(screen_path)
            wireframe_value = screen.get("wireframe")
            if not wireframe_value:
                continue
            path = _resolve_design_path(design_root, str(wireframe_value), f"screen {screen.get('id')} wireframe")
            owned_wireframes.add(path)
            if not path.is_file():
                raise ValueError("declared wireframe source is missing")
            document = parse_uiwire(_read_text(path))
            actual_rects = _node_rects(document)
            expected_document = parse_uiwire(_wireframe_from_screen(screen))
            expected_rects = _node_rects(expected_document)
            actual_nodes = {node.node_id: node for node in document.nodes}
            expected_nodes = {node.node_id: node for node in expected_document.nodes}
            differences: list[str] = []
            if (document.width, document.height) != (expected_document.width, expected_document.height):
                differences.append("canvas")
            if set(actual_nodes) != set(expected_nodes):
                differences.append("element IDs")
            for node_id in sorted(set(actual_nodes) & set(expected_nodes)):
                actual_node = actual_nodes[node_id]
                expected_node = expected_nodes[node_id]
                if actual_node.kind != expected_node.kind:
                    differences.append(f"{node_id}.type")
                if actual_node.attrs.get("parent") != expected_node.attrs.get("parent"):
                    differences.append(f"{node_id}.parent")
                if any(abs(left - right) > 0.01 for left, right in zip(actual_rects[node_id], expected_rects[node_id])):
                    differences.append(f"{node_id}.rect")
            if differences:
                raise ValueError(f"contract geometry/type drift: {', '.join(differences)}; regenerate with `ui-ref wireframe new {screen.get('id')} --force`")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            wire_errors.append({"path": str(path), "message": str(exc)})
            print(f"ERROR [wireframe.invalid] {path}: {exc}")
    for path in sorted((design_root / "wireframes").glob("*.uiwire")):
        resolved_path = path.resolve()
        if resolved_path in owned_wireframes:
            continue
        try:
            document = parse_uiwire(_read_text(path))
            _node_rects(document)
            raise ValueError("wireframe source is not owned by a screen contract")
        except (OSError, ValueError) as exc:
            wire_errors.append({"path": str(path), "message": str(exc)})
            print(f"ERROR [wireframe.orphan] {path}: {exc}")
    stale_build: dict[str, Any] = {
        "checked": False,
        "stale_sources": [],
        "removed_sources": [],
        "changed_outputs": [],
        "missing_outputs": [],
        "orphaned_wireframes": [],
    }
    manifest_path = design_root / "build" / "build-manifest.json"
    if manifest_path.exists():
        stale_build["checked"] = True
        manifest = _read_json(manifest_path)
        try:
            current_ir = compile_design_ir(design_root, require_valid=False, project_root=_project_root(args))
            recorded = manifest.get("source_hashes", {})
            current = current_ir.get("source_hashes", {})
            stale_build["stale_sources"] = sorted(path for path, value in current.items() if recorded.get(path) != value)
            stale_build["removed_sources"] = sorted(path for path in recorded if path not in current)
            recorded_outputs = manifest.get("outputs", {}) if isinstance(manifest.get("outputs"), dict) else {}
            for relative, expected_hash in recorded_outputs.items():
                try:
                    output_path = _resolve_design_path(design_root / "build", str(relative), "build manifest output")
                except ValueError as exc:
                    stale_build.setdefault("manifest_errors", []).append(str(exc))
                    continue
                if not output_path.is_file():
                    stale_build["missing_outputs"].append(str(relative))
                elif _sha256(output_path) != expected_hash:
                    stale_build["changed_outputs"].append(str(relative))
            expected_wireframes = {str(path).replace("\\", "/") for path in recorded_outputs if str(path).startswith("wireframes/")}
            actual_wireframes = {
                _rel(design_root / "build", path)
                for path in (design_root / "build" / "wireframes").glob("*.svg")
                if path.is_file()
            }
            stale_build["orphaned_wireframes"] = sorted(actual_wireframes - expected_wireframes)
        except ValueError as exc:
            stale_build["error"] = str(exc)
    errors = int(summary.get("errors", 0)) + len(wire_errors)
    report = {
        **summary,
        "checked_at": _now(),
        "wireframes": {"checked": len(list((design_root / "wireframes").glob("*.uiwire"))), "errors": wire_errors},
        "build_drift": stale_build,
        "issues": [item.as_dict() for item in issues],
        "total_errors": errors,
    }
    _write_json(design_root / "build" / "check-report.json", report)
    drift_count = sum(
        len(stale_build.get(key, []))
        for key in ("stale_sources", "removed_sources", "changed_outputs", "missing_outputs", "orphaned_wireframes", "manifest_errors")
    )
    print(f"Design check: {errors} error(s), {summary.get('warnings', 0)} warning(s), {drift_count} built-source drift item(s).")
    if drift_count:
        print("Generated outputs are stale; run `ui-ref spec build --force` after reviewing source changes.")
    return 1 if errors or drift_count else 0


def command_design_trace(args: argparse.Namespace) -> int:
    design_root = _design_root(args)
    _ensure_workspace(design_root)
    path = _find_artifact(design_root, args.kind, args.artifact_id)
    artifact = _read_json(path)
    refs = _read_json(design_root / "references.json")
    ref_map = {str(item.get("id")): item for item in refs.get("sources", []) if isinstance(item, dict)}
    approvals = _read_json(design_root / "approvals.json")
    reference_ids: set[str] = set(artifact.get("reference_ids", []) or [])
    bindings: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for element in artifact.get("elements", []) if isinstance(artifact.get("elements"), list) else []:
        if not isinstance(element, dict):
            continue
        reference_ids.update(element.get("reference_ids", []) or [])
        bindings.extend(item for item in element.get("data_bindings", []) or [] if isinstance(item, dict))
        inputs.extend(item for item in element.get("interactions", []) or [] if isinstance(item, dict))
    trace = {
        "artifact": {
            "kind": artifact.get("kind"),
            "id": artifact.get("id"),
            "status": artifact.get("status"),
            "revision": artifact.get("revision"),
            "content_sha256": _sha256(path),
        },
        "references": [ref_map[value] for value in sorted(reference_ids) if value in ref_map],
        "missing_reference_ids": sorted(value for value in reference_ids if value not in ref_map),
        "data_bindings": bindings,
        "interactions": inputs,
        "approvals": [
            item for item in approvals.get("approvals", [])
            if isinstance(item, dict) and item.get("artifact_kind") == artifact.get("kind") and item.get("artifact_id") == artifact.get("id")
        ],
        "dependency_sha256": _dependency_snapshot(design_root, artifact),
    }
    if args.output:
        output = Path(args.output).resolve()
        _write_json(output, trace)
        print(f"Traceability report: {output}")
    else:
        print(json.dumps(trace, ensure_ascii=False, indent=2))
    return 1 if trace["missing_reference_ids"] else 0


def _add_output_force(parser: argparse.ArgumentParser, *, output_help: str) -> None:
    parser.add_argument("--output", default=None, help=output_help)
    parser.add_argument("--force", action="store_true", help="Replace generated output at the exact target.")


def register_design_commands(sub: Any) -> None:
    """Register the structured-design command families on the root parser."""
    spec = sub.add_parser("spec", aliases=["design"], help="Author, validate, approve, and compile game UX/UI contracts.")
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)

    init = spec_sub.add_parser("init", help="Create the canonical ui_design contract workspace.")
    init.add_argument("--project-id", default=None, help="Stable project ID. Default: slug of project name/root.")
    init.add_argument("--project-name", default=None, help="Project display name.")
    init.add_argument("--platform", action="append", default=[], help="Target platform. Repeatable; default pc.")
    init.add_argument("--input-device", action="append", default=[], help="Required input device ID. Repeatable; default keyboard_mouse + gamepad.")
    init.add_argument("--aspect-ratio", action="append", default=[], help="Target aspect ratio. Repeatable; default 16:9.")
    init.add_argument("--locale", default="en", help="Default locale. Default: en.")
    init.add_argument("--no-import-references", action="store_true", help="Do not import an existing local reference manifest.")
    init.add_argument("--force", action="store_true", help="Refresh project metadata without deleting authored contracts or notes.")
    init.set_defaults(func=command_design_init)

    add_screen = spec_sub.add_parser("add-screen", help="Create a draft screen contract.")
    add_screen.add_argument("name", help="Screen display name.")
    add_screen.add_argument("--id", dest="screen_id", default=None, help="Stable screen ID. Default: slug of name.")
    add_screen.add_argument("--width", type=int, default=1920, help="Reference viewport width.")
    add_screen.add_argument("--height", type=int, default=1080, help="Reference viewport height.")
    add_screen.add_argument("--author", default="human", help="Initial author name/type.")
    add_screen.add_argument("--wireframe", action="store_true", help="Also create a starter .uiwire file.")
    add_screen.add_argument("--force", action="store_true", help="Replace the exact draft screen file.")
    add_screen.set_defaults(func=command_design_new_screen)

    add_component = spec_sub.add_parser("add-component", help="Create a draft reusable component contract.")
    add_component.add_argument("name", help="Component display name.")
    add_component.add_argument("--id", dest="component_id", default=None, help="Stable component ID. Default: slug of name.")
    add_component.add_argument("--author", default="human", help="Initial author name/type.")
    add_component.add_argument("--force", action="store_true", help="Replace the exact draft component file.")
    add_component.set_defaults(func=command_design_new_component)

    validate = spec_sub.add_parser("validate", help="Validate contracts, references, lifecycle gates, and flows.")
    validate.add_argument("--strict", action="store_true", help="Apply review-grade completeness checks to every draft too.")
    validate.add_argument("--output", default=None, help="Validation JSON path. Default: ui_design/build/validation-report.json.")
    validate.set_defaults(func=command_design_validate)

    check = spec_sub.add_parser("check", help="Run contract, approval, wireframe, and generated-output drift checks.")
    check.add_argument("--strict", action="store_true", help="Apply review-grade checks to every draft too.")
    check.set_defaults(func=command_design_check)

    compile_parser = spec_sub.add_parser("compile", help="Compile validated contracts into canonical engine-neutral Design IR.")
    _add_output_force(compile_parser, output_help="IR JSON path. Default: ui_design/build/design.ir.json.")
    compile_parser.set_defaults(func=command_design_compile)

    build = spec_sub.add_parser("build", help="Generate Design IR, annotated wireframes, Markdown, and readable HTML.")
    _add_output_force(build, output_help="Build directory. Default: ui_design/build.")
    build.set_defaults(func=command_design_build)

    promote = spec_sub.add_parser("promote", help="Move a screen/component through draft -> reviewed -> approved with a hash ledger.")
    promote.add_argument("kind", choices=["screen", "component"])
    promote.add_argument("artifact_id", help="Stable screen/component ID.")
    promote.add_argument("--to", required=True, choices=list(STATUS_ORDER), help="Target lifecycle status.")
    promote.add_argument("--by", required=True, help="Named reviewer/author recorded in the ledger.")
    promote.add_argument("--note", required=True, help="Reason and review scope.")
    promote.add_argument("--human-confirmed", action="store_true", help="Required for final approved status after explicit human approval.")
    promote.set_defaults(func=command_design_transition)

    trace = spec_sub.add_parser("trace", help="Show evidence, binding, interaction, approval, and dependency traceability.")
    trace.add_argument("kind", choices=["screen", "component"])
    trace.add_argument("artifact_id")
    trace.add_argument("--output", default=None, help="Optional JSON report path; otherwise print to stdout.")
    trace.set_defaults(func=command_design_trace)

    import_refs = spec_sub.add_parser("import-references", help="Synchronize scan-local evidence into the contract catalog.")
    import_refs.set_defaults(func=command_design_import_references)

    wireframe = sub.add_parser("wireframe", help="Create, lint, and deterministically render AI-friendly .uiwire sources.")
    wire_sub = wireframe.add_subparsers(dest="wireframe_command", required=True)
    wire_new = wire_sub.add_parser("new", help="Generate .uiwire source from a screen contract.")
    wire_new.add_argument("screen_id")
    _add_output_force(wire_new, output_help="Optional .uiwire output path.")
    wire_new.set_defaults(func=command_wireframe_new)
    wire_lint = wire_sub.add_parser("lint", help="Parse and structurally validate a .uiwire file.")
    wire_lint.add_argument("input")
    wire_lint.set_defaults(func=command_wireframe_lint)
    wire_render = wire_sub.add_parser("render", help="Render a .uiwire file to standalone annotated SVG.")
    wire_render.add_argument("input")
    _add_output_force(wire_render, output_help="SVG output. Default: source path with .svg extension.")
    wire_render.set_defaults(func=command_wireframe_render)

    prototype = sub.add_parser("prototype", help="Build a contract-driven clickable UX prototype.")
    prototype_sub = prototype.add_subparsers(dest="prototype_command", required=True)
    prototype_build = prototype_sub.add_parser("build", help="Build static HTML/CSS/JS with screen, state, keyboard, and gamepad flows.")
    _add_output_force(prototype_build, output_help="Prototype directory. Default: ui_design/build/prototype.")
    prototype_build.add_argument("--release", action="store_true", help="Require every exported screen to have a current human approval.")
    prototype_build.set_defaults(func=command_prototype_build)

    analyze = sub.add_parser("analyze", help="Prepare and import evidence-bounded multimodal AI reverse-engineering runs.")
    analyze_sub = analyze.add_subparsers(dest="analyze_command", required=True)
    analyze_media = analyze_sub.add_parser("media", help="Extract/dedupe screenshots or video frames and create an AI analysis packet.")
    analyze_media.add_argument("input", nargs="+", help="Screenshot, video, or directory inputs.")
    analyze_media.add_argument("--interval", type=float, default=2.0, help="Video frame interval in seconds. Default: 2.")
    analyze_media.add_argument("--frame-limit", type=int, default=120, help="Maximum frames extracted per video. Default: 120.")
    _add_output_force(analyze_media, output_help="Analysis run directory. Default: ui_design/analysis/<timestamp>.")
    analyze_media.set_defaults(func=command_analyze_media)
    analyze_import = analyze_sub.add_parser("import", help="Validate a multimodal AI result and import draft-only screen contracts.")
    analyze_import.add_argument("result", help="AI analysis result JSON.")
    analyze_import.add_argument("--packet", required=True, help="The exact analysis-packet.json used by the model.")
    analyze_import.add_argument("--force", action="store_true", help="Replace exact draft screen IDs; never promotes status.")
    analyze_import.set_defaults(func=command_analysis_import)

    export_parser = sub.add_parser("export", help="Generate explicit game-engine handoff scaffolds from Design IR.")
    export_sub = export_parser.add_subparsers(dest="engine", required=True)
    for engine in ENGINE_CHOICES:
        engine_parser = export_sub.add_parser(engine, help=f"Export {engine} handoff files and a capability report.")
        _add_output_force(engine_parser, output_help=f"Export directory. Default: ui_design/build/exports/{engine}.")
        engine_parser.add_argument("--screen", default=None, help="Export one screen ID instead of all screens.")
        engine_parser.add_argument("--release", action="store_true", help="Require current human approval for every exported screen.")
        engine_parser.set_defaults(func=command_export_engine, engine=engine)
