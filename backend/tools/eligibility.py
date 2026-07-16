"""Eligibility checking and scheme-search utilities.

Loads scheme data from ``data/schemes.json`` (relative to the project root)
and compares a user's profile against each scheme's eligibility rules.
Supports dynamic mappings between JSON rule names and UserProfile properties.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reconfigure stdout to use UTF-8 just in case we run this file directly on Windows
if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Locate schemes.json relative to the project root.
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent            # backend/tools/
_BACKEND_DIR = _THIS_DIR.parent                        # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                    # project root
_SCHEMES_PATH = _PROJECT_ROOT / "data" / "schemes.json"


def _load_schemes() -> List[Dict[str, Any]]:
    """Read and return the list of schemes from the JSON file."""
    if not _SCHEMES_PATH.exists():
        raise FileNotFoundError(
            f"Scheme data not found at {_SCHEMES_PATH}. "
            "Make sure data/schemes.json exists in the project root."
        )
    with open(_SCHEMES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ── Comparison helpers ────────────────────────────────────────────────────

def _value_matches(user_value: Any, rule_value: Any) -> bool:
    """Check whether a single user value satisfies one rule value.

    Supports:
      • exact string match (case-insensitive)
      • numeric range  {"min": …, "max": …}
      • list-of-allowed-values  ["Farmer", "Agricultural Labourer"]
    """
    if user_value is None:
        return False

    # --- list of allowed values ---
    if isinstance(rule_value, list):
        return str(user_value).strip().lower() in [
            str(v).strip().lower() for v in rule_value
        ]

    # --- numeric range {"min": …, "max": …} ---
    if isinstance(rule_value, dict):
        try:
            num = float(user_value)
        except (TypeError, ValueError):
            return False
        if "min" in rule_value and num < rule_value["min"]:
            return False
        if "max" in rule_value and num > rule_value["max"]:
            return False
        return True

    # --- exact match (string, case-insensitive) ---
    return str(user_value).strip().lower() == str(rule_value).strip().lower()


# ── Public API ────────────────────────────────────────────────────────────

def check_eligibility(user_profile: dict, scheme_id: str) -> dict:
    """Compare *user_profile* against a scheme's eligibility rules.

    Supports checking standard properties and mapping specialized properties:
      - land_ownership -> checked against land_acres (must be <= land_ownership)
      - income_cap     -> checked against income (must be <= income_cap)
      - states_excluded -> checked against state (must NOT be in states_excluded)

    Parameters
    ----------
    user_profile : dict
        Keys mirror :class:`UserProfile` fields (occupation, state, income,
        land_acres, age, category, gender). Values may be ``None``.
    scheme_id : str
        The unique identifier of the scheme to evaluate.

    Returns
    -------
    dict
        ``eligible``       – ``True``, ``False``, or ``"needs_more_info"``
        ``reason``         – human-readable explanation
        ``missing_fields`` – list of profile fields still needed
    """
    schemes = _load_schemes()
    scheme = next((s for s in schemes if s["scheme_id"] == scheme_id), None)

    if scheme is None:
        return {
            "eligible": False,
            "reason": f"Scheme '{scheme_id}' not found in the database.",
            "missing_fields": [],
        }

    rules: Dict[str, Any] = scheme.get("eligibility", {})
    missing_fields: List[str] = []
    failed_fields: List[str] = []

    # Map the JSON rule fields to their corresponding UserProfile fields
    # Format: rule_key -> (profile_field_name, rule_type)
    # Types: 'standard', 'income_cap', 'land_ownership', 'states_excluded'
    rule_mappings = {
        "occupation": ("occupation", "standard"),
        "state": ("state", "standard"),
        "age": ("age", "standard"),
        "category": ("category", "standard"),
        "gender": ("gender", "standard"),
        "income": ("income", "standard"),
        "land_acres": ("land_acres", "standard"),
        # Specialized rule mappings
        "income_cap": ("income", "income_cap"),
        "land_ownership": ("land_acres", "land_ownership"),
        "states_excluded": ("state", "states_excluded"),
    }

    for rule_key, rule_value in rules.items():
        if rule_key not in rule_mappings:
            # Fallback if there is an unmapped rule key: assume direct standard lookup
            profile_field = rule_key
            rule_type = "standard"
        else:
            profile_field, rule_type = rule_mappings[rule_key]

        user_value = user_profile.get(profile_field)

        # If user has not provided this profile field yet, it is missing
        if user_value is None:
            if profile_field not in missing_fields:
                missing_fields.append(profile_field)
            continue

        # Evaluate the rule based on its type
        if rule_type == "standard":
            if not _value_matches(user_value, rule_value):
                failed_fields.append(profile_field)

        elif rule_type == "income_cap":
            try:
                user_income = float(user_value)
                cap = float(rule_value)
                if user_income > cap:
                    failed_fields.append(profile_field)
            except (ValueError, TypeError):
                failed_fields.append(profile_field)

        elif rule_type == "land_ownership":
            try:
                user_land = float(user_value)
                max_land = float(rule_value)
                if user_land > max_land:
                    failed_fields.append(profile_field)
            except (ValueError, TypeError):
                failed_fields.append(profile_field)

        elif rule_type == "states_excluded":
            if isinstance(rule_value, list):
                excluded_list = [str(s).strip().lower() for s in rule_value]
                if str(user_value).strip().lower() in excluded_list:
                    failed_fields.append(profile_field)
            else:
                if str(user_value).strip().lower() == str(rule_value).strip().lower():
                    failed_fields.append(profile_field)

    # ── Decision logic ────────────────────────────────────────────────
    scheme_name = scheme.get("name", scheme_id)

    if failed_fields:
        reasons = [
            f"'{f}' does not meet the requirement" for f in failed_fields
        ]
        return {
            "eligible": False,
            "reason": (
                f"Not eligible for {scheme_name}: "
                + "; ".join(reasons) + "."
            ),
            "missing_fields": missing_fields,
        }

    if missing_fields:
        return {
            "eligible": "needs_more_info",
            "reason": (
                f"Cannot determine eligibility for {scheme_name} yet — "
                f"still need: {', '.join(missing_fields)}."
            ),
            "missing_fields": missing_fields,
        }

    return {
        "eligible": True,
        "reason": f"You appear to be eligible for {scheme_name}!",
        "missing_fields": [],
    }


def search_schemes_by_criteria(
    occupation: Optional[str] = None,
    state: Optional[str] = None,
    category: Optional[str] = None,
    gender: Optional[str] = None,
) -> List[str]:
    """Return scheme_ids that broadly match the given criteria.

    A scheme is included if the supplied criteria are compatible with the rules.
    If the scheme rules exclude the supplied state, it is filtered out.
    """
    schemes = _load_schemes()
    matched_ids: List[str] = []

    # Map the search input key to the scheme rule key
    criteria = {
        k: v
        for k, v in {
            "occupation": occupation,
            "state": state,
            "category": category,
            "gender": gender,
        }.items()
        if v is not None
    }

    for scheme in schemes:
        rules = scheme.get("eligibility", {})
        match = True

        for search_field, search_value in criteria.items():
            # Check exclusions first
            if search_field == "state" and "states_excluded" in rules:
                excluded = rules["states_excluded"]
                if isinstance(excluded, list):
                    excluded_list = [str(s).strip().lower() for s in excluded]
                    if str(search_value).strip().lower() in excluded_list:
                        match = False
                        break
                elif str(search_value).strip().lower() == str(excluded).strip().lower():
                    match = False
                    break

            # Check matching rules (standard keys and aliases)
            # Map search field name to potential keys in scheme json rules
            field_rule_keys = [search_field]
            if search_field == "state":
                field_rule_keys.append("state")
            elif search_field == "gender":
                field_rule_keys.append("gender")

            # Check if any applicable rule key fails
            for rkey in field_rule_keys:
                if rkey in rules and not _value_matches(search_value, rules[rkey]):
                    match = False
                    break

            if not match:
                break

        if match:
            matched_ids.append(scheme["scheme_id"])

    return matched_ids


# ── Quick smoke-test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_profile = {
        "occupation": "Student",
        "state": "Karnataka",
        "income": 150000.0,
        "land_acres": 0.0,
        "age": 20,
        "category": "General",
        "gender": "Female",
    }

    print("=== Testing Eligibility mapping with Student Profile ===")
    try:
        schemes = _load_schemes()
        print(f"Total schemes found in schemes.json: {len(schemes)}")
        for scheme in schemes:
            sid = scheme["scheme_id"]
            result = check_eligibility(sample_profile, sid)
            status = result["eligible"]
            if status == True or status == "needs_more_info":
                print(f"  [{status}]  {sid}: {result['reason']}")
    except FileNotFoundError as exc:
        print(f"  ⚠  {exc}")

    print()
    print("=== Testing Search for occupation=Student ===")
    try:
        matches = search_schemes_by_criteria(occupation="Student")
        print(f"  Matched scheme_ids: {matches}")
    except FileNotFoundError as exc:
        print(f"  ⚠  {exc}")
