from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.dependency_security import _is_vulnerable, _parse_version, _normalize_package


def test_version_helpers_are_deterministic():
    assert _parse_version("2.28.0") == (2, 28, 0)
    assert _parse_version("v1.2.3-beta") == (1, 2, 3)
    assert _parse_version(None) is None
    assert _parse_version("not-a-version") is None

    # Strictly-below comparison against the advisory bound.
    assert _is_vulnerable("2.28.0", "2.32.0") is True
    assert _is_vulnerable("2.32.0", "2.32.0") is False
    assert _is_vulnerable("2.33.0", "2.32.0") is False
    assert _is_vulnerable(None, "2.32.0") is False

    assert _normalize_package("Django") == "django"
    assert _normalize_package("PyYAML") == "pyyaml"
    assert _normalize_package("some_pkg.name") == "some-pkg-name"


@pytest.mark.asyncio
async def test_dependency_security_flags_known_vulnerable_package(client: AsyncClient, tmp_path: Path):
    # requests 2.28.0 is below the 2.32.0 advisory bound -> must be flagged.
    (tmp_path / "requirements.txt").write_text(
        "requests==2.28.0\n"
        "flask==2.3.2\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text

    response = await client.get(
        f"/api/v1/repositories/{ingest.json()['id']}/security/dependencies"
    )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["dependencies_scanned"] >= 1
    assert result["advisories_checked"] > 0
    assert result["limitations"]

    flagged = {item["package_name"].lower(): item for item in result["risky_dependencies"]}
    assert "requests" in flagged
    assert flagged["requests"]["cve"] == "CVE-2024-35195"
    assert flagged["requests"]["recommendation"]

    # Severity counts must be internally consistent with the risk list.
    total_by_severity = (
        result["critical_count"]
        + result["high_count"]
        + result["medium_count"]
        + result["low_count"]
    )
    assert total_by_severity == len(result["risky_dependencies"])


@pytest.mark.asyncio
async def test_dependency_security_reports_clean_for_patched_versions(client: AsyncClient, tmp_path: Path):
    # requests 2.32.0 is at/above the bound -> must NOT be flagged.
    (tmp_path / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text

    response = await client.get(
        f"/api/v1/repositories/{ingest.json()['id']}/security/dependencies"
    )
    assert response.status_code == 200, response.text
    result = response.json()

    flagged_names = [item["package_name"].lower() for item in result["risky_dependencies"]]
    assert "requests" not in flagged_names
    assert result["critical_count"] == 0
    assert result["high_count"] == 0
