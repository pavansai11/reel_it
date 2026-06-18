"""Cost guardrails (spec §8): rate limits, spend ledger, and the global kill
switch. Built in from the start so a viral spike can't bankrupt us.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from .config import settings
from .db import session_scope
from .models import Job, SpendLedger

log = logging.getLogger(__name__)

# Approx Claude pricing (USD per token). Update with the model's real rates.
PRICE_IN_PER_TOKEN = 3.0 / 1_000_000
PRICE_OUT_PER_TOKEN = 15.0 / 1_000_000
# Rough fixed compute cost charged per rendered reel (CPU scoring + ffmpeg).
COMPUTE_COST_PER_REEL = 0.01


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record_llm_spend(input_tokens: int, output_tokens: int) -> float:
    usd = input_tokens * PRICE_IN_PER_TOKEN + output_tokens * PRICE_OUT_PER_TOKEN
    _add_spend(usd, note="edit_brain")
    return usd


def record_compute_spend(usd: float = COMPUTE_COST_PER_REEL) -> None:
    _add_spend(usd, note="compute")


def _add_spend(usd: float, note: str) -> None:
    if usd <= 0:
        return
    with session_scope() as session:
        session.add(SpendLedger(day=_today(), usd=usd, note=note))
    log.info("Spend +$%.4f (%s)", usd, note)


def today_spend_usd() -> float:
    with session_scope() as session:
        total = (
            session.query(func.coalesce(func.sum(SpendLedger.usd), 0.0))
            .filter(SpendLedger.day == _today())
            .scalar()
        )
    return float(total or 0.0)


def spend_ceiling_exceeded() -> bool:
    ceiling = settings.daily_spend_ceiling_usd
    if ceiling <= 0:
        return False
    return today_spend_usd() >= ceiling


def session_reels_today(session_id: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    with session_scope() as session:
        return (
            session.query(func.count(Job.id))
            .filter(Job.session_id == session_id, Job.created_at >= since)
            .scalar()
        ) or 0


def rate_limited(session_id: str) -> bool:
    return session_reels_today(session_id) >= settings.max_reels_per_session_per_day
