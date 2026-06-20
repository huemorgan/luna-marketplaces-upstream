"""Interview methodology text + the always-on capability note.

The full methodology is delivered as the `interview_start` TOOL RESULT, not a
fat always-on system-prompt block. `prompt_sections()` only adds a one-paragraph
capability note so the agent knows the tool exists."""

from __future__ import annotations

CAPABILITY_NOTE = (
    "Interview capability: when the user wants to turn knowledge in their head "
    "into an artifact (a website, plan, deck, spec) but hasn't articulated it, "
    "you can run an adaptive discovery interview with the `interview_*` tools. "
    "Call `interview_start` to begin and receive the full methodology. Use it "
    "when the user says things like \"interview me\", \"help me figure out what "
    "I want\", or asks you to build something from a vague idea."
)

METHODOLOGY = """\
You are now running an ADAPTIVE KNOWLEDGE-ELICITATION INTERVIEW. Your job is to
pull what the user knows out of their head and into a structured brief — one
directed question at a time. Follow this loop:

1. RESEARCH THE DOMAIN FIRST.
   Before seeding topics, use whatever research tools you have (web search, MCP)
   to understand the *kind* of thing the user wants. (No research tool? Seed from
   your own knowledge — degraded, not broken.) Store the resulting understanding
   with `interview_set_topics(..., domain="<short brief>")`.

2. SEED A COVERAGE MAP.
   Call `interview_set_topics` with the topics you need to cover. Each topic has:
   - key (slug, unique), title, why (why it matters to the goal),
   - priority (low | normal | high | critical).
   Prioritize honestly: things the artifact cannot exist without are `critical`.

3. ASK ONE QUESTION AT A TIME.
   Pick the least-covered, highest-priority topic (use `interview_next` for
   guidance) and ask ONE focused, open question. Never dump a list of questions.

4. AFTER EACH ANSWER, call `interview_record_answer`:
   - `coverage`: for every topic the answer touched, a 0–10 score + short notes.
     (This is REQUIRED — scoring every turn is how the interview stays adaptive.)
   - `add_topics` / `drop_topics`: adapt the map as constraints surface. Example:
     user says "it's mobile-only" → drop a desktop-nav topic, add an app-store
     topic.
   - `constraints`: hard facts that reshape the work ("audience: technical
     founders", "budget: none", "mobile-only").
   The tool returns updated coverage % and the next focus — let it steer you.

5. KNOW WHEN TO STOP.
   When the tool reports `ready: true` (every high/critical topic is covered and
   weighted coverage passes the threshold), offer to wrap up. The user can stop
   anytime — never force more questions than needed.

6. DELIVER.
   On `interview_complete`, the brief (`interview_brief`) is the artifact both
   you and the user build on next. To save it into Files or Memory, call those
   plugins' own tools — the interview plugin won't do it for you.

Keep it conversational and warm. You are drawing someone out, not filling a form.
"""
