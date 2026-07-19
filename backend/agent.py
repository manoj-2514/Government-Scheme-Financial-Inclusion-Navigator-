"""Agentic loop powered by the Groq SDK with function-calling.

Orchestrates a multi-turn conversation where the LLM can invoke
``check_eligibility``, ``search_schemes_by_criteria``, and
``get_scheme_details`` as tool calls, and the results are fed back
until the model produces a final text response.
"""

import json
import os
import re
import copy
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from groq import Groq

from models import ChatMessage, ChatSession
from tools.eligibility import (
    check_eligibility,
    search_schemes_by_criteria,
    validate_profile_field,
    detect_intent,
    get_missing_fields_for_profile,
)
from tools.scheme_lookup import get_scheme_details
from tools.knowledge_base import query_knowledge_base
from tools.voice_assistant import translate_text

# Global agent response cache: (session_id, cleaned_message) -> (final_text, tool_log, eligible_schemes, profile_snapshot)
_agent_response_cache = {}

# ---------------------------------------------------------------------------
# Initialise Groq client
# ---------------------------------------------------------------------------

load_dotenv()

# ── Multi-key + multi-model fallback ──────────────────────────────
# .env can define GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ...
_API_KEYS = [
    v for k, v in sorted(os.environ.items())
    if k.startswith("GROQ_API_KEY") and v
]
if not _API_KEYS:
    _API_KEYS = [os.getenv("GROQ_API_KEY", "")]

_clients = [Groq(api_key=key) for key in _API_KEYS]
_client = _clients[0]  # kept so existing tests that patch _client still work

_MODEL = "llama-3.3-70b-versatile"
_FALLBACK_MODEL = "llama-3.1-8b-instant"


def _chat_completion_with_fallback(**kwargs):
    """Try every (key, model) combination until one succeeds.

    Order: all keys on the main model first, then all keys on the
    fallback model. Non-rate-limit errors are raised immediately.
    """
    last_exc = None
    for model in (_MODEL, _FALLBACK_MODEL):
        for client in _clients:
            try:
                kwargs["model"] = model
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                msg = str(exc).lower()
                retryable = (
                    "rate limit" in msg or "rate_limit" in msg or "429" in msg
                    or "quota" in msg or "413" in msg or "request too large" in msg
                    or "tokens per" in msg or "over capacity" in msg or "503" in msg
                )
                if retryable:
                    last_exc = exc
                    continue  # try next key/model
                raise  # real error — don't mask it
    raise last_exc if last_exc else RuntimeError("All Groq keys exhausted")


_MAX_TOOL_ITERATIONS = 5

# ---------------------------------------------------------------------------
# Field display names — used to deterministically render the "Need more
# information" list, instead of trusting the LLM to compose it correctly.
# ---------------------------------------------------------------------------

_FIELD_DISPLAY_NAMES = {
    "occupation": "Occupation",
    "state": "State of residence",
    "income": "Annual income",
    "land_acres": "Land owned in acres",
    "age": "Age",
    "category": "Category (e.g. General, SC, OBC)",
    "gender": "Gender",
}

# Matches the "Need more information" block whether the model wrote it
# bold (**Need more information**:) or plain (Need more information:),
# any capitalisation — so the deterministic rebuild never duplicates it.
_NEED_MORE_INFO_BLOCK_PATTERN = re.compile(
    r"\*{0,2}Need more information\*{0,2}\s*:.*?(?=\n\n\S|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _rebuild_missing_info_section(
    final_text: str,
    allowed_missing_fields: set,
    eligibility_checked_this_turn: bool,
) -> str:
    """Deterministically replace any "Need more information" block in the
    model's response with one built directly from allowed_missing_fields.

    This guarantees correctness regardless of whether the model faithfully
    followed the ALLOWED_MISSING_FIELDS instruction — we don't trust the
    model's phrasing of *which* fields to ask for, only its prose around it.
    If no check_eligibility call happened this turn, we have no authoritative
    data to correct against, so the text is left untouched.
    """
    if not eligibility_checked_this_turn:
        return final_text

    # Strip out whatever "Need more information" block the model wrote.
    cleaned = _NEED_MORE_INFO_BLOCK_PATTERN.sub("", final_text).rstrip()

    if allowed_missing_fields:
        friendly = [
            _FIELD_DISPLAY_NAMES.get(f, f.replace("_", " ").title())
            for f in sorted(allowed_missing_fields)
        ]
        bullets = "\n".join(f"* {f}" for f in friendly)
        block = (
            "\n\n**Need more information**: To check your eligibility, "
            f"I still need:\n\n{bullets}"
        )
        return cleaned + block

    return cleaned


# ---------------------------------------------------------------------------
# System prompt — tells the LLM *who* it is and how to behave
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a friendly, expert Indian government-scheme eligibility assistant.

Your job:
1. Greet the user warmly and check the CURRENT USER PROFILE STATE below.
2. If occupation is already known, IMMEDIATELY use **search_schemes_by_criteria** 
   with the known occupation (and age/income if known — this matters for
   pension/age-based schemes) to find relevant schemes — do NOT wait for other fields.
3. Only ask for fields that are MISSING (null/None) from the current profile.
   NEVER re-ask for occupation, state, or any field that's already populated.
4. As soon as you have enough info, use **check_eligibility** for each found scheme to verify.
5. If eligibility cannot be determined because of missing fields, ask the user
   for those specific details — do NOT guess.
6. Once a user is confirmed eligible, call **get_scheme_details** to fetch
   benefits, documents needed, and the application link.
7. Present results clearly in simple language.  Always state *why* they
   qualify or don't.  List required documents and application steps.

Rules:
- Be concise but warm. Use bullet points for clarity.
- Never fabricate scheme information — only use data returned by the tools.
- Different schemes require different fields. A student scholarship scheme
  may never need land_acres; a farmer scheme may never need gender. Do not
  assume every profile field is always relevant.
- CRITICAL — TOOL CALLING FORMAT: You MUST use the structured tool-calling
  mechanism provided to you (the tools/functions interface). NEVER write a
  tool call as plain text in your response, such as
  "<function=check_eligibility>{...}". If you find yourself about to type
  "<function=" you are making a mistake — use the real tool-calling interface
  instead. A tool call must NEVER be visible in the text you show the user.
- ABSOLUTE RULE: You may ONLY name schemes whose scheme_id appeared in a tool
  result in THIS conversation. NEVER mention schemes from your own memory
  (e.g. Rythu Bandhu, YSR Rythu Bharosa, or any state scheme) unless a tool
  returned them.
- If the user asks about a SPECIFIC NAMED scheme (e.g. "PM-KISAN", "PMFBY"):
  1. FIRST try get_scheme_details (with your best-guess scheme_id) or
     search_schemes_by_criteria.
  2. If that returns no match or an error, you MUST THEN call
     query_knowledge_base with the scheme's name/question before concluding
     anything — the knowledge base has official guideline documents that may
     cover schemes not fully represented in structured data.
  3. ONLY if query_knowledge_base ALSO returns no relevant information should
     you tell the user the scheme is not in your database and suggest
     checking the official portal.
- Present a scheme's name EXACTLY as returned by get_scheme_details — do not
  rename, localize, or substitute a similar-sounding scheme.
- CRITICAL: Only state specific numeric criteria (income caps, age limits, land limits, etc.) that are EXPLICITLY present in the tool's returned data. NEVER infer, estimate, or mention any numeric threshold that was not provided by the eligibility check or scheme details tools.
- If the user's profile is updated (they share new info), incorporate it
  immediately into subsequent tool calls.
- If the user states a DIFFERENT occupation than the one in the profile,
  accept the new occupation, use it for all further tool calls, and briefly
  acknowledge the change (e.g. "Got it — updating your profile to Student.").
- Speak in English by default; switch to Hindi or the user's language if
  they write in it.
- Do NOT write your own "Need more information" bullet list of missing
  fields — the system will construct that list for you automatically and
  append it to your response. Just write the introductory sentence(s)
  explaining what schemes you found; leave out the field list entirely.

CRITICAL — Profile Awareness:
- The CURRENT USER PROFILE STATE below shows which fields are known (have values) 
  and which are missing (null/None).
- ALWAYS check this profile state before asking for information.
- NEVER ask for fields that already have values — only request missing fields.
- If occupation is known, proactively search for schemes using that occupation immediately.

CRITICAL — Response Formatting Instructions:
1. Start EVERY response with exactly a one-sentence direct answer to what was asked.
2. If listing multiple items (such as schemes or required documents), ALWAYS use markdown bullet points (*) or numbered lists. NEVER list items inline with asterisks or commas within a paragraph.
3. If eligibility for any scheme is being discussed, you MUST prefix the explanation with one of these bold status labels:
   - **Eligible**: [Explanation...]
   - **Not eligible**: [Explanation...]
   - (Do NOT write your own "**Need more information**:" block — see rule above, the system appends this automatically.)
4. Keep responses concise. Avoid restating disclaimers (e.g. "please check the official website...") more than once in a single response.

Response Examples:
Example 1 (schemes found, some info still needed — DO NOT add a field list yourself):
"Based on your occupation as a Farmer, I found several schemes you may qualify for."
(The system will automatically append the correct "Need more information" list after this.)

Example 2 (Eligible):
"You qualify for the PM-KISAN scheme based on your profile.
**Eligible**: You meet the criteria for PM-KISAN:
* Occupation: Farmer
* Land: 2 acres"


CRITICAL — handling unknown profile fields:
- When calling check_eligibility, ONLY include fields the user has EXPLICITLY
  told you. Do NOT assume or default missing values.
- NEVER pass income=0, land_acres=0, age=0, or any zero/placeholder for fields
  the user has not provided. Instead, OMIT those fields entirely from the
  user_profile object.
- If check_eligibility returns "needs_more_info" or null with missing_fields,
  you MUST NOT list them yourself — the system appends the correct list
  automatically.
- Do NOT present a scheme as eligible until ALL required fields are confirmed.

CRITICAL — ALLOWED_MISSING_FIELDS:
- The ALLOWED_MISSING_FIELDS list below is computed dynamically based on the
  user's current intent and profile. You must ONLY ask for fields that appear
  in this list. Do NOT ask for any field not in this list, even if you think
  it might be relevant. Different scheme categories require different fields.
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
                "Verify if a user is eligible for a specific scheme using their known profile fields "
                "(occupation, state, income, land_acres, age, category, gender) and scheme_id. OMIT unknown fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_profile": {
                        "type": "object",
                        "description": "Known profile fields. OMIT fields the user has not explicitly provided.",
                        "properties": {
                            "occupation": {"type": ["string", "null"]},
                            "state": {"type": ["string", "null"]},
                            "income": {"type": ["number", "null"], "description": "Annual income in INR. Omit or null if unknown."},
                            "land_acres": {"type": ["number", "null"], "description": "Land owned in acres. Omit or null if unknown."},
                            "age": {"type": ["integer", "null"], "description": "User's age. Omit or null if unknown."},
                            "category": {"type": ["string", "null"]},
                            "gender": {"type": ["string", "null"]},
                        },
                    },
                    "scheme_id": {
                        "type": "string",
                        "description": "The unique scheme ID.",
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
            "description": "Search for schemes matching occupation, state, category, gender, age, and/or income. Always pass age and/or income if known — this is required for pension/age-based schemes to filter correctly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occupation": {"type": "string", "description": "e.g. Farmer, Student"},
                    "state": {"type": "string", "description": "e.g. Karnataka"},
                    "category": {"type": "string", "description": "e.g. General, SC, OBC"},
                    "gender": {"type": "string", "description": "e.g. Female, Male"},
                    "age": {"type": "integer", "description": "User's age, if known."},
                    "income": {"type": "number", "description": "User's annual income in INR, if known."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scheme_details",
            "description": "Get benefits, documents, and application link for an eligible scheme.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scheme_id": {"type": "string", "description": "The unique scheme ID."},
                },
                "required": ["scheme_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Search official guidelines/documentation for detailed or open-ended questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Search query."},
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
        age=args.get("age"),
        income=args.get("income"),
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
# Recovery net — handles models that leak tool calls as plain text
# ---------------------------------------------------------------------------

# Matches "<function=NAME>{...json...}" blocks, greedily up to the next
# "<function=" occurrence or the end of the string. Some models omit the
# closing tag entirely, so we don't require one.
_PSEUDO_FUNCTION_CALL_PATTERN = re.compile(
    r"<function=([a-zA-Z_][a-zA-Z0-9_]*)>\s*(\{.*?\})\s*(?=</function|<function=|$)",
    re.DOTALL,
)


def _extract_pseudo_tool_calls(text: str) -> List[Tuple[str, dict]]:
    """Detect tool calls a model mistakenly wrote as plain text instead of
    using Groq's structured tool_calls mechanism (e.g. weaker fallback
    models sometimes do this). Returns a list of (tool_name, args_dict)."""
    calls: List[Tuple[str, dict]] = []
    if "<function=" not in text:
        return calls
    for match in _PSEUDO_FUNCTION_CALL_PATTERN.finditer(text):
        name = match.group(1)
        raw_json = match.group(2)
        if name not in _TOOL_DISPATCH:
            continue
        try:
            args = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        calls.append((name, args))
    return calls


def _recover_from_pseudo_tool_calls(
    session: ChatSession,
    pseudo_calls: List[Tuple[str, dict]],
    tool_log: List[Dict[str, Any]],
    eligible_schemes: List[Dict[str, Any]],
    eligible_scheme_ids: set,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Actually execute tool calls the model wrote as raw text, then build a
    clean, user-facing response directly from the real results. We do NOT
    trust any other prose from the malformed message, and we do NOT make
    another LLM round-trip here (to avoid repeating the same failure and to
    save latency/tokens) — we synthesize a plain, honest summary instead."""
    summary_lines: List[str] = []

    for name, args in pseudo_calls:
        result_json = _execute_tool(name, json.dumps(args))
        try:
            result = json.loads(result_json)
        except (json.JSONDecodeError, TypeError):
            result = {}

        tool_log.append({"tool": name, "args": args, "result": result})

        if args:
            try:
                _update_profile_from_tool_call(session, args)
            except Exception:
                pass

        if not result or "error" in result:
            continue

        if name == "check_eligibility":
            scheme_id = args.get("scheme_id")
            status = result.get("eligible")
            reason = result.get("reason", "")
            if status is True and scheme_id and scheme_id not in eligible_scheme_ids:
                compiled = _compile_eligible_scheme(scheme_id, reason)
                if compiled:
                    eligible_schemes.append(compiled)
                    eligible_scheme_ids.add(scheme_id)
                    summary_lines.append(f"* **Eligible**: {compiled['name']} — {reason}")
            elif status == "needs_more_info" or status is None:
                summary_lines.append(f"* **Need more information** for {scheme_id}: {reason}")
            elif status is False:
                summary_lines.append(f"* **Not eligible** for {scheme_id}: {reason}")

        elif name == "get_scheme_details":
            scheme_id = args.get("scheme_id")
            summary_lines.append(f"* {result.get('name', scheme_id)}: {result.get('benefits', '')}")

        elif name == "search_schemes_by_criteria":
            if isinstance(result, list) and result:
                summary_lines.append(f"* Found matching schemes: {', '.join(result)}")

        elif name == "query_knowledge_base":
            summary_lines.append(str(result))

    if summary_lines:
        final_text = "Here's what I found:\n\n" + "\n".join(summary_lines)
    else:
        final_text = (
            "**Need more information**: I looked into this but couldn't find a "
            "clear answer. Could you rephrase your question or share a bit more detail?"
        )

    return final_text, tool_log, eligible_schemes


# ---------------------------------------------------------------------------
# Profile field validation — applied uniformly regardless of input source
# ---------------------------------------------------------------------------

def _validate_profile_field(field: str, value: Any) -> Any:
    """Validate a single profile field value.

    Returns the cleaned value if valid, or ``None`` if the value is
    invalid / malformed.  This function delegates to the centralized
    validate_profile_field in tools.eligibility.
    """
    return validate_profile_field(field, value)



# ---------------------------------------------------------------------------
# Profile extraction — pull structured fields from the LLM's tool calls
# ---------------------------------------------------------------------------

_PROFILE_FIELDS = {"occupation", "state", "income", "land_acres", "age", "category", "gender"}

# Numeric fields are only accepted into the session profile if the number
# actually appears in the user's own messages — this blocks the LLM from
# inventing values (e.g. copying "2 acres" from prompt examples).
_NUMERIC_FIELDS = {"income", "land_acres", "age"}


def _numeric_value_mentioned_by_user(session: ChatSession, value) -> bool:
    """Return True if *value*'s digits appear in any user message this session.

    Handles integers/floats and the common Indian "lakh" phrasing
    (e.g. income 200000 matches a user message containing "2 lakh").
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return True  # non-numeric — let normal validation handle it

    user_text = " ".join(
        m.content for m in session.messages if m.role == "user"
    ).lower()

    forms = set()
    if f.is_integer():
        forms.add(str(int(f)))
    forms.add(str(f))
    if "lakh" in user_text and f >= 100000:
        lakhs = f / 100000
        forms.add(str(int(lakhs)) if lakhs.is_integer() else str(lakhs))

    return any(form in user_text for form in forms)


def _update_profile_from_tool_call(session: ChatSession, args: dict) -> None:
    """If a tool call contains user_profile fields, validate and merge them
    into the session.  Invalid values are silently dropped so the field
    remains ``None`` and the agent will naturally ask for clarification.

    All fields — including occupation — are simple validated merges: the
    latest value the user provides wins.  This keeps the chat, profile
    panel, and dashboard consistent when the user corrects themselves
    (e.g. "actually, I'm a student").
    """
    profile_data = args.get("user_profile", args)

    for field in _PROFILE_FIELDS:
        value = profile_data.get(field)
        if value is None:
            continue
        validated = _validate_profile_field(field, value)
        if validated is None:
            continue
        if field in _NUMERIC_FIELDS and not _numeric_value_mentioned_by_user(session, validated):
            print(f"[GUARD] Rejected LLM-invented {field}={validated} (not stated by user)")
            continue
        setattr(session.profile, field, validated)


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


def _translate_agent_output(
    session: ChatSession,
    response_text: str,
    eligible_schemes: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Translate the English agent response and scheme fields for the session language."""
    target_lang = session.language
    if not target_lang or target_lang == "en":
        return response_text, eligible_schemes

    translated_text = response_text
    try:
        translated_text = translate_text(response_text, "en", target_lang)
    except RuntimeError:
        pass

    translated_schemes = copy.deepcopy(eligible_schemes)
    for scheme in translated_schemes:
        try:
            if scheme.get("name"):
                scheme["name"] = translate_text(scheme["name"], "en", target_lang)
            if scheme.get("reason"):
                scheme["reason"] = translate_text(scheme["reason"], "en", target_lang)
            if scheme.get("documents_needed"):
                scheme["documents_needed"] = [
                    translate_text(doc, "en", target_lang)
                    for doc in scheme["documents_needed"]
                ]
        except RuntimeError:
            pass

    return translated_text, translated_schemes


def _finalize_agent_response(
    session: ChatSession,
    response_text: str,
    tool_log: List[Dict[str, Any]],
    eligible_schemes: List[Dict[str, Any]],
    *,
    apply_language_translation: bool = True,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply session-language translation before returning to the caller."""
    if apply_language_translation:
        translated_text, translated_schemes = _translate_agent_output(
            session, response_text, eligible_schemes
        )
        return translated_text, tool_log, translated_schemes
    return response_text, tool_log, eligible_schemes


def run_agent(
    session: ChatSession,
    user_message: str,
    *,
    apply_language_translation: bool = True,
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
    cleaned_msg = user_message.strip().lower()
    cache_key = (session.session_id, cleaned_msg, session.language or "en")
    current_profile = session.profile.model_dump()

    if cache_key in _agent_response_cache:
        final_text, cached_tool_log, cached_eligible_schemes, cached_profile = _agent_response_cache[cache_key]
        if current_profile == cached_profile:
            print(f"[CACHE HIT] Agent response for message: '{user_message}'")
            # Append user message and assistant message to session history
            session.messages.append(ChatMessage(role="user", content=user_message))
            session.messages.append(ChatMessage(role="assistant", content=final_text))
            return _finalize_agent_response(
                session,
                final_text,
                copy.deepcopy(cached_tool_log),
                copy.deepcopy(cached_eligible_schemes),
                apply_language_translation=apply_language_translation,
            )

    print(f"[CACHE MISS] Agent response for message: '{user_message}'")

    # 1. Append the user message to session history
    session.messages.append(ChatMessage(role="user", content=user_message))

    # 2. Build the messages payload for Groq
    # Shorten context window by injecting current profile to system prompt,
    # and only sending the last 10 conversational turns (user + assistant messages)
    profile_dict = {k: v for k, v in session.profile.model_dump().items() if v is not None}

    # Detect user intent and compute dynamic missing fields
    intent_tags = detect_intent(user_message)
    # Store intent on session for dashboard use
    if not hasattr(session, 'last_detected_intent'):
        session.last_detected_intent = []
    if intent_tags:
        session.last_detected_intent = intent_tags

    dynamic_missing = get_missing_fields_for_profile(
        session.profile.model_dump(), intent_tags=session.last_detected_intent or None
    )

    profile_state = {
        "known_fields": profile_dict,
        "missing_fields": dynamic_missing,
    }

    system_content = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"CURRENT USER PROFILE STATE:\n{json.dumps(profile_state, indent=2)}\n\n"
        f"ALLOWED_MISSING_FIELDS: {json.dumps(dynamic_missing)}"
    )

    # Keep requests small enough for the fallback model's tight TPM limit:
    # last 8 messages only, each truncated to 1500 chars.
    _MAX_MSG_CHARS = 1500
    api_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_content},
    ]
    for msg in session.messages[-8:]:
        content = msg.content or ""
        if len(content) > _MAX_MSG_CHARS:
            content = content[:_MAX_MSG_CHARS] + " …[truncated]"
        api_messages.append({"role": msg.role, "content": content})

    tool_log: List[Dict[str, Any]] = []
    eligible_schemes: List[Dict[str, Any]] = []
    eligible_scheme_ids = set()

    # Tracks the UNION of missing_fields actually returned by check_eligibility
    # calls made THIS turn. Used to deterministically rebuild the "Need more
    # information" section after the model responds — we do NOT trust the
    # model to correctly transcribe this list into its own prose.
    allowed_missing_fields: set = set()
    eligibility_checked_this_turn = False

    # 3. Loop until the model gives a final text response (or we hit the cap)
    for _iteration in range(_MAX_TOOL_ITERATIONS):
        try:
            response = _chat_completion_with_fallback(
                messages=api_messages,
                tools=_TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=1024,
            )
        except Exception as exc:
            err_text = str(exc)
            # Groq rejected a malformed tool call (e.g. nulls where the schema
            # forbade them). The error payload includes the attempted call in
            # 'failed_generation' — recover it locally instead of failing the turn.
            if "tool_use_failed" in err_text or "failed_generation" in err_text:
                pseudo_calls = _extract_pseudo_tool_calls(err_text)
                if pseudo_calls:
                    print(
                        f"[WARNING] Groq rejected a malformed tool call; recovering "
                        f"{len(pseudo_calls)} call(s) from failed_generation."
                    )
                    final_text, tool_log, eligible_schemes = _recover_from_pseudo_tool_calls(
                        session, pseudo_calls, tool_log, eligible_schemes, eligible_scheme_ids
                    )
                    session.messages.append(
                        ChatMessage(role="assistant", content=final_text)
                    )
                    _agent_response_cache[cache_key] = (
                        final_text, copy.deepcopy(tool_log),
                        copy.deepcopy(eligible_schemes), current_profile,
                    )
                    return _finalize_agent_response(
                        session, final_text, tool_log, eligible_schemes,
                        apply_language_translation=apply_language_translation,
                    )
            raise

        choice = response.choices[0]
        message = choice.message

        # ── No tool calls → final text response ──────────────────────
        if not message.tool_calls:
            final_text = message.content or ""

            # Safety net: some models (especially the smaller fallback model)
            # occasionally write tool calls as plain text instead of using
            # the structured tool_calls mechanism. Detect and recover.
            pseudo_calls = _extract_pseudo_tool_calls(final_text)
            if pseudo_calls:
                print(
                    f"[WARNING] Model emitted {len(pseudo_calls)} pseudo tool-call(s) "
                    f"as plain text instead of structured tool_calls. Recovering."
                )
                final_text, tool_log, eligible_schemes = _recover_from_pseudo_tool_calls(
                    session, pseudo_calls, tool_log, eligible_schemes, eligible_scheme_ids
                )
            else:
                # Deterministically correct the "Need more information" list,
                # regardless of what the model wrote — this is the fix for
                # the model asking about irrelevant fields or echoing known
                # profile values as "missing".
                # When check_eligibility ran, use its missing_fields output;
                # otherwise re-compute from the (possibly updated) profile.
                if eligibility_checked_this_turn:
                    effective_missing = allowed_missing_fields
                else:
                    effective_missing = set(get_missing_fields_for_profile(
                        session.profile.model_dump(),
                        intent_tags=session.last_detected_intent or None,
                    ))
                final_text = _rebuild_missing_info_section(
                    final_text, effective_missing, True
                )

            session.messages.append(
                ChatMessage(role="assistant", content=final_text)
            )
            _agent_response_cache[cache_key] = (final_text, copy.deepcopy(tool_log), copy.deepcopy(eligible_schemes), current_profile)
            return _finalize_agent_response(
                session, final_text, tool_log, eligible_schemes,
                apply_language_translation=apply_language_translation,
            )

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

            # Inspect tool call to collect eligible schemes AND track the
            # union of missing_fields actually required by relevant schemes.
            if result and "error" not in result:
                if fn_name == "check_eligibility":
                    eligibility_checked_this_turn = True
                    for mf in result.get("missing_fields", []) or []:
                        allowed_missing_fields.add(mf)

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
                        eligibility_checked_this_turn = True
                        for mf in check_res.get("missing_fields", []) or []:
                            allowed_missing_fields.add(mf)
                        if check_res.get("eligible") is True:
                            reason = check_res.get("reason", "Eligible for this scheme.")
                            compiled = _compile_eligible_scheme(scheme_id, reason)
                            if compiled:
                                eligible_schemes.append(compiled)
                                eligible_scheme_ids.add(scheme_id)

            # Feed the tool result back to the model (truncated to keep the
            # request small; the full result is preserved in tool_log for the UI)
            model_result = result_json
            if len(model_result) > 1500:
                model_result = model_result[:1500] + " …[truncated]"
            api_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": model_result,
                }
            )

    # 4. If we exhausted iterations, return whatever we have
    fallback = (
        "I've gathered quite a bit of information.  Let me summarise what "
        "I know so far — could you help me fill in any gaps?"
    )
    fallback = _rebuild_missing_info_section(
        fallback, allowed_missing_fields, eligibility_checked_this_turn
    )
    session.messages.append(ChatMessage(role="assistant", content=fallback))
    _agent_response_cache[cache_key] = (fallback, copy.deepcopy(tool_log), copy.deepcopy(eligible_schemes), current_profile)
    return _finalize_agent_response(
        session, fallback, tool_log, eligible_schemes,
        apply_language_translation=apply_language_translation,
    )