"""
Radio field intel grounding — translates multilingual field-responder utterances
to English and maps to grid coordinates via landmark registry.
"""
import json
import sys
import llm_gateway
from landmarks import LandmarkRegistry

_registry = LandmarkRegistry()

CONFIDENCE_THRESHOLD = 0.5

_PROMPT_TEMPLATE = """You translate field-responder radio to English and match ONE landmark.

LANDMARKS: {landmarks}

INPUT: lang="{lang}", text="{text}"

OUTPUT JSON (no markdown):
{{
  "english": "<english translation>",
  "landmark_name": "<exact landmark name from list, or null>",
  "x": <x int or null>,
  "y": <y int or null>,
  "urgency": "CRITICAL" | "URGENT" | "STABLE",
  "confidence": <float 0-1>
}}

Rules:
- urgency=CRITICAL if life-threatening words (trapped, unconscious, bleeding, critical, terperangkap, kecemasan, kritikal, bawah bangunan)
- urgency=URGENT if moderate distress
- urgency=STABLE if mobile or requesting information
- landmark_name=null if no unambiguous landmark mentioned
- confidence=0 if text is unintelligible
"""


def translate_and_ground(lang: str, text: str) -> dict:
    """
    Translate and ground a field-responder utterance.
    Returns dict with keys: english, landmark_name, x, y, urgency, confidence, status.
    status: GROUNDED | UNGROUNDED | PENDING_GROUND
    """
    prompt = _PROMPT_TEMPLATE.format(
        landmarks=_registry.all_names_for_prompt(),
        lang=lang,
        text=text,
    )
    try:
        resp = llm_gateway.completion(messages=[{"role": "user", "content": prompt}])
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
    except Exception as e:
        print(f"[RADIO] LLM grounding failed: {e}", file=sys.stderr)
        return {
            "english": text, "landmark_name": None,
            "x": None, "y": None,
            "urgency": "STABLE", "confidence": 0.0,
            "status": "UNGROUNDED",
        }

    confidence = float(data.get("confidence", 0.0))
    if confidence >= CONFIDENCE_THRESHOLD and data.get("x") is not None:
        status = "GROUNDED"
    else:
        status = "UNGROUNDED"

    return {
        "english": data.get("english", text),
        "landmark_name": data.get("landmark_name"),
        "x": data.get("x"),
        "y": data.get("y"),
        "urgency": data.get("urgency", "STABLE"),
        "confidence": confidence,
        "status": status,
    }
