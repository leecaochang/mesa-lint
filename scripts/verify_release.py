"""Check version agreement and exact source contents in both built artifacts."""

from __future__ import annotations

import ast
import os
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

root = Path(__file__).resolve().parents[1]
metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
name, version = metadata["name"], metadata["version"]
package = name.replace("-", "_")
module = ast.parse((root / package / "__init__.py").read_text(encoding="utf-8"))
module_version = next(
    ast.literal_eval(node.value)
    for node in module.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
)
assert module_version == version, (module_version, version)
if os.environ.get("GITHUB_REF_TYPE") == "tag":
    assert os.environ["GITHUB_REF_NAME"] == f"v{version}", "release tag must match package version"
wheels = list((root / "dist").glob("*.whl"))
sources = list((root / "dist").glob("*.tar.gz"))
assert len(wheels) == len(sources) == 1, "build into a clean dist directory"
with zipfile.ZipFile(wheels[0]) as wheel, tarfile.open(sources[0]) as source:
    prefix = source.getnames()[0].split("/")[0]
    source_names = set(source.getnames())
    wheel_metadata = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
    source_metadata = source.extractfile(f"{prefix}/PKG-INFO")
    assert source_metadata is not None
    for payload in (wheel.read(wheel_metadata), source_metadata.read()):
        built_metadata = BytesParser().parsebytes(payload)
        assert built_metadata["Version"] == version
        assert built_metadata["Name"] == name
    for directory in (package, "tests", "examples", "scripts", "documents"):
        for path in (root / directory).rglob("*"):
            if (
                not path.is_file()
                or path.name.startswith(".")
                or "__pycache__" in path.parts
                or path.suffix == ".pyc"
            ):
                continue
            relative = path.relative_to(root).as_posix()
            archived = source.extractfile(f"{prefix}/{relative}")
            assert archived is not None and archived.read() == path.read_bytes(), relative
            if directory == package:
                assert wheel.read(relative) == path.read_bytes(), relative
    for relative in ("pyproject.toml", "README.md", "CHANGELOG.md"):
        archived = source.extractfile(f"{prefix}/{relative}")
        assert archived is not None and archived.read() == (root / relative).read_bytes(), relative
    assert not any("/.venv/" in member or "/memory/" in member for member in source_names)
print(f"{name} {version}: wheel and sdist match the release sources")
