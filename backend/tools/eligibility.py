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


# ── Profile field validation ──────────────────────────────────────────────

_VALID_OCCUPATIONS = {
    "farmer", "agricultural labourer", "student", "entrepreneur",
    "business owner", "street vendor", "hawker", "shopkeeper",
    "labourer", "daily wager", "construction worker", "domestic worker",
    "artisan", "self-employed",
    "women entrepreneur", "msme", "senior citizen", "unorganized worker",
    "unorganised worker", "laborer",
    # Persons with Disabilities
    "disabled", "person with disability", "divyangjan", "pwd",
    # Fisherfolk
    "fisherman", "fisherfolk", "fish farmer",
    # Artisans / Weavers
    "weaver", "craftsman", "carpenter", "blacksmith", "goldsmith", "potter",
    # Unemployed Youth
    "unemployed", "unemployed youth", "job seeker",
    # BPL / EWS
    "bpl", "economically weaker section",
}

_VALID_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar",
    "chhattisgarh", "goa", "gujarat", "haryana", "himachal pradesh",
    "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra",
    "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "punjab",
    "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal",
    "andaman and nicobar islands", "chandigarh",
    "dadra and nagar haveli and daman and diu",
    "delhi", "jammu and kashmir", "ladakh", "lakshadweep",
    "puducherry", "new delhi",
    "j&k", "ap", "up", "mp", "hp", "uk", "wb", "tn",
}

# NOTE: includes EBC and DNT — PM-YASASVI's rules use these categories, and
# without them here no user could ever validate as EBC/DNT, making that
# scheme unreachable.
_VALID_CATEGORIES = {"general", "sc", "st", "obc", "ews", "ebc", "dnt", "nt", "sbc", "vjnt", "bpl"}
_VALID_GENDERS = {"male", "female", "other", "transgender"}


def validate_profile_field(field: str, value: Any) -> Any:
    """Validate a single profile field value.

    Returns the cleaned value if valid, or ``None`` if the value is
    invalid / malformed.
    """
    if value is None:
        return None

    if field == "occupation":
        s = str(value).strip().lower()
        if s in _VALID_OCCUPATIONS:
            return str(value).strip().title()
        # Substring matching only for inputs long enough to be meaningful —
        # otherwise "a" would match "artisan", etc.
        if len(s) >= 4:
            for valid in _VALID_OCCUPATIONS:
                if s in valid or valid in s:
                    return valid.title()
        return None

    if field == "state":
        s = str(value).strip().lower()
        if s in _VALID_STATES:
            return str(value).strip().title()
        # Substring matching only for inputs of 4+ chars — short forms like
        # "up"/"ap" are already in _VALID_STATES; "a" must not match "assam".
        if len(s) >= 4:
            for valid in _VALID_STATES:
                if s in valid or valid.startswith(s):
                    return valid.title()
        return None

    if field == "category":
        s = str(value).strip().lower()
        if s in _VALID_CATEGORIES:
            return s.upper()
        return None

    if field == "gender":
        s = str(value).strip().lower()
        if s in _VALID_GENDERS:
            return s.title()
        return None

    if field == "age":
        try:
            age = int(float(value))
        except (TypeError, ValueError):
            return None
        if age < 0 or age > 130:
            return None
        return age

    if field == "income":
        try:
            income = float(value)
        except (TypeError, ValueError):
            return None
        if income < 0 or income > 1_00_00_00_000:
            return None
        return income

    if field == "land_acres":
        try:
            acres = float(value)
        except (TypeError, ValueError):
            return None
        if acres < 0 or acres > 10_000:
            return None
        return acres

    return value


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


import copy

# ---------------------------------------------------------------------------
# Caching Layer
# ---------------------------------------------------------------------------
_check_eligibility_cache = {}
_search_schemes_cache = {}


# ── Public API ────────────────────────────────────────────────────────────

def check_eligibility(user_profile: dict, scheme_id: str) -> dict:
    """Compare *user_profile* against a scheme's eligibility rules."""
    profile_key = tuple(sorted(f"{k}:{v}" for k, v in user_profile.items()))
    cache_key = (profile_key, scheme_id)
    if cache_key in _check_eligibility_cache:
        print(f"[CACHE HIT] eligibility check for scheme: {scheme_id}")
        return copy.deepcopy(_check_eligibility_cache[cache_key])
    print(f"[CACHE MISS] eligibility check for scheme: {scheme_id}")

    # Helper function below will populate cache and return the result
    res = _check_eligibility_uncached(user_profile, scheme_id)
    _check_eligibility_cache[cache_key] = copy.deepcopy(res)
    return res


def _check_eligibility_uncached(user_profile: dict, scheme_id: str) -> dict:
    """Compare *user_profile* against a scheme's eligibility rules (actual logic).

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
        ``eligible``       - ``True``, ``False``, or ``"needs_more_info"``
        ``reason``         - human-readable explanation
        ``missing_fields`` - list of profile fields still needed
    """
    # Safety net and validation: treat 0 as "not provided" for numeric fields,
    # and run all fields through validate_profile_field to ensure data sanity.
    _PROFILE_FIELDS = {"occupation", "state", "income", "land_acres", "age", "category", "gender"}
    sanitised_profile = {}
    for field in _PROFILE_FIELDS:
        val = user_profile.get(field)
        if val is not None:
            # First handle numeric 0 as missing
            if field in {"income", "land_acres", "age"} and (val == 0 or val == 0.0):
                sanitised_profile[field] = None
            else:
                sanitised_profile[field] = validate_profile_field(field, val)
        else:
            sanitised_profile[field] = None
    user_profile = sanitised_profile

    schemes = _load_schemes()
    scheme = next((s for s in schemes if s["scheme_id"] == scheme_id), None)

    if scheme is None:
        return {
            "eligible": False,
            "reason": f"Scheme '{scheme_id}' not found in the database.",
            "missing_fields": [],
        }

    rules: Dict[str, Any] = scheme.get("eligibility", {})
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

    # Compute missing fields dynamically from the scheme's required fields
    required_fields = scheme.get("required_fields", [])
    missing_fields = [f for f in required_fields if user_profile.get(f) is None]

    for rule_key, rule_value in rules.items():
        if rule_key not in rule_mappings:
            # Fallback if there is an unmapped rule key: assume direct standard lookup
            profile_field = rule_key
            rule_type = "standard"
        else:
            profile_field, rule_type = rule_mappings[rule_key]

        user_value = user_profile.get(profile_field)

        # If user has not provided this profile field yet, we skip evaluating this rule
        if user_value is None:
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
            "eligible": None,  # undetermined eligibility
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
    age: Optional[int] = None,
    income: Optional[float] = None,
) -> List[str]:
    """Return scheme_ids that broadly match the given criteria.

    Now also accepts age and income — without these, an occupation-less
    search (e.g. "I'm 65, looking for pension schemes") could not filter
    meaningfully and returned nearly every scheme in the database.
    """
    cache_key = (occupation, state, category, gender, age, income)
    if cache_key in _search_schemes_cache:
        print(f"[CACHE HIT] search_schemes_by_criteria (occ={occupation}, st={state}, cat={category}, gen={gender}, age={age}, income={income})")
        return list(_search_schemes_cache[cache_key])
    print(f"[CACHE MISS] search_schemes_by_criteria (occ={occupation}, st={state}, cat={category}, gen={gender}, age={age}, income={income})")

    res = _search_schemes_by_criteria_uncached(occupation, state, category, gender, age, income)
    _search_schemes_cache[cache_key] = list(res)
    return res


def _search_schemes_by_criteria_uncached(
    occupation: Optional[str] = None,
    state: Optional[str] = None,
    category: Optional[str] = None,
    gender: Optional[str] = None,
    age: Optional[int] = None,
    income: Optional[float] = None,
) -> List[str]:
    """Return scheme_ids that broadly match the given criteria (actual logic)."""
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

        if not match:
            continue

        # ── Age filtering ──────────────────────────────────────────
        # If the scheme has an age rule and the caller provided an age,
        # only include the scheme if the age actually satisfies it. This
        # is what makes "I'm 65, looking for pension schemes" correctly
        # narrow down to pension/senior schemes instead of everything.
        if age is not None and "age" in rules:
            if not _value_matches(age, rules["age"]):
                continue

        # ── Income filtering ───────────────────────────────────────
        if income is not None:
            if "income_cap" in rules:
                try:
                    if float(income) > float(rules["income_cap"]):
                        continue
                except (TypeError, ValueError):
                    pass
            if "income" in rules and not _value_matches(income, rules["income"]):
                continue

        # ── Occupation–tag relevance filter ─────────────────────────
        # Schemes without an occupation restriction (like APY) technically
        # match every occupation search.  However a pension scheme is
        # irrelevant for a Student, and a scholarship is irrelevant for a
        # Farmer.  Exclude clearly mismatched tag–occupation combos.
        _OCCUPATION_TAG_EXCLUSIONS = {
            "student": {"pension", "insurance"},
        }
        if occupation:
            excluded_tags = _OCCUPATION_TAG_EXCLUSIONS.get(occupation.lower(), set())
            if excluded_tags:
                scheme_tags = set(scheme.get("tags", []))
                if scheme_tags & excluded_tags:
                    # Only exclude if the scheme does NOT explicitly list
                    # this occupation — if it does, respect the rule.
                    if "occupation" not in rules or not _value_matches(occupation, rules["occupation"]):
                        continue

        matched_ids.append(scheme["scheme_id"])

    return matched_ids


def detect_intent(user_message: str) -> List[str]:
    """Scan user_message for keywords matching scheme tags."""
    msg = user_message.lower()
    tags = set()
    
    # Keyword mappings
    pension_keywords = ["pension", "pensions", "old age", "retired", "senior citizen", "retirement"]
    scholarship_keywords = ["scholarship", "scholarships", "student", "college", "school", "study", "studies", "education", "merit"]
    loan_keywords = ["loan", "loans", "credit", "borrow", "capital", "svanidhi", "mudra", "cgtmse", "entrepreneur", "business", "self-employed"]
    insurance_keywords = ["insurance", "bima", "accident", "accidental", "disability cover"]
    subsidy_keywords = ["subsidy", "subsidies", "subsidized", "interest subsidy"]
    food_keywords = ["ration", "food", "grain", "grains", "wheat", "rice", "anna", "garib kalyan"]
    skill_keywords = ["skill", "skills", "training", "kaushal", "vishwakarma", "artisan", "craftsman", "weaver"]

    if any(k in msg for k in pension_keywords):
        tags.add("pension")
    if any(k in msg for k in scholarship_keywords):
        tags.add("scholarship")
    if any(k in msg for k in loan_keywords):
        tags.add("loan")
    if any(k in msg for k in insurance_keywords):
        tags.add("insurance")
    if any(k in msg for k in subsidy_keywords):
        tags.add("subsidy")
    if any(k in msg for k in food_keywords):
        tags.add("food_security")
    if any(k in msg for k in skill_keywords):
        tags.add("skill_development")

    return list(tags)


def get_missing_fields_for_profile(user_profile: dict, intent_tags: List[str] = None) -> List[str]:
    """Compute the union of missing required fields only across plausibly relevant schemes."""
    schemes = _load_schemes()
    
    # Filter schemes by intent_tags if provided and non-empty
    if intent_tags:
        filtered_schemes = []
        for s in schemes:
            s_tags = s.get("tags", [])
            if set(s_tags).intersection(set(intent_tags)):
                filtered_schemes.append(s)
        schemes = filtered_schemes

    missing_fields_set = set()
    
    # Determine user tags based on profile
    user_tags = set()
    user_age = user_profile.get("age")
    if user_age is not None:
        try:
            if float(user_age) >= 60:
                user_tags.add("senior_only")
        except (ValueError, TypeError):
            pass
            
    user_occ = user_profile.get("occupation")
    if user_occ is not None:
        user_tags.add(user_occ.lower())
        
    for scheme in schemes:
        scheme_id = scheme["scheme_id"]
        
        # Check eligibility using the updated _check_eligibility_uncached
        res = check_eligibility(user_profile, scheme_id)
        if res.get("eligible") == False:
            continue
            
        s_tags = scheme.get("tags", [])
        req_fields = scheme.get("required_fields", [])
        
        # Generic Tag Filtering Rule: For "pension" tagged schemes:
        # if "senior_only" is in user_tags, any pension scheme that does not have "senior_only" in its tags is skipped,
        # UNLESS the user has a matching occupation tag in user_tags.
        if "senior_only" in user_tags and "pension" in s_tags:
            if "senior_only" not in s_tags and not (user_occ and user_occ.lower() in s_tags):
                continue
                
        # Special case: if occupation is unknown AND a candidate scheme is occupation-gated:
        # only request "occupation" from that scheme (don't ask for other occupation-specific fields)
        if "occupation" in req_fields and user_occ is None:
            missing_fields_set.add("occupation")
        else:
            for f in req_fields:
                if user_profile.get(f) is None:
                    missing_fields_set.add(f)
                    
    # Exclude any field already present (non-null) in user_profile
    for f in list(missing_fields_set):
        if user_profile.get(f) is not None:
            missing_fields_set.discard(f)
            
    return sorted(list(missing_fields_set))


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

    print()
    print("=== Testing Search for age=65 (no occupation) — should NOT return everything ===")
    try:
        matches = search_schemes_by_criteria(age=65)
        print(f"  Matched scheme_ids ({len(matches)} of {len(schemes)} total): {matches}")
    except FileNotFoundError as exc:
        print(f"  ⚠  {exc}")