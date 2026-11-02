"""The closure matrix records evidence; it must never infer a close."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_v2_closure_matrix", ROOT / "scripts" / "build_v2_closure_matrix.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TICKETS = """# V2.0 票据台账

#### `L1-T01` first ticket
- **严重度**：P0｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **测试**：
  - `tests/test_a.py::test_one`

#### `L2-T02` second ticket
- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：1
- **测试**：
  - `tests/test_b.py::test_missing`

#### `L3-T03` third ticket
- **严重度**：P2｜**类型**：feature｜**工作量**：S｜**拓扑层**：1
- **测试**：无
"""


def test_matrix_records_evidence_and_never_closes(tmp_path: Path) -> None:
    module = _load()
    tests_root = tmp_path
    (tests_root / "tests").mkdir()
    (tests_root / "tests" / "test_a.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
    (tests_root / "tests" / "test_b.py").write_text("def test_other():\n    pass\n", encoding="utf-8")

    matrix = module.build_matrix(
        TICKETS,
        [
            ("abc123456789", "fix: L1-T01 something"),
            ("def456789012", "docs: L2-T02 something"),
        ],
        tests_root,
    )

    rows = {row["ticket_id"]: row for row in matrix["tickets"]}
    assert rows["L1-T01"]["evidence_status"] == "commit+named_test"
    assert rows["L1-T01"]["test_status"] == "present"
    assert rows["L2-T02"]["evidence_status"] == "commit_only"
    assert rows["L2-T02"]["test_status"] == "missing"
    assert rows["L3-T03"]["evidence_status"] == "none"
    assert all(row["owner_signoff"] is None for row in matrix["tickets"])
    assert matrix["summary"]["formally_closed"] == 0
    assert matrix["summary"]["total"] == 3
    assert matrix["summary"]["commit_referenced"] == 2
    assert matrix["summary"]["named_test_present"] == 1


def test_ticket_parser_reads_priority_and_tests() -> None:
    module = _load()
    tickets = module._ticket_blocks(TICKETS)
    assert [t["ticket_id"] for t in tickets] == ["L1-T01", "L2-T02", "L3-T03"]
    assert tickets[0]["priority"] == "P0"
    assert tickets[0]["lane"] == "L1"
    assert tickets[0]["named_tests"] == ["tests/test_a.py::test_one"]