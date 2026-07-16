"""Test script with mock Groq Client for validating the scheme eligibility agent.

Simulates a real multi-turn conversation without needing an active API Key.
"""

import json
import os
import sys

# Reconfigure stdout to support UTF-8 characters (like the Indian Rupee symbol '₹') on Windows
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")

# Set dummy key so agent.py doesn't crash on import
os.environ["GROQ_API_KEY"] = "mock_key_for_testing"

from unittest.mock import MagicMock
import agent  # Import agent to patch its client
from models import ChatSession
from agent import run_agent


# ── Mocking Groq API responses for the three turns ───────────────────────

class MockChoice:
    def __init__(self, message):
        self.message = message


class MockResponse:
    def __init__(self, message):
        self.choices = [MockChoice(message)]


class MockToolCallFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class MockToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = MockToolCallFunction(name, arguments)


class MockAssistantMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


# Define what the LLM should reply on each sequential API call in the loop
class APIResponseGenerator:
    def __init__(self):
        self.call_count = 0

    def get_next_response(self, *args, **kwargs):
        self.call_count += 1
        # Extract messages passed to the API
        messages = kwargs.get("messages", [])
        last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

        # ── TURN 1: User says "I am a farmer." ────────────────────────────
        if "I am a farmer." in last_user_msg:
            if self.call_count == 1:
                return MockResponse(
                    MockAssistantMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                "call_search_1",
                                "search_schemes_by_criteria",
                                json.dumps({"occupation": "Farmer"}),
                            )
                        ],
                    )
                )
            else:
                return MockResponse(
                    MockAssistantMessage(
                        content=(
                            "Hello! I see you are a farmer. I found some schemes like "
                            "PM-KISAN and Karnataka Farmer Pension. To check if you qualify, "
                            "could you tell me how many acres of land you own and which state you live in?"
                        )
                    )
                )

        # ── TURN 2: User says "I own 2 acres of agricultural land." ───────
        elif "I own 2 acres of agricultural land." in last_user_msg:
            if self.call_count == 3:
                return MockResponse(
                    MockAssistantMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                "call_check_pmkisan",
                                "check_eligibility",
                                json.dumps({
                                    "user_profile": {
                                        "occupation": "Farmer",
                                        "land_acres": 2.0
                                    },
                                    "scheme_id": "pm-kisan"
                                }),
                            )
                        ],
                    )
                )
            else:
                return MockResponse(
                    MockAssistantMessage(
                        content=(
                            "Thanks for sharing that. With 2 acres of land, you meet the land limit for PM-KISAN. "
                            "To finalize eligibility and check other schemes, could you tell me your age and which state you live in?"
                        )
                    )
                )

        # ── TURN 3: User says "I am in Karnataka and I am 65 years old..."
        else:
            if self.call_count == 5:
                return MockResponse(
                    MockAssistantMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                "call_check_pmkisan_final",
                                "check_eligibility",
                                json.dumps({
                                    "user_profile": {
                                        "occupation": "Farmer",
                                        "land_acres": 2.0,
                                        "state": "Karnataka",
                                        "age": 65
                                    },
                                    "scheme_id": "pm-kisan"
                                }),
                            )
                        ],
                    )
                )
            elif self.call_count == 6:
                return MockResponse(
                    MockAssistantMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                "call_check_pension_final",
                                "check_eligibility",
                                json.dumps({
                                    "user_profile": {
                                        "occupation": "Farmer",
                                        "land_acres": 2.0,
                                        "state": "Karnataka",
                                        "age": 65
                                    },
                                    "scheme_id": "karnataka-farmer-pension"
                                }),
                            )
                        ],
                    )
                )
            elif self.call_count == 7:
                return MockResponse(
                    MockAssistantMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                "call_details_pmkisan",
                                "get_scheme_details",
                                json.dumps({"scheme_id": "pm-kisan"}),
                            ),
                            MockToolCall(
                                "call_details_pension",
                                "get_scheme_details",
                                json.dumps({"scheme_id": "karnataka-farmer-pension"}),
                            ),
                        ],
                    )
                )
            else:
                return MockResponse(
                    MockAssistantMessage(
                        content=(
                            "Great news! You qualify for two schemes:\n\n"
                            "1. **PM-KISAN**: Since you are a farmer owning 2 acres of land (which is below the 5-acre limit). "
                            "You will get ₹6,000/year. Required documents: Aadhaar card, Land Ownership documents, and Bank Details.\n"
                            "2. **Karnataka Farmer Old Age Pension**: Since you are a farmer in Karnataka and are 65 years old (above the 60 age limit). "
                            "You will get a monthly pension of ₹1,000. Required documents: Aadhaar card, age proof, Karnataka domicile certificate, and Land records.\n\n"
                            "Would you like me to guide you on how to apply online?"
                        )
                    )
                )


# Patch the Groq completions client with our generator
response_generator = APIResponseGenerator()
agent._client.chat.completions.create = MagicMock(side_effect=response_generator.get_next_response)


def print_session_profile(session: ChatSession):
    profile_dict = session.profile.model_dump()
    active_profile = {k: v for k, v in profile_dict.items() if v is not None}
    print(f"  [Extracted Profile]: {active_profile}")


def test_agent_conversation():
    session = ChatSession()

    messages = [
        "I am a farmer.",
        "I own 2 acres of agricultural land.",
        "I am in Karnataka and I am 65 years old. What schemes do I qualify for?"
    ]

    print("==================================================")
    print("STARTING CONVERSATION TEST (MOCKED GROQ SDK)")
    print(f"Session ID: {session.session_id}")
    print("==================================================")

    for i, user_msg in enumerate(messages, 1):
        print(f"\n--- Turn {i} ---")
        print(f"User: {user_msg}")

        # Run agent (which will hit our mocked completions client)
        response_text, tools_used, eligible_schemes = run_agent(session, user_msg)

        # Print current profile and the response
        print_session_profile(session)
        print(f"\nAgent:\n{response_text}")

        # Print eligible schemes collected
        if eligible_schemes:
            print("\nEligible Schemes Collected:")
            for s in eligible_schemes:
                print(f"  - {s['name']} (Benefit: {s['benefit_amount']})")

        # Print tool logs
        if tools_used:
            print("\nTools Executed:")
            for tool_call in tools_used:
                print(f"  - Tool: {tool_call['tool']}")
                print(f"    Args: {tool_call['args']}")
                print(f"    Result: {tool_call['result']}")
        else:
            print("\nTools Executed: None")

    print("\n==================================================")
    print("CONVERSATION COMPLETE")
    print("==================================================")


if __name__ == "__main__":
    test_agent_conversation()
