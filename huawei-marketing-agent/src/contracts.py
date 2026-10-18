"""Shared, framework-free input and output contracts for the agent."""

from typing import List, TypedDict


class AgentInput(TypedDict):
    """Request fields supplied by a user or calling application."""

    product_query: str
    audience: str
    scene: str
    platform: str
    goal: str
    extra_requirements: str


class Scenario(TypedDict):
    """Audience, campaign context, channel, and high-level strategy."""

    audience: str
    scene: str
    platform: str
    strategy: str


class EvidenceItem(TypedDict):
    """One supporting fact, its source, and any associated media references."""

    fact: str
    source: str
    media: List[str]


class Content(TypedDict):
    """Generated marketing copy fields."""

    title: str
    body: str
    cta: str
    tags: List[str]


class Checks(TypedDict):
    """Fact-check findings, risk notes, and information still needed."""

    facts: List[str]
    risks: List[str]
    missing_information: List[str]


class AgentOutput(TypedDict):
    """Unified result returned by the agent."""

    scenario: Scenario
    evidence: List[EvidenceItem]
    content: Content
    checks: Checks
