"""Motor de horarios: cuándo publicar cada clip.

Combina tres señales, todas con peso editable desde la interfaz:

1. **Historial de la cuenta** — a qué horas han funcionado mejor tus propias
   publicaciones (se aprende de las métricas que se van guardando).
2. **Patrón base** — franjas de actividad típicas de TikTok, editables como
   un mapa de calor de 7 días x 24 horas.
3. **Estado de la cuenta** — seguidores, cadencia reciente y calentamiento:
   una cuenta nueva publica menos y va subiendo poco a poco.

Todo se guarda en UTC; la zona horaria sólo se usa para interpretar las horas
que ve el usuario.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, MetricSample, Post, PostStatus, utcnow

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Patrón base por hora local (0-23). Se puede editar entero desde la pantalla
# de estrategia; esto es sólo el punto de partida.
_WEEKDAY_BASE = [
    0.20, 0.12, 0.08, 0.06, 0.08, 0.18, 0.42, 0.62,  # 00-07
    0.55, 0.45, 0.42, 0.48, 0.62, 0.58, 0.46, 0.44,  # 08-15
    0.52, 0.66, 0.78, 0.86, 0.95, 0.92, 0.74, 0.44,  # 16-23
]
_WEEKEND_BASE = [
    0.34, 0.24, 0.14, 0.08, 0.07, 0.12, 0.26, 0.40,
    0.52, 0.60, 0.64, 0.66, 0.68, 0.64, 0.58, 0.58,
    0.62, 0.70, 0.80, 0.88, 0.94, 0.90, 0.78, 0.56,
]


def default_heatmap() -> list[list[float]]:
    return [list(_WEEKDAY_BASE) for _ in range(5)] + [list(_WEEKEND_BASE) for _ in range(2)]


def default_strategy() -> dict[str, Any]:
    return {
        "timezone": "Europe/Madrid",
        "max_per_day": 3,
        "min_gap_hours": 3.0,
        "allowed_days": [0, 1, 2, 3, 4, 5, 6],
        "quiet_hours": {"start": 1, "end": 7},
        "weights": {"history": 0.45, "baseline": 0.40, "variety": 0.15},
        "heatmap": default_heatmap(),
        "warmup": True,
        "jitter_minutes": 12,
        "min_samples": 6,
    }


def ensure_strategy(strategy: dict[str, Any] | None) -> dict[str, Any]:
    merged = default_strategy()
    for key, value in (strategy or {}).items():
        if key == "weights" and isinstance(value, dict):
            merged["weights"].update(value)
        elif key == "heatmap" and isinstance(value, list) and len(value) == 7:
            merged["heatmap"] = [
                [float(h) for h in (row + [0.0] * 24)[:24]] for row in value
            ]
        elif key in merged:
            merged[key] = value
    return merged


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover
        return ZoneInfo("UTC")


def to_local(dt: datetime, zone: ZoneInfo) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(zone)


def to_utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Aprendizaje a partir del historial
# --------------------------------------------------------------------------
def learned_heatmap(
    session: Session, account_id: int, zone: ZoneInfo, min_samples: int = 6
) -> tuple[list[list[float]] | None, int]:
    """Mapa 7x24 con el rendimiento medio de tus publicaciones."""
    rows = session.execute(
        select(Post.published_at, Post.metrics)
        .where(
            Post.account_id == account_id,
            Post.status == PostStatus.published.value,
            Post.published_at.is_not(None),
        )
        .order_by(Post.published_at.desc())
        .limit(400)
    ).all()

    samples: list[tuple[int, int, float]] = []
    for published_at, metrics in rows:
        views = float((metrics or {}).get("views") or 0)
        if views <= 0:
            continue
        local = to_local(published_at, zone)
        samples.append((local.weekday(), local.hour, views))

    if len(samples) < min_samples:
        return None, len(samples)

    # normalizamos con la mediana para que un vídeo viral no lo distorsione todo
    values = sorted(s[2] for s in samples)
    median = values[len(values) // 2] or 1.0

    buckets: dict[tuple[int, int], list[float]] = {}
    for weekday, hour, views in samples:
        score = min(2.5, views / median) / 2.5
        buckets.setdefault((weekday, hour), []).append(score)

    matrix = [[0.0] * 24 for _ in range(7)]
    counts = [[0] * 24 for _ in range(7)]
    for (weekday, hour), scores in buckets.items():
        matrix[weekday][hour] = sum(scores) / len(scores)
        counts[weekday][hour] = len(scores)

    # difuminamos hacia las horas vecinas para no depender de una sola muestra
    smoothed = [[0.0] * 24 for _ in range(7)]
    for day in range(7):
        for hour in range(24):
            total = weight = 0.0
            for offset in (-2, -1, 0, 1, 2):
                neighbour = (hour + offset) % 24
                if counts[day][neighbour]:
                    factor = 1.0 / (1 + abs(offset))
                    total += matrix[day][neighbour] * factor
                    weight += factor
            smoothed[day][hour] = total / weight if weight else 0.0
    return smoothed, len(samples)


def account_state(session: Session, account: Account) -> dict[str, Any]:
    """Radiografía de la cuenta que usa el motor (y que se muestra en el panel)."""
    strategy = ensure_strategy(account.strategy)
    zone = get_zone(strategy["timezone"])
    stats = account.stats or {}
    # TikTok los llama seguidores; YouTube, suscriptores
    followers = int(stats.get("followers") or stats.get("subscribers") or 0)

    since = utcnow() - timedelta(days=7)
    published_7d = len(
        session.execute(
            select(Post.id).where(
                Post.account_id == account.id,
                Post.status == PostStatus.published.value,
                Post.published_at >= since,
            )
        ).all()
    )
    scheduled = len(
        session.execute(
            select(Post.id).where(
                Post.account_id == account.id,
                Post.status == PostStatus.scheduled.value,
            )
        ).all()
    )
    last_post_at = session.scalars(
        select(Post.published_at)
        .where(
            Post.account_id == account.id,
            Post.status == PostStatus.published.value,
            Post.published_at.is_not(None),
        )
        .order_by(Post.published_at.desc())
        .limit(1)
    ).first()

    samples = session.execute(
        select(MetricSample.views, MetricSample.captured_at)
        .where(MetricSample.account_id == account.id)
        .order_by(MetricSample.captured_at.desc())
        .limit(60)
    ).all()
    views = [float(v or 0) for v, _ in samples if v]
    avg_views = sum(views) / len(views) if views else 0.0
    recent_avg = sum(views[:10]) / len(views[:10]) if views else 0.0
    older_avg = sum(views[10:30]) / len(views[10:30]) if len(views) > 10 else recent_avg
    trend = 0.0
    if older_avg:
        trend = round((recent_avg - older_avg) / older_avg, 3)

    # Cadencia recomendada: cuentas nuevas empiezan suave y van subiendo
    ceiling = int(strategy.get("max_per_day", 3) or 3)
    if strategy.get("warmup", True):
        if followers < 1000:
            recommended = min(ceiling, 2)
        elif followers < 10000:
            recommended = min(ceiling, 3)
        else:
            recommended = ceiling
        if published_7d < 3:  # cuenta parada: se reanuda con calma
            recommended = min(recommended, 2)
    else:
        recommended = ceiling

    _, learned_samples = learned_heatmap(
        session, account.id, zone, int(strategy.get("min_samples", 6) or 6)
    )

    maturity = "nueva"
    if followers >= 10000 or published_7d >= 10:
        maturity = "consolidada"
    elif followers >= 1000 or published_7d >= 4:
        maturity = "en crecimiento"

    return {
        "followers": followers,
        "published_7d": published_7d,
        "scheduled": scheduled,
        "avg_views": round(avg_views),
        "trend": trend,
        "recommended_per_day": recommended,
        "max_per_day": ceiling,
        "maturity": maturity,
        "learned_samples": learned_samples,
        "using_history": learned_samples >= int(strategy.get("min_samples", 6) or 6),
        "timezone": strategy["timezone"],
        "last_post_at": last_post_at.isoformat() if last_post_at else None,
    }


# --------------------------------------------------------------------------
# Puntuación de franjas
# --------------------------------------------------------------------------
def combined_heatmap(session: Session, account: Account) -> dict[str, Any]:
    strategy = ensure_strategy(account.strategy)
    zone = get_zone(strategy["timezone"])
    weights = strategy["weights"]
    base = strategy["heatmap"]
    learned, samples = learned_heatmap(
        session, account.id, zone, int(strategy.get("min_samples", 6) or 6)
    )

    total_weight = float(weights.get("history", 0)) + float(weights.get("baseline", 0))
    matrix: list[list[float]] = []
    for day in range(7):
        row = []
        for hour in range(24):
            base_value = float(base[day][hour])
            if learned:
                value = (
                    float(weights.get("history", 0)) * learned[day][hour]
                    + float(weights.get("baseline", 0)) * base_value
                ) / (total_weight or 1)
            else:
                value = base_value
            row.append(round(max(0.0, min(1.0, value)), 4))
        matrix.append(row)

    return {
        "matrix": matrix,
        "baseline": base,
        "learned": learned,
        "samples": samples,
        "timezone": strategy["timezone"],
        "using_history": bool(learned),
    }


def _is_quiet(hour: int, quiet: dict[str, Any] | None) -> bool:
    if not quiet:
        return False
    start = int(quiet.get("start", 0) or 0)
    end = int(quiet.get("end", 0) or 0)
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # franja que cruza la medianoche


def plan_slots(
    session: Session,
    account: Account,
    count: int,
    *,
    max_per_day: int | None = None,
    min_gap_hours: float | None = None,
    spread_days: int = 7,
    start_delay_hours: float = 2.0,
    exclude: list[datetime] | None = None,
) -> list[dict[str, Any]]:
    """Devuelve `count` momentos (UTC) ordenados, ya libres de conflictos."""
    strategy = ensure_strategy(account.strategy)
    zone = get_zone(strategy["timezone"])
    heat = combined_heatmap(session, account)["matrix"]
    state = account_state(session, account)

    per_day = int(max_per_day or state["recommended_per_day"] or 3)
    gap = timedelta(hours=float(min_gap_hours or strategy.get("min_gap_hours", 3) or 3))
    allowed_days = set(strategy.get("allowed_days") or list(range(7)))
    quiet = strategy.get("quiet_hours")
    jitter = int(strategy.get("jitter_minutes", 12) or 0)
    variety_weight = float(strategy.get("weights", {}).get("variety", 0.15))

    # publicaciones ya programadas o publicadas (para respetar la separación)
    horizon_start = utcnow() - timedelta(days=2)
    booked: list[datetime] = [
        row[0]
        for row in session.execute(
            select(Post.scheduled_at).where(
                Post.account_id == account.id,
                Post.status.in_([PostStatus.scheduled.value, PostStatus.published.value]),
                Post.scheduled_at >= horizon_start,
            )
        ).all()
    ]
    booked += list(exclude or [])

    now_local = to_local(utcnow() + timedelta(hours=float(start_delay_hours)), zone)
    used_hours: dict[int, int] = {}
    chosen: list[dict[str, Any]] = []

    for _ in range(count):
        best: tuple[float, datetime, str] | None = None

        for day_offset in range(0, max(1, int(spread_days))):
            day = (now_local + timedelta(days=day_offset)).date()
            weekday = day.weekday()
            if weekday not in allowed_days:
                continue

            day_start = datetime.combine(day, datetime.min.time(), tzinfo=zone)
            same_day = [
                slot for slot in booked
                if to_local(slot, zone).date() == day
            ] + [
                c["local"] for c in chosen if c["local"].date() == day
            ]
            if len(same_day) >= per_day:
                continue

            for hour in range(24):
                if _is_quiet(hour, quiet):
                    continue
                candidate_local = day_start + timedelta(hours=hour, minutes=30)
                if candidate_local <= now_local:
                    continue

                candidate_utc = to_utc_naive(candidate_local)
                if any(abs(candidate_utc - slot) < gap for slot in booked):
                    continue
                if any(abs(candidate_utc - c["utc"]) < gap for c in chosen):
                    continue

                score = heat[weekday][hour]
                # penalizamos repetir siempre la misma hora
                score -= variety_weight * min(1.0, used_hours.get(hour, 0) * 0.5)
                # y preferimos publicar antes que después, a igualdad de calidad
                score -= 0.012 * day_offset

                if best is None or score > best[0]:
                    reason = f"{DAYS[weekday]} {hour:02d}:30 · franja {round(heat[weekday][hour] * 100)}%"
                    best = (score, candidate_local, reason)

        if best is None:
            break

        score, local_dt, reason = best
        if jitter:
            local_dt = local_dt + timedelta(minutes=random.randint(-jitter, jitter))
        utc_dt = to_utc_naive(local_dt)
        used_hours[local_dt.hour] = used_hours.get(local_dt.hour, 0) + 1
        chosen.append(
            {
                "utc": utc_dt,
                "local": local_dt,
                "score": round(max(0.0, min(1.0, score)), 4),
                "reason": reason,
            }
        )

    chosen.sort(key=lambda c: c["utc"])
    return chosen


def best_hours(session: Session, account: Account, top: int = 5) -> list[dict[str, Any]]:
    """Las mejores franjas de la semana, para mostrarlas en la interfaz."""
    heat = combined_heatmap(session, account)["matrix"]
    flat = [
        {"day": day, "hour": hour, "score": heat[day][hour]}
        for day in range(7)
        for hour in range(24)
    ]
    flat.sort(key=lambda item: item["score"], reverse=True)
    result = []
    for item in flat[:top]:
        result.append(
            {
                **item,
                "label": f"{DAYS[item['day']]} · {item['hour']:02d}:00",
                "percent": round(item["score"] * 100),
            }
        )
    return result


def health_score(state: dict[str, Any]) -> int:
    """Nota rápida (0-100) del estado de la cuenta."""
    score = 40.0
    score += min(25.0, state.get("published_7d", 0) * 3.0)
    score += min(15.0, math.log10(max(1, state.get("followers", 0))) * 4)
    trend = state.get("trend") or 0
    score += max(-15.0, min(20.0, trend * 40))
    if state.get("using_history"):
        score += 5
    return int(max(0, min(100, round(score))))
