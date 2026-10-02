from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from scenario_db.api.schemas.arch_exploration import ArchReportRequest, ReportStatusRequest
from scenario_db.reporting.xlsx_export import report_sheets, write_xlsx


def test_write_xlsx_is_a_valid_package_with_typed_cells():
    data = write_xlsx([("요약 [1]", ["항목", "값"], [["power", 677.4], ["ok", True], ["text", "a<b & c"], ["blank", None]]),
                       ("요약 [1]", ["x"], [])])
    z = zipfile.ZipFile(io.BytesIO(data))
    assert {"xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/styles.xml"} <= set(z.namelist())
    wb = z.read("xl/workbook.xml").decode()
    assert 'name="요약 _1_"' in wb and wb.count("<sheet ") == 2  # sanitized and de-duplicated names
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<v>677.4</v>" in sheet and 't="b"' in sheet and "a&lt;b &amp; c" in sheet
    assert 'state="frozen"' in sheet and "<autoFilter" in sheet


def test_report_sheets_tolerate_old_snapshots():
    old = {"overview": {"target_soc": "soc", "model_limits": ["x"]}, "spec_summary": {"failed": [{"variant_id": "v", "reasons": ["r"]}]},
           "scenarios": [{"scenario_id": "s", "variant_id": "v", "fps": 30, "eis_on": False, "spec_ok": False, "power": {"total_mw": 1.0},
                          "distribution": {"total_mw": {"min": 1, "max": 2}}}]}
    names = [n for n, _, _ in report_sheets(old)]
    assert names[:4] == ["요약", "권고 조치", "Scenario", "Spec 미달"]
    assert write_xlsx(report_sheets(old))[:2] == b"PK"


def test_publish_requires_reviewer_and_note():
    with pytest.raises(ValidationError):
        ArchReportRequest(run_id="EXP-1", status="published")
    with pytest.raises(ValidationError):
        ReportStatusRequest(status="published")
    with pytest.raises(ValidationError):
        ReportStatusRequest(status="published", reviewer="Joo", note=" ")
    assert ReportStatusRequest(status="draft").status == "draft"
    assert ReportStatusRequest(status="published", reviewer="Joo", note="ok").reviewer == "Joo"


def test_sheet_names_escape_attributes_and_resolve_case_insensitive_collisions():
    data = write_xlsx([(name, ["x"], []) for name in ('a', 'a_2', 'a', 'A', 'quoted" & sheet', '\x01control')])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("xl/workbook.xml"))
    names = [s.attrib["name"] for s in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet")]
    assert len({n.casefold() for n in names}) == len(names)
    assert names[4:] == ['quoted" & sheet', 'control']
    assert all(len(n) <= 31 for n in names)
