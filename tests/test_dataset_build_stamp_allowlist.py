"""The three dataset validators must tolerate the pipeline's build stamp.

`build.json` sits next to a dataset's manifest. It is written by the daily
pipeline (L5-T02/T04), not declared in the dataset's own manifest. Before this
test, personas / insights / reports validators treated it as an undeclared file,
so the next out-of-band rebuild would fail after the data had been published.

These tests exercise the allowlist mechanism plus the insights writer. The
persona validator needs a full 14-file snapshot, so its allowlist helper is
tested directly; the reports validator's inventory function is tested with a
minimal directory.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_persona_allowlist_includes_manifest_and_build_stamp() -> None:
    from reddit_voc.v3_persona_snapshot import _allowed_root_files

    allowed = _allowed_root_files({"personas.json"})
    assert "personas.json" in allowed
    assert "manifest.json" in allowed
    assert "build.json" in allowed
    assert "extra.json" not in allowed


def test_insights_wrapper_accepts_a_build_stamp(tmp_path: Path) -> None:
    module = _load_script("build_reddit_insights_snapshot")
    output = tmp_path / "insights"
    output.mkdir()
    (output / "build.json").write_text('{"schema_version":"stamp"}\n', encoding="utf-8")

    module.write_v3_public_insights_wrapper(
        output,
        {"schema_version": "demo"},
        {"schema_version": "demo"},
        {"schema_version": "demo"},
    )

    assert (output / "build.json").is_file()
    assert (output / "insights.json").is_file()
    assert (output / "manifest.json").is_file()
    assert (output / "validation-receipt.json").is_file()


def test_reports_inventory_allows_a_build_stamp(tmp_path: Path) -> None:
    module = _load_script("build_reddit_reports_snapshot")
    root = tmp_path / "reports"
    root.mkdir()
    (root / "a.json").write_text("{}\n", encoding="utf-8")
    (root / "build.json").write_text("{}\n", encoding="utf-8")

    module._v3_assert_output_inventory(
        root,
        {"a.json"},
        "demo reports",
        exact=True,
        allowed_extra_files={"build.json"},
    )


def test_reports_inventory_still_rejects_other_undeclared_files(tmp_path: Path) -> None:
    module = _load_script("build_reddit_reports_snapshot")
    root = tmp_path / "reports"
    root.mkdir()
    (root / "a.json").write_text("{}\n", encoding="utf-8")
    (root / "build.json").write_text("{}\n", encoding="utf-8")
    (root / "extra.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(module.V3ReportsBuildError, match="undeclared files"):
        module._v3_assert_output_inventory(
            root,
            {"a.json"},
            "demo reports",
            exact=True,
            allowed_extra_files={"build.json"},
        )