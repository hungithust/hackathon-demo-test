"""Agent Core reasoning. Calls Claude for real ReAct reasoning when an API key is
available, otherwise returns the scenario's scripted output. Either way the demo
runs identically — the live LLM is the wow factor, the fallback is the safety net.
"""

import os
import json

import streamlit as st

try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except Exception:
    _ANTHROPIC_AVAILABLE = False

MODEL = "claude-sonnet-4-6"


def _api_key():
    """Read key from env or Streamlit secrets (Streamlit Cloud uses secrets)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def run_agent_reasoning(scenario_name, sc):
    """Return (decision_dict, engine_label). decision_dict has keys:
    reasoning(list[str]), action(str), impact(str), needs_approval(bool)."""
    key = _api_key()
    if not (_ANTHROPIC_AVAILABLE and key):
        return sc["scripted"], "scripted (no API key)"

    prompt = f"""You are the decision core of an autonomous supply-chain agent.
A disruption was detected. Reason step-by-step (ReAct style), then decide a
concrete restructuring action. Return STRICT JSON only.

EVENT: {sc['event']}
ANOMALY SIGNAL: {sc['anomaly']}
CONTEXT: {json.dumps(sc['context'])}

Return JSON with keys:
- "reasoning": array of 3-4 short step strings (Observe/Think/Act/Plan)
- "action": one concrete action string
- "impact": one short impact-estimate string
- "needs_approval": boolean (true if high business impact)
JSON only, no prose."""

    try:
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "", 1).strip()
        data = json.loads(text)
        # minimal validation; fall back if shape is wrong
        assert isinstance(data.get("reasoning"), list) and data.get("action")
        return data, f"Claude ({MODEL})"
    except Exception as e:
        st.session_state.llm_error = str(e)
        return sc["scripted"], "scripted (API fallback)"
