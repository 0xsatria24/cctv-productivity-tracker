import json
from pathlib import Path

from cctv_tracker.cli import main


def test_repeatable_demo_registry_assignment_and_report_cli(tmp_path, capsys):
    common = ["--log-dir", str(tmp_path / "logs")]
    main([*common, "demo", "--output-dir", str(tmp_path / "demos")])
    first = json.loads(capsys.readouterr().out)
    main([*common, "demo", "--output-dir", str(tmp_path / "demos")])
    second = json.loads(capsys.readouterr().out)
    assert first["database"] != second["database"]
    assert Path(first["database"]).is_file() and Path(second["database"]).is_file()
    common += ["--database", first["database"]]
    main([*common, "employee-add", "Karyawan Contoh"])
    employee_id = json.loads(capsys.readouterr().out)["employee_id"]
    main([*common, "assign", "--employee", employee_id, "--workspace", first["workstations"][0]["workspace_id"],
          "--start", "2026-10-12T09:00:00+07:00", "--end", "2026-10-12T09:00:17+07:00"])
    assert json.loads(capsys.readouterr().out)["is_observed_identity"] is False
    main([*common, "report", "--start", "2026-10-12T09:00:00+07:00", "--end", "2026-10-12T09:00:17+07:00"])
    report = json.loads(capsys.readouterr().out)
    assert report["workstations"][0]["observed_employee_id"] is None
    assert report["workstations"][0]["workstation_assignments"][0]["display_name"] == "Karyawan Contoh"
