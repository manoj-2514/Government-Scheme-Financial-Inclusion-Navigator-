"""Agentic loop powered by the Groq SDK with function-calling.

Orchestrates a multi-turn conversation where the LLM can invoke
``check_eligibility``, ``search_schemes_by_criteria``, and
``get_scheme_details`` as tool calls, and the results are fed back
until the model produces a final text response.
"""

import json
import os
import re
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from groq import Groq

from models import ChatMessage, ChatSession
from tools.eligibility import check_eligibility, search_schemes_by_criteria
from tools.scheme_lookup import get_scheme_details
from tools.knowledge_base import query_knowledge_base

# ---------------------------------------------------------------------------
# Initialise Groq client
# ---------------------------------------------------------------------------

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

_MODEL = "llama-3.3-70b-versatile"
_MAX_TOOL_ITERATIONS = 5

# ---------------------------------------------------------------------------
# System prompt — tells the LLM *who* it is and how to behave
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a friendly, expert Indian government-scheme eligibility assistant.

Your job:
1. Greet the user warmly and ask about their situation (occupation, state,
   income, land, age, category, gender).
2. As soon as you have enough info, use **search_schemes_by_criteria** to find
   relevant schemes, then **check_eligibility** for each to verify.
3. If eligibility cannot be determined because of missing fields, ask the user
   for those specific details — do NOT guess.
4. Once a user is confirmed eligible, call **get_scheme_details** to fetch
   benefits, documents needed, and the application link.
5. Present results clearly in simple language.  Always state *why* they
   qualify or don't.  List required documents and application steps.

Rules:
- Be concise but warm. Use bullet points for clarity.
- Never fabricate scheme information — only use data returned by the tools.
- If the user's profile is updated (they share new info), incorporate it
  immediately into subsequent tool calls.
- Speak in English by default; switch to Hindi or the user's language if
  they write in it.
"""

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI-compatible function-calling format)
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_eligibility",
            "description": (
                "Check whether a user is eligible for a specific government "
                "scheme.  Call this when you have at least some profile info "
                "and a scheme_id to evaluate.  Returns eligible (true / false "
                "/ needs_more_info), a reason, and any missing_fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_profile": {
                        "type": "object",
                        "description": (
                            "The user's known profile fields.  Keys: "
                            "occupation, state, income, land_acres, age, "
                            "category, gender.  Omit unknown fields."
                        ),
                        "properties": {
                            "occupation": {"type": "string"},
                            "state": {"type": "string"},
                            "income": {"type": "number"},
                            "land_acres": {"type": "number"},
                            "age": {"type": "integer"},
                            "category": {"type": "string"},
                            "gender": {"type": "string"},
                        },
                    },
                    "scheme_id": {
                        "type": "string",
                        "description": "The unique scheme identifier.",
                    },
                },
                "required": ["user_profile", "scheme_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_schemes_by_criteria",
            "description": (
                "Search for government schemes that broadly match the "
                "user's occupation, state, or category.  Call this early "
                "in the conversation to discover which schemes to check.  "
                "Returns a list of matching scheme_ids."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "occupation": {
                        "type": "string",
                        "description": "e.g. Farmer, Student, Labourer",
                    },
                    "state": {
                        "type": "string",
                        "description": "Indian state name, e.g. Karnataka",
                    },
                    "category": {
                        "type": "string",
                        "description": "e.g. General, SC, ST, OBC",
                    },
                    "gender": {
                        "type": "string",
                        "description": "e.g. Female, Male, Other",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scheme_details",
            "description": (
                "Retrieve the full details of a government scheme — "
                "benefits, required documents, application link, and "
                "description.  Call this AFTER confirming the user is "
                "eligible, so you can present actionable next steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scheme_id": {
                        "type": "string",
                        "description": "The unique scheme identifier.",
                    },
                },
                "required": ["scheme_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": (
                "Query the unstructured knowledge base containing official "
                "guidelines and PDF/text documentation.  Call this when the "
                "user asks detailed, open-ended questions about how a scheme "
                "works, the detailed application steps, documentation details, "
                "or fine-grained rules not fully captured by eligibility checks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The query or question to look up in the documentation.",
                    },
                },
                "required": ["question"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatcher — maps function names to real Python callables
# ---------------------------------------------------------------------------

_TOOL_DISPATCH = {
    "check_eligibility": lambda args: check_eligibility(
        user_profile=args["user_profile"],
        scheme_id=args["scheme_id"],
    ),
    "search_schemes_by_criteria": lambda args: search_schemes_by_criteria(
        occupation=args.get("occupation"),
        state=args.get("state"),
        category=args.get("category"),
        gender=args.get("gender"),
    ),
    "get_scheme_details": lambda args: get_scheme_details(
        scheme_id=args["scheme_id"],
    ),
    "query_knowledge_base": lambda args: query_knowledge_base(
        question=args["question"],
    ),
}


def _execute_tool(name: str, arguments_json: str) -> str:
    """Parse the JSON arguments, call the real function, return JSON result."""
    try:
        args = json.loads(arguments_json)
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid JSON arguments: {arguments_json}"})

    func = _TOOL_DISPATCH.get(name)
    if func is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = func(args)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})

    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Profile extraction — pull structured fields from the LLM's tool calls
# ---------------------------------------------------------------------------

_PROFILE_FIELDS = {"occupation", "state", "income", "land_acres", "age", "category", "gender"}


def _update_profile_from_tool_call(session: ChatSession, args: dict) -> None:
    """If a tool call contains user_profile fields, merge them into the session."""
    profile_data = args.get("user_profile", args)
    for field in _PROFILE_FIELDS:
        value = profile_data.get(field)
        if value is not None:
            setattr(session.profile, field, value)


# ---------------------------------------------------------------------------
# Main agentic loop
# ---------------------------------------------------------------------------

def _compile_eligible_scheme(scheme_id: str, reason: str) -> dict:
    """Load scheme metadata and package it into the expected structured format."""
    details = get_scheme_details(scheme_id)
    if not details or "error" in details:
        return {}
    return {
        "name": details.get("name", scheme_id),
        "benefit_amount": details.get("benefits", ""),
        "reason": reason,
        "documents_needed": details.get("documents_needed", []),
        "apply_link": details.get("apply_link", ""),
    }


def run_agent(
    session: ChatSession,
    user_message: str,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run one turn of the agent loop.

    Parameters
    ----------
    session : ChatSession
        The current conversation state (messages + profile).  Modified in-place.
    user_message : str
        The latest message from the user.

    Returns
    -------
    tuple[str, list[dict], list[dict]]
        ``(final_text_response, tool_log, eligible_schemes)``
        where *eligible_schemes* is a list of structured dicts for each scheme
        determined to be eligible in this turn.
    """

    # 1. Append the user message to session history
    session.messages.append(ChatMessage(role="user", content=user_message))

    # 2. Build the messages payload for Groq
    api_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
    ]
    for msg in session.messages:
        api_messages.append({"role": msg.role, "content": msg.content})

    tool_log: List[Dict[str, Any]] = []
    eligible_schemes: List[Dict[str, Any]] = []
    eligible_scheme_ids = set()

    # 3. Loop until the model gives a final text response (or we hit the cap)
    for _iteration in range(_MAX_TOOL_ITERATIONS):
        response = _client.chat.completions.create(
            model=_MODEL,
            messages=api_messages,
            tools=_TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=1024,
        )

        choice = response.choices[0]
        message = choice.message

        # ── No tool calls → final text response ──────────────────────
        if not message.tool_calls:
            final_text = message.content or ""
            session.messages.append(
                ChatMessage(role="assistant", content=final_text)
            )
            return final_text, tool_log, eligible_schemes

        # ── Model wants to call one or more tools ─────────────────────
        # Append the assistant message (with tool_calls) to the thread
        api_messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
        )

        for tc in message.tool_calls:
            fn_name = tc.function.name
            fn_args_json = tc.function.arguments

            # Execute the real function
            result_json = _execute_tool(fn_name, fn_args_json)

            # Log it
            tool_log.append({
                "tool": fn_name,
                "args": json.loads(fn_args_json),
                "result": json.loads(result_json),
            })

            # Update the session profile if this call carried profile data
            try:
                args = json.loads(fn_args_json)
                result = json.loads(result_json)
            except (json.JSONDecodeError, TypeError):
                args = {}
                result = {}

            if args:
                try:
                    _update_profile_from_tool_call(session, args)
                except Exception:
                    pass

            # Inspect tool call to collect eligible schemes
            if result and "error" not in result:
                if fn_name == "check_eligibility":
                    if result.get("eligible") is True:
                        scheme_id = args.get("scheme_id")
                        reason = result.get("reason", "")
                        if scheme_id and scheme_id not in eligible_scheme_ids:
                            compiled = _compile_eligible_scheme(scheme_id, reason)
                            if compiled:
                                eligible_schemes.append(compiled)
                                eligible_scheme_ids.add(scheme_id)

                elif fn_name == "get_scheme_details":
                    scheme_id = args.get("scheme_id")
                    if scheme_id and scheme_id not in eligible_scheme_ids:
                        # Verify eligibility locally using the current user profile
                        profile_dict = {k: v for k, v in session.profile.model_dump().items() if v is not None}
                        check_res = check_eligibility(profile_dict, scheme_id)
                        if check_res.get("eligible") is True:
                            reason = check_res.get("reason", "Eligible for this scheme.")
                            compiled = _compile_eligible_scheme(scheme_id, reason)
                            if compiled:
                                eligible_schemes.append(compiled)
                                eligible_scheme_ids.add(scheme_id)

            # Feed the tool result back to the model
            api_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_json,
                }
            )

    # 4. If we exhausted iterations, return whatever we have
    fallback = (
        "I've gathered quite a bit of information.  Let me summarise what "
        "I know so far — could you help me fill in any gaps?"
    )
    session.messages.append(ChatMessage(role="assistant", content=fallback))
    return fallback, tool_log, eligible_schemes

