"""
Multimodal Gemini Job-Matching & Structured Output Engine

Evaluates a candidate's PDF resume directly against scraped multi-platform job
postings, enforcing:
- Strict typed JSON extraction via Pydantic response_schema
- Explicit geographic & remote-eligibility checks (filtering out geo-locked posts)
- Incorporation of prior user rejection feedback without cross-company bias
- Near-miss retention so users understand why roles fell below MATCH_SCORE_THRESHOLD
"""

import logging
import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger("job_worker.matching")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MATCH_SCORE_THRESHOLD = int(os.environ.get("MATCH_SCORE_THRESHOLD", 60))
MAX_DESCRIPTION_CHARS = 1000
MAX_NEAR_MISSES = 5

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


class _JobMatch(BaseModel):
    job_index: int
    match_score: int
    match_reason: str
    cover_letter: str


class _MatchResponse(BaseModel):
    matches: list[_JobMatch]


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _sanitize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _format_jobs_for_prompt(jobs: list[dict]) -> str:
    blocks = []
    for i, job in enumerate(jobs):
        desc = _strip_html(job.get("description", ""))[:MAX_DESCRIPTION_CHARS]
        blocks.append(
            f"[{i}] {job['title']} @ {job['company']} ({job.get('location') or 'remote'})\n"
            f"Tags: {', '.join(job.get('tags') or [])}\n"
            f"Description: {desc}"
        )
    return "\n\n".join(blocks)


async def analyze_with_gemini(
    cv_bytes: bytes,
    jobs: list[dict],
    feedback_context: str = "",
    search_location: str = "",
    user_location: str = "",
    search_role: str = "",
) -> tuple[list[dict], list[dict]]:
    """Evaluate a PDF resume against candidate postings and return (matches, near_misses)."""
    if not jobs or not client:
        return [], []

    loc_parts = []
    if search_role:
        loc_parts.append(f"- Target role: {search_role}")
    if search_location:
        loc_parts.append(f"- Desired search location/modality: {search_location}")
    if user_location:
        loc_parts.append(f"- Candidate location of residence: {user_location}")
    location_block = "\n\nCANDIDATE LOCATION CONTEXT:\n" + "\n".join(loc_parts) if loc_parts else ""

    feedback_block = (
        f"\n\nPrior explicit rejection signals (apply only to shared rejection causes, "
        f"never penalize unrelated roles):\n{feedback_context}"
        if feedback_context
        else ""
    )

    prompt = (
        "You are an expert technical recruiting evaluator. Given a candidate resume PDF "
        "and a numbered list of job postings, score fit from 0 to 100 and return a concise "
        f"1-2 sentence match_reason. Only when match_score >= {MATCH_SCORE_THRESHOLD}, generate "
        "a concise 3-4 sentence first-person tailored cover_letter; otherwise return empty string.\n\n"
        "CRITICAL GEOGRAPHIC & ELIGIBILITY RULES:\n"
        "1. If a role requires work authorization exclusive to a region outside the candidate's "
        "residence (e.g., 'Remote - US Only', 'UK Only') while the candidate resides elsewhere, "
        "assign match_score: 0 and explain the geo-restriction in match_reason.\n"
        "2. Roles explicitly marked 'Remote', 'Worldwide Remote', 'LATAM Remote', or 'Americas' "
        "remain valid for regional/global remote applicants.\n"
        f"{location_block}{feedback_block}\n\n"
        f"Job Postings:\n{_format_jobs_for_prompt(jobs)}"
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=cv_bytes, mime_type="application/pdf"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_MatchResponse,
        ),
    )

    parsed: _MatchResponse | None = response.parsed
    if parsed is None:
        try:
            parsed = _MatchResponse.model_validate_json(response.text)
        except Exception as exc:
            logger.error(f"Invalid JSON from Gemini structured output: {exc}")
            return [], []

    matches: list[dict] = []
    below_threshold: list[dict] = []
    for item in parsed.matches:
        if not (0 <= item.job_index < len(jobs)):
            continue
        scored_job = {
            **jobs[item.job_index],
            "match_score": item.match_score,
            "match_reason": _sanitize_text(item.match_reason),
            "cover_letter": _sanitize_text(item.cover_letter),
        }
        if item.match_score >= MATCH_SCORE_THRESHOLD:
            matches.append(scored_job)
        else:
            below_threshold.append(scored_job)

    below_threshold.sort(key=lambda j: j["match_score"], reverse=True)
    near_misses = below_threshold[:MAX_NEAR_MISSES]
    return matches, near_misses
