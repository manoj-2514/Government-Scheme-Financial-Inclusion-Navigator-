"""Automated test script for validating the caching layer.

Ensures check_eligibility, search_schemes_by_criteria, get_scheme_details,
and run_agent all cache identical inputs correctly, printing hits and misses.
"""

import os
import sys
import io
from unittest.mock import MagicMock

# Reconfigure stdout to support UTF-8 on Windows
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")

# Set dummy key so agent.py imports correctly
os.environ["GROQ_API_KEY"] = "mock_key_for_testing"

# Import target functions
from tools.eligibility import check_eligibility, search_schemes_by_criteria
from tools.scheme_lookup import get_scheme_details
from models import ChatSession, UserProfile
import agent
from agent import run_agent

# Mock patch Groq client so run_agent doesn't call the actual network
mock_choice = MagicMock()
mock_choice.message.tool_calls = []
mock_choice.message.content = "Mocked LLM Response"
mock_response = MagicMock()
mock_response.choices = [mock_choice]
agent._client.chat.completions.create = MagicMock(return_value=mock_response)


def run_tests():
    print("=== STARTING CACHING LAYER TESTS ===\n")

    # ---------------------------------------------------------------------------
    # 1. Test check_eligibility caching
    # ---------------------------------------------------------------------------
    print("Testing check_eligibility caching...")
    profile = {"occupation": "Farmer", "state": "Karnataka"}
    scheme_id = "pm-kisan"

    # Capture stdout to verify printed output
    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    # Call 1 (Miss)
    check_eligibility(profile, scheme_id)
    # Call 2 (Hit)
    check_eligibility(profile, scheme_id)

    sys.stdout = sys.__stdout__
    output = captured_stdout.getvalue()

    assert "[CACHE MISS] eligibility check for scheme: pm-kisan" in output, "Expected check_eligibility first call cache miss"
    assert "[CACHE HIT] eligibility check for scheme: pm-kisan" in output, "Expected check_eligibility second call cache hit"
    print("✔ check_eligibility caching verified successfully.")

    # ---------------------------------------------------------------------------
    # 2. Test search_schemes_by_criteria caching
    # ---------------------------------------------------------------------------
    print("Testing search_schemes_by_criteria caching...")
    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    # Call 1 (Miss)
    search_schemes_by_criteria("Farmer", "Karnataka")
    # Call 2 (Hit)
    search_schemes_by_criteria("Farmer", "Karnataka")

    sys.stdout = sys.__stdout__
    output = captured_stdout.getvalue()

    assert "[CACHE MISS] search_schemes_by_criteria" in output, "Expected search_schemes_by_criteria first call cache miss"
    assert "[CACHE HIT] search_schemes_by_criteria" in output, "Expected search_schemes_by_criteria second call cache hit"
    print("✔ search_schemes_by_criteria caching verified successfully.")

    # ---------------------------------------------------------------------------
    # 3. Test get_scheme_details caching
    # ---------------------------------------------------------------------------
    print("Testing get_scheme_details caching...")
    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    # Call 1 (Miss)
    get_scheme_details("pm-kisan")
    # Call 2 (Hit)
    get_scheme_details("pm-kisan")

    sys.stdout = sys.__stdout__
    output = captured_stdout.getvalue()

    assert "[CACHE MISS] get_scheme_details for: pm-kisan" in output, "Expected get_scheme_details first call cache miss"
    assert "[CACHE HIT] get_scheme_details for: pm-kisan" in output, "Expected get_scheme_details second call cache hit"
    print("✔ get_scheme_details caching verified successfully.")

    # ---------------------------------------------------------------------------
    # 4. Test run_agent endpoint caching
    # ---------------------------------------------------------------------------
    print("Testing run_agent response caching...")
    session = ChatSession(session_id="test-cache-session", profile=UserProfile(occupation="Farmer"))
    user_message = "Hello, what schemes are available?"

    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    # Call 1 (Miss)
    run_agent(session, user_message)
    # Call 2 (Hit - profile has not changed, same message)
    run_agent(session, user_message)

    sys.stdout = sys.__stdout__
    output = captured_stdout.getvalue()

    assert "[CACHE MISS] Agent response for message: 'Hello, what schemes are available?'" in output, "Expected run_agent first call cache miss"
    assert "[CACHE HIT] Agent response for message: 'Hello, what schemes are available?'" in output, "Expected run_agent second call cache hit"
    print("✔ run_agent caching (same profile) verified successfully.")

    # ---------------------------------------------------------------------------
    # 5. Test run_agent profile invalidation
    # ---------------------------------------------------------------------------
    print("Testing run_agent profile changed cache invalidation...")
    captured_stdout = io.StringIO()
    sys.stdout = captured_stdout

    # Change profile state
    session.profile.state = "Karnataka"

    # Call 3 (Miss - profile changed)
    run_agent(session, user_message)

    sys.stdout = sys.__stdout__
    output = captured_stdout.getvalue()

    assert "[CACHE MISS] Agent response for message: 'Hello, what schemes are available?'" in output, "Expected cache invalidation on profile change"
    print("✔ run_agent profile invalidation verified successfully.")

    print("\n=== ALL CACHING TESTS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    run_tests()
