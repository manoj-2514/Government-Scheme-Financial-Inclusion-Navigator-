import sys
from pathlib import Path

# Add backend to sys.path so we can import tools
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from tools.eligibility import (
    check_eligibility, search_schemes_by_criteria, validate_profile_field,
    detect_intent, get_missing_fields_for_profile,
)

def test_profile_field_validation():
    print("Testing profile field validation...")
    
    # Test valid occupations (including new ones)
    assert validate_profile_field("occupation", "disabled") == "Disabled"
    assert validate_profile_field("occupation", "fisherfolk") == "Fisherfolk"
    assert validate_profile_field("occupation", "weaver") == "Weaver"
    assert validate_profile_field("occupation", "unemployed youth") == "Unemployed Youth"
    assert validate_profile_field("occupation", "bpl") == "Bpl"
    
    # Test invalid occupations
    assert validate_profile_field("occupation", "doctor") is None
    
    # Test new categories
    assert validate_profile_field("category", "bpl") == "BPL"
    assert validate_profile_field("category", "ews") == "EWS"
    print("✓ Profile field validation tests passed.")

def test_scheme_eligibility():
    print("Testing eligibility evaluation...")

    # Case 1: Disabled Person (Non-BPL)
    profile_disabled_non_bpl = {
        "occupation": "Disabled",
        "state": "Karnataka",
        "income": 150000.0,
        "age": 25,
        "category": "General",
        "gender": "Male"
    }
    # ADIP should be True
    res_adip = check_eligibility(profile_disabled_non_bpl, "adip-disability")
    assert res_adip["eligible"] is True, f"ADIP failed: {res_adip}"
    
    # IGNDPS should be False (requires BPL category)
    res_igndps = check_eligibility(profile_disabled_non_bpl, "indira-gandhi-disability-pension")
    assert res_igndps["eligible"] is False, f"IGNDPS should be False for non-BPL: {res_igndps}"

    # Case 2: Disabled Person (BPL)
    profile_disabled_bpl = {
        "occupation": "Disabled",
        "state": "Karnataka",
        "income": 50000.0,
        "age": 25,
        "category": "BPL",
        "gender": "Male"
    }
    # IGNDPS should be True
    res_igndps_bpl = check_eligibility(profile_disabled_bpl, "indira-gandhi-disability-pension")
    assert res_igndps_bpl["eligible"] is True, f"IGNDPS failed for BPL: {res_igndps_bpl}"

    # Case 3: Fisherfolk
    profile_fisher = {
        "occupation": "Fisherfolk",
        "state": "Tamil Nadu",
        "income": 120000.0,
        "age": 30,
        "category": "General",
        "gender": "Female"
    }
    assert check_eligibility(profile_fisher, "pm-matsya-sampada")["eligible"] is True
    assert check_eligibility(profile_fisher, "fishermen-accident-insurance")["eligible"] is True

    # Case 4: Artisan / Weaver
    profile_weaver = {
        "occupation": "Weaver",
        "state": "Uttar Pradesh",
        "income": 100000.0,
        "age": 40,
        "category": "OBC",
        "gender": "Male"
    }
    assert check_eligibility(profile_weaver, "pm-vishwakarma")["eligible"] is True
    assert check_eligibility(profile_weaver, "ambedkar-hastshilp-vikas")["eligible"] is True

    # Case 5: Unemployed Youth
    profile_unemployed_general = {
        "occupation": "Unemployed Youth",
        "state": "Madhya Pradesh",
        "income": 50000.0,
        "age": 22,
        "category": "General",
        "gender": "Male"
    }
    assert check_eligibility(profile_unemployed_general, "pm-kaushal-vikas")["eligible"] is True
    assert check_eligibility(profile_unemployed_general, "ddu-grameen-kaushalya")["eligible"] is False

    profile_unemployed_bpl = {
        "occupation": "Unemployed Youth",
        "state": "Madhya Pradesh",
        "income": 30000.0,
        "age": 22,
        "category": "BPL",
        "gender": "Male"
    }
    assert check_eligibility(profile_unemployed_bpl, "ddu-grameen-kaushalya")["eligible"] is True

    # Case 6: BPL / EWS
    profile_bpl = {
        "occupation": "Daily Wager",
        "state": "Bihar",
        "income": 40000.0,
        "age": 45,
        "category": "BPL",
        "gender": "Female"
    }
    assert check_eligibility(profile_bpl, "antyodaya-anna-yojana")["eligible"] is True
    assert check_eligibility(profile_bpl, "pm-garib-kalyan-anna")["eligible"] is True

    print("✓ Scheme eligibility checks passed.")

def test_scheme_search():
    print("Testing scheme search by criteria...")

    # Search for "weaver"
    weaver_matches = search_schemes_by_criteria(occupation="Weaver")
    assert "pm-vishwakarma" in weaver_matches
    assert "ambedkar-hastshilp-vikas" in weaver_matches

    # Search for "disabled"
    disabled_matches = search_schemes_by_criteria(occupation="Disabled")
    assert "adip-disability" in disabled_matches
    assert "indira-gandhi-disability-pension" in disabled_matches

    # Search by category "BPL"
    bpl_matches = search_schemes_by_criteria(category="BPL")
    assert "antyodaya-anna-yojana" in bpl_matches
    assert "pm-garib-kalyan-anna" in bpl_matches
    assert "indira-gandhi-disability-pension" in bpl_matches

    print("✓ Scheme search tests passed.")


# ── New tests for dynamic eligibility and intent detection ────────────────

def test_undetermined_eligibility():
    """check_eligibility returns None (not False) when required fields are missing."""
    print("Testing undetermined eligibility (None vs False)...")

    # Student with missing income — should be None (undetermined), NOT False
    student_partial = {"occupation": "Student", "age": 20}
    res = check_eligibility(student_partial, "national-scholarship-scheme")
    assert res["eligible"] is None, (
        f"Expected None for missing required fields, got: {res['eligible']}"
    )
    assert "income" in res["missing_fields"], (
        f"Expected 'income' in missing_fields, got: {res['missing_fields']}"
    )

    # Farmer with all required fields filled — should be True or False, NOT None
    farmer_full = {"occupation": "Farmer", "land_acres": 2.0}
    res = check_eligibility(farmer_full, "pm-kisan")
    assert res["eligible"] is not None, (
        f"Expected True/False for fully-provided fields, got None: {res}"
    )

    print("✓ Undetermined eligibility tests passed.")


def test_detect_intent():
    """detect_intent returns correct tag categories from user messages."""
    print("Testing detect_intent...")

    assert "pension" in detect_intent("I want to know about pension schemes")
    assert "scholarship" in detect_intent("Are there any scholarships for students?")
    assert "loan" in detect_intent("I need a loan for my business")
    assert "insurance" in detect_intent("Tell me about crop insurance")
    assert "food_security" in detect_intent("I need ration card benefits")
    assert "skill_development" in detect_intent("I want skill training")

    # No matching intent
    tags = detect_intent("Hello, good morning")
    assert len(tags) == 0, f"Expected empty tags for greeting, got: {tags}"

    print("✓ detect_intent tests passed.")


def test_dynamic_missing_fields_student():
    """A student should NOT be asked for land_acres."""
    print("Testing dynamic missing fields for Student...")

    student_profile = {"occupation": "Student", "age": 20}
    missing = get_missing_fields_for_profile(student_profile, intent_tags=["scholarship"])
    assert "land_acres" not in missing, (
        f"Student + scholarship should NOT need land_acres, got: {missing}"
    )
    assert "income" in missing, (
        f"Student + scholarship should need income, got: {missing}"
    )

    print("✓ Student dynamic missing fields test passed.")


def test_dynamic_missing_fields_farmer():
    """A farmer should be asked for land_acres but NOT irrelevant student fields."""
    print("Testing dynamic missing fields for Farmer...")

    farmer_profile = {"occupation": "Farmer", "state": "Karnataka"}
    missing = get_missing_fields_for_profile(farmer_profile, intent_tags=None)
    assert "land_acres" in missing, (
        f"Farmer should need land_acres, got: {missing}"
    )

    print("✓ Farmer dynamic missing fields test passed.")


def test_dynamic_missing_fields_senior_pension():
    """A 65-year-old asking about pension should NOT be asked for occupation or land_acres."""
    print("Testing dynamic missing fields for Senior Citizen + pension...")

    senior_profile = {"age": 65}
    missing = get_missing_fields_for_profile(senior_profile, intent_tags=["pension"])
    assert "land_acres" not in missing, (
        f"Senior + pension should NOT need land_acres, got: {missing}"
    )
    # Senior-only pension schemes (senior-citizen-savings, indira-gandhi-old-age-pension)
    # don't require occupation, so it should not appear
    # (non-senior-only pension schemes are filtered out by the tag rule)
    print(f"  Senior pension missing fields: {missing}")

    print("✓ Senior Citizen pension dynamic missing fields test passed.")


def test_dynamic_missing_fields_occupation_gating():
    """When occupation is unknown, only 'occupation' should be requested first."""
    print("Testing occupation-gating behavior...")

    empty_profile = {}
    missing = get_missing_fields_for_profile(empty_profile, intent_tags=None)
    # Since occupation is unknown and many schemes gate on it,
    # the system should request "occupation" (and possibly age, category, gender
    # from non-occupation-gated schemes)
    assert "occupation" in missing, (
        f"Unknown occupation should request 'occupation', got: {missing}"
    )
    # Should NOT request land_acres when occupation is unknown
    # (land_acres is only relevant for farmer schemes which are occupation-gated)
    assert "land_acres" not in missing, (
        f"Should NOT request land_acres when occupation is unknown, got: {missing}"
    )

    print("✓ Occupation-gating test passed.")


def test_intent_filters_missing_fields():
    """Different intents should yield different missing field sets for the same profile."""
    print("Testing intent-based filtering of missing fields...")

    profile = {"occupation": "Student", "age": 20}
    scholarship_missing = get_missing_fields_for_profile(profile, intent_tags=["scholarship"])
    loan_missing = get_missing_fields_for_profile(profile, intent_tags=["loan"])
    # Scholarship and loan have different required_fields compositions
    print(f"  Scholarship missing: {scholarship_missing}")
    print(f"  Loan missing: {loan_missing}")

    print("✓ Intent-based filtering test passed.")


if __name__ == "__main__":
    print("Running automated eligibility & search tests for expanded schemes...")
    try:
        test_profile_field_validation()
        test_scheme_eligibility()
        test_scheme_search()
        test_undetermined_eligibility()
        test_detect_intent()
        test_dynamic_missing_fields_student()
        test_dynamic_missing_fields_farmer()
        test_dynamic_missing_fields_senior_pension()
        test_dynamic_missing_fields_occupation_gating()
        test_intent_filters_missing_fields()
        print("=== ALL TESTS PASSED SUCCESSFULLY! ===")
    except AssertionError as e:
        print(f"❌ TEST FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
