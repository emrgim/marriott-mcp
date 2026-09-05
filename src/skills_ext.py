"""SEP-2640 Skills extension: skill:// resources, skills/list, skills/get."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
SCHEME = "skill://"


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValueError("SKILL.md missing YAML frontmatter")
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        raise ValueError("SKILL.md unclosed frontmatter")
    raw = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    fm: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = val.strip().strip('"').strip("'")
    if "name" not in fm or "description" not in fm:
        raise ValueError("frontmatter requires name and description")
    return fm, body


def _walk_files(skill_dir: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts or p.name.startswith("."):
            continue
        out.append(p)
    return out


def _mime(path: Path, is_dir: bool = False) -> str:
    if is_dir:
        return "inode/directory"
    if path.name == "SKILL.md" or path.suffix.lower() == ".md":
        return "text/markdown"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _digest_size(data: bytes) -> tuple[str, int]:
    return "sha256:" + hashlib.sha256(data).hexdigest(), len(data)


def _rel_uri(skill_name: str, rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    return f"{SCHEME}{skill_name}/{rel}"


def load_catalog() -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    if not SKILLS_DIR.is_dir():
        return skills
    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        manifest = skill_dir / "SKILL.md"
        if not manifest.is_file():
            continue
        text = manifest.read_text(encoding="utf-8")
        fm, _ = _parse_frontmatter(text)
        name = str(fm["name"])
        if name != skill_dir.name:
            raise ValueError(f"skill name {name!r} != directory {skill_dir.name!r}")
        resources = []
        files: dict[str, Path] = {}
        for fp in _walk_files(skill_dir):
            rel = fp.relative_to(skill_dir).as_posix()
            uri = _rel_uri(name, rel)
            data = fp.read_bytes()
            digest, size = _digest_size(data)
            resources.append({"uri": uri, "digest": digest, "size": size})
            files[uri] = fp
        skills.append(
            {
                "uri": _rel_uri(name, "SKILL.md"),
                "frontmatter": fm,
                "resources": resources,
                "_files": files,
                "_dir": skill_dir,
            }
        )
    return skills


def skill_entries() -> list[dict[str, Any]]:
    return [
        {"uri": s["uri"], "frontmatter": s["frontmatter"], "resources": s["resources"]}
        for s in load_catalog()
    ]


def get_entry(uri: str) -> dict[str, Any] | None:
    uri = (uri or "").strip()
    for s in load_catalog():
        if s["uri"] == uri:
            return {
                "uri": s["uri"],
                "frontmatter": s["frontmatter"],
                "resources": s["resources"],
            }
    return None


def all_file_resources() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in load_catalog():
        fm = s["frontmatter"]
        for rec in s["resources"]:
            path = s["_files"][rec["uri"]]
            item = {
                "uri": rec["uri"],
                "name": path.name,
                "mimeType": _mime(path),
            }
            if path.name == "SKILL.md":
                item["name"] = fm["name"]
                item["description"] = fm["description"]
                item["mimeType"] = "text/markdown"
            out.append(item)
    return out


def read_uri(uri: str) -> dict[str, Any] | None:
    uri = (uri or "").strip()
    for s in load_catalog():
        fp = s["_files"].get(uri)
        if fp is None:
            continue
        data = fp.read_bytes()
        mime = _mime(fp)
        if mime.startswith("text/") or fp.suffix.lower() in {".md", ".txt", ".json", ".yml", ".yaml"}:
            return {
                "uri": uri,
                "mimeType": mime,
                "text": data.decode("utf-8"),
            }
        import base64

        return {
            "uri": uri,
            "mimeType": mime,
            "blob": base64.standard_b64encode(data).decode("ascii"),
        }
    return None


def list_directory(uri: str) -> list[dict[str, Any]] | None:
    uri = (uri or "").rstrip("/")
    if not uri.startswith(SCHEME):
        return None
    rest = uri[len(SCHEME) :]
    parts = [p for p in rest.split("/") if p]
    if not parts:
        # skill:// root → skill directories
        kids = []
        for s in load_catalog():
            name = s["frontmatter"]["name"]
            kids.append(
                {
                    "uri": f"{SCHEME}{name}",
                    "name": name,
                    "mimeType": "inode/directory",
                }
            )
        return kids
    skill_name = parts[0]
    sub = "/".join(parts[1:])
    catalog = {s["frontmatter"]["name"]: s for s in load_catalog()}
    skill = catalog.get(skill_name)
    if skill is None:
        return None
    base: Path = skill["_dir"]
    target = base / sub if sub else base
    if not target.is_dir():
        return None
    kids: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: p.name):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        rel = child.relative_to(base).as_posix()
        child_uri = f"{SCHEME}{skill_name}/{rel}" if rel != "." else f"{SCHEME}{skill_name}"
        if child.is_dir():
            kids.append(
                {
                    "uri": f"{SCHEME}{skill_name}/{rel}",
                    "name": child.name,
                    "mimeType": "inode/directory",
                }
            )
        elif child.is_file():
            kids.append(
                {
                    "uri": child_uri,
                    "name": child.name,
                    "mimeType": _mime(child),
                }
            )
    return kids
