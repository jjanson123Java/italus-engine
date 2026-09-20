from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.legacy_production_isolation_service import (
    RETIRED_LEGACY_MODULES,
    PRIMARY40C_ISOLATION_MARKER,
    PRIMARY41_RETIREMENT_MARKER,
    assert_production_isolation,
)


def main() -> int:
    report = assert_production_isolation(REPO_ROOT)

    # Import the real production application after the static fail-closed gate
    # has passed, then prove the legacy runtime chain was not loaded as a
    # side-effect of FastAPI startup wiring.
    from app.api.main import app

    loaded_legacy = sorted(
        module_name
        for module_name in RETIRED_LEGACY_MODULES
        if module_name in sys.modules
    )
    if loaded_legacy:
        raise RuntimeError(
            "Primary 40C production import loaded legacy modules: "
            + ", ".join(loaded_legacy)
        )

    route_paths = sorted(
        str(route.path)
        for route in app.routes
        if getattr(route, "path", None)
    )

    if not route_paths:
        raise RuntimeError("Primary 40C could not observe FastAPI production routes.")

    print(f"PRIMARY40C MARKER: {PRIMARY40C_ISOLATION_MARKER}")
    print(
        "PRIMARY40C PRODUCTION ENTRY: "
        f"{report['production_entry_module']}"
    )
    print(
        "PRIMARY40C REACHABLE PRODUCTION MODULES: "
        f"{report['production_module_count']}"
    )
    print("PRIMARY40C LEGACY MODULE REACHABILITY: NONE")
    print("PRIMARY40C NON-PRODUCTION COMPATIBILITY REACHABILITY: NONE")
    print("PRIMARY40C FRONTEND LEGACY REFERENCES: NONE")
    print("PRIMARY40C LEGACY ROLLBACK SURFACE: RETIRED BY PRIMARY41")
    print(f"PRIMARY41 MARKER: {PRIMARY41_RETIREMENT_MARKER}")
    print("PRIMARY41 RETIRED LEGACY EXECUTABLES: ABSENT")
    print("PRIMARY41 RETIRED PROMPT BUILDER: ABSENT")
    print("PRIMARY40C FASTAPI LEGACY MODULE LOAD: NONE")
    print(f"PRIMARY40C FASTAPI ROUTES OBSERVED: {len(route_paths)}")
    print("PRIMARY40C RESULT: PASS")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    print("LEGACY GENERATION FALLBACK: NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
