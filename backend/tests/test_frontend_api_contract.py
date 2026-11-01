"""Frontend ↔ backend API contract test.

Guards against the bug class where a frontend service calls a backend URL
that does not exist (for example ``/repositories/github`` when the real route
is ``/repositories/clone``). Such mismatches 404 at runtime yet are invisible
to backend-only test suites.

The check is static: it compares URL literals in ``frontend/services/*.ts``
against the live FastAPI route table.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.main import app

SERVICES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "services"

# `${repoId}` and `${encodeURIComponent(path)}` in JS template literals.
_TEMPLATE_EXPR = re.compile(r"\$\{[^{}]*\}")
# `{repo_id}` in FastAPI route paths.
_PARAM = re.compile(r"\{[^{}]*\}")


def _normalize(path: str) -> str:
    path = path.split("?")[0]
    path = _TEMPLATE_EXPR.sub("{}", path)
    path = _PARAM.sub("{}", path)
    return path.rstrip("/") or "/"


def _backend_paths() -> set[str]:
    """Return mounted API paths from the generated OpenAPI schema.

    Newer FastAPI versions keep included routers lazy (``_IncludedRouter``)
    until the schema or first request is resolved, so walking ``app.routes``
    directly misses every endpoint mounted with ``include_router``. The
    OpenAPI schema is the public contract and resolves nested includes.
    """
    paths: set[str] = set()
    for route_path in app.openapi().get("paths", {}):
        if not route_path.startswith("/api/v1"):
            continue
        paths.add(_normalize(route_path[len("/api/v1"):]))
    return paths


def _frontend_paths() -> dict[str, set[str]]:
    """Map normalized path -> names of service files that call it."""
    calls: dict[str, set[str]] = {}
    for file in sorted(SERVICES_DIR.glob("*.ts")):
        text = file.read_text(encoding="utf-8")
        found: list[str] = []
        # api.ts style: fetch(`${API_BASE}/path`, ...) and new URL(`${API_BASE}/path`)
        # Requires a literal "/" after API_BASE so the generic request() helper
        # interpolation (`${API_BASE}${path}`) is not mistaken for an endpoint.
        found += re.findall(r"`\$\{API_BASE\}(?P<path>/[^`]*)`", text)
        # intelligence.ts style: request<ResponseType>(`/path`, ...)
        found += re.findall(r"request\s*<[^`]{0,150}?>\s*\(\s*`(?P<path>/[^`]*)`", text)
        for raw in found:
            normalized = _normalize(raw)
            if not normalized.startswith("/"):
                normalized = "/" + normalized
            calls.setdefault(normalized, set()).add(file.name)
    return calls


def test_frontend_calls_only_existing_backend_routes():
    backend_paths = _backend_paths()
    frontend_paths = _frontend_paths()

    # Sanity: make sure the extractor actually found the service layer.
    assert len(frontend_paths) >= 30, (
        f"Contract scan found only {len(frontend_paths)} frontend paths — "
        "the extractor may be out of date with the services code."
    )

    missing = {
        path: sorted(files)
        for path, files in frontend_paths.items()
        if path not in backend_paths
    }
    details = "; ".join(
        f"{path} (used by {', '.join(files)})" for path, files in sorted(missing.items())
    )
    assert not missing, (
        "Frontend calls backend routes that do not exist and will 404 at runtime: "
        + details
    )


def test_ingestion_routes_match_backend_contract():
    """Pin the historically broken ingestion routes specifically."""
    backend_paths = _backend_paths()
    frontend_paths = _frontend_paths()

    # The canonical routes implemented in backend/app/api/v1/endpoints/repositories.py.
    assert "/repositories/clone" in backend_paths
    assert "/repositories/upload" in backend_paths
    assert "/repositories/local" in backend_paths

    # The frontend must call those exact routes for Git clone and ZIP upload.
    assert "/repositories/clone" in frontend_paths
    assert "/repositories/upload" in frontend_paths
    assert "/repositories/github" not in frontend_paths
    assert "/repositories/upload-zip" not in frontend_paths
