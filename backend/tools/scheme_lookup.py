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


import copy

_scheme_details_cache = {}


def get_scheme_details(scheme_id: str) -> Dict[str, Any]:
    """Return the full scheme record for *scheme_id*."""
    if scheme_id in _scheme_details_cache:
        print(f"[CACHE HIT] get_scheme_details for: {scheme_id}")
        return copy.deepcopy(_scheme_details_cache[scheme_id])
    print(f"[CACHE MISS] get_scheme_details for: {scheme_id}")

    res = _get_scheme_details_uncached(scheme_id)
    _scheme_details_cache[scheme_id] = copy.deepcopy(res)
    return res


def _get_scheme_details_uncached(scheme_id: str) -> Dict[str, Any]:
    """Return the full scheme record for *scheme_id* (actual logic).

    Tries an exact match first. If that fails (e.g. the LLM guessed a
    slightly different ID format like "pm_kisan" instead of "pm-kisan"),
    falls back to a normalized ID match, then a fuzzy match against the
    scheme's display name — so small guessing errors don't cause a real
    scheme to be incorrectly reported as "not in the database".
    """
    schemes = _load_schemes()

    # 1. Exact match
    scheme = next((s for s in schemes if s["scheme_id"] == scheme_id), None)

    # 2. Normalized ID match (case / underscore / space insensitive)
    if scheme is None:
        normalized_target = (
            scheme_id.strip().lower().replace("_", "-").replace(" ", "-")
        )
        scheme = next(
            (
                s
                for s in schemes
                if s["scheme_id"].strip().lower() == normalized_target
            ),
            None,
        )

    # 3. Fuzzy match against the scheme's display name
    if scheme is None:
        needle = scheme_id.strip().lower().replace("-", " ").replace("_", " ")
        if needle:
            for s in schemes:
                name = s.get("name", "").lower()
                if needle in name or name in needle:
                    scheme = s
                    break

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

            print("\n=== Fuzzy match test: 'pm_kisan' ===")
            pprint.pprint(get_scheme_details("pm_kisan"))
        else:
            print("  schemes.json is empty.")
    except FileNotFoundError as exc:
        print(f"  ⚠  {exc}")