"""Pydantic models for the scheme-eligibility chatbot backend."""

from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field
import uuid


class UserProfile(BaseModel):
    """Demographic and economic details gathered from the user during conversation."""

    occupation: Optional[str] = None
    state: Optional[str] = None
    income: Optional[float] = None          # Annual income in INR
    land_acres: Optional[float] = None      # Agricultural land owned
    age: Optional[int] = None
    category: Optional[str] = None          # e.g. General, SC, ST, OBC
    gender: Optional[str] = None            # e.g. Male, Female, Other


class SchemeResult(BaseModel):
    """Eligibility verdict for a single government scheme."""

    scheme_id: str
    eligible: Optional[Union[bool, Literal["needs_more_info"]]] = "needs_more_info"
    reason: str = ""
    missing_fields: List[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: Literal["user", "assistant", "system"]
    content: str


class ChatSession(BaseModel):
    """Tracks the full state of one user conversation."""

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    messages: List[ChatMessage] = Field(default_factory=list)
    profile: UserProfile = Field(default_factory=UserProfile)
    language: Optional[str] = None  # ISO 639-1 code, e.g. "hi", "te", "ta"
    last_detected_intent: List[str] = Field(default_factory=list)


class EligibleScheme(BaseModel):
    """Structured information about an eligible government scheme."""

    name: str
    benefit_amount: str
    reason: str
    documents_needed: List[str]
    apply_link: str