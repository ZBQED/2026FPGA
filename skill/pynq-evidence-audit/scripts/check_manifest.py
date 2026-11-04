"""Create or verify a portable SHA-256 inventory; does not execute project files."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def files(root, excluded):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinks unsupported: " + str(path))
        if path.is_file() and path.resolve() != excluded:
            if not path.resolve().is_relative_to(root):
                raise ValueError("file escapes root")
            result[path.relative_to(root).as_posix()] = path
    return result


def verify(root, manifest, strict=False, manifest_path=None):
    if manifest.get("schema") != "sha256-inventory-v1" or not manifest.get("files"):
        raise ValueError("unsupported or empty manifest")
    issues = []
    for name, entry in manifest["files"].items():
        relative = PurePosixPath(name)
        if not name or relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
            raise ValueError("unsafe relative path")
        path = root.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("manifest path escapes root or is a symlink")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise ValueError("invalid manifest digest or size")
        if not path.is_file():
            issues.append("missing: " + name)
        elif path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            issues.append("changed: " + name)
    if strict:
        extra = set(files(root, manifest_path)) - set(manifest["files"])
        issues.extend("unexpected: " + name for name in sorted(extra))
    return {"status": "passed" if not issues else "failed", "files": len(manifest["files"]),
            "issues": issues, "scope": "file integrity only; not rebuild reproducibility or trusted authorship"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        root, target = args.root.resolve(strict=True), args.manifest.resolve()
        if not root.is_dir():
            raise ValueError("root must be a directory")
        if args.action == "create":
            if target.exists():
                raise ValueError("manifest already exists")
            entries = files(root, target)
            if not entries:
                raise ValueError("empty project")
            manifest = {"schema": "sha256-inventory-v1", "files": {
                name: {"bytes": p.stat().st_size, "sha256": digest(p)} for name, p in entries.items()}}
            with target.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            report = {"status": "passed", "files": len(entries), "manifest": str(target)}
        else:
            report = verify(root, json.loads(target.read_text(encoding="utf-8-sig")), args.strict, target)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        report = {"status": "failed", "issues": [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
