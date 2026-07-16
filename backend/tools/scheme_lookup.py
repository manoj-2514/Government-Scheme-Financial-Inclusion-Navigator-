"""Scheme look-up utility.

Returns the full detail record for a scheme (benefits, required documents,
application link, etc.) from ``data/schemes.json``.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Resolve data/schemes.json relative to the project root.
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent            # backend/tools/
_BACKEND_DIR = _THIS_DIR.parent                        # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                    # project root
_SCHEMES_PATH = _PROJECT_ROOT / "data" / "schemes.json"


def _load_schemes():
    """Read and return the list of schemes from the JSON file."""
    if not _SCHEMES_PATH.exists():
        raise FileNotFoundError(
            f"Scheme data not found at {_SCHEMES_PATH}. "
            "Make sure data/schemes.json exists in the project root."
        )
    with open(_SCHEMES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_scheme_details(scheme_id: str) -> Dict[str, Any]:
    """Return the full scheme record for *scheme_id*.

    Parameters
    ----------
    scheme_id : str
        The unique identifier of the scheme (e.g. ``"pm-kisan"``).

    Returns
    -------
    dict
        The complete scheme object including:
        ``scheme_id``, ``name``, ``description``, ``benefits``,
        ``documents_needed``, ``apply_link``, ``eligibility``, and any
        other fields present in the JSON record.

        If the scheme is not found, returns a dict with
        ``{"error": "..."}`` instead.
    """
    schemes = _load_schemes()
    scheme = next((s for s in schemes if s["scheme_id"] == scheme_id), None)

    if scheme is None:
        return {"error": f"Scheme '{scheme_id}' not found in the database."}

    return scheme


# ── Quick smoke-test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        schemes = _load_schemes()
        if schemes:
            first_id = schemes[0]["scheme_id"]
            print(f"=== Details for '{first_id}' ===")
            import pprint
            pprint.pprint(get_scheme_details(first_id))
        else:
            print("  schemes.json is empty.")
    except FileNotFoundError as exc:
        print(f"  ⚠  {exc}")
