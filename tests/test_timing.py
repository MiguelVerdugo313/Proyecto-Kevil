"""Motor de horarios: reglas, huecos y estado de la cuenta."""

from datetime import timedelta

from app.models import (
    Account, AccountStatus, Clip, Platform, Post, PostStatus, Video, utcnow,
)
from app.services import timing


def _clip(session):
    """Un clip mínimo para poder colgar publicaciones de él."""
    video = Video(external_id="vid-test", title="Vídeo", url="local", duration_s=600)
    session.add(video)
    session.flush()
    clip = Clip(video_id=video.id, index=1, title="Clip", start_s=0, end_s=30)
    session.add(clip)
    session.commit()
    return clip


def _cuenta(session, **estrategia):
    account = Account(
        platform=Platform.tiktok.value,
        display_name="Prueba",
        handle="prueba",
        external_id="test-1",
        status=AccountStatus.connected.value,
        strategy={**timing.default_strategy(), **estrategia},
        stats={"followers": 25000},
    )
    session.add(account)
    session.commit()
    return account


def test_estrategia_por_defecto_se_completa():
    completa = timing.ensure_strategy({"max_per_day": 5})
    assert completa["max_per_day"] == 5
    assert len(completa["heatmap"]) == 7
    assert all(len(fila) == 24 for fila in completa["heatmap"])
    assert "weights" in completa


def test_los_huecos_respetan_la_separacion_minima(session):
    account = _cuenta(session, min_gap_hours=6, max_per_day=4)
    slots = timing.plan_slots(session, account, 4, spread_days=7, start_delay_hours=1)
    assert len(slots) == 4
    for anterior, siguiente in zip(slots, slots[1:]):
        assert (siguiente["utc"] - anterior["utc"]) >= timedelta(hours=6) - timedelta(minutes=25)


def test_se_respeta_el_maximo_diario(session):
    account = _cuenta(session, max_per_day=2, min_gap_hours=1)
    slots = timing.plan_slots(session, account, 8, max_per_day=2, spread_days=4, start_delay_hours=1)
    por_dia = {}
    for slot in slots:
        clave = slot["local"].date()
        por_dia[clave] = por_dia.get(clave, 0) + 1
    assert all(cuenta <= 2 for cuenta in por_dia.values())


def test_no_se_publica_en_horas_de_silencio(session):
    account = _cuenta(session, quiet_hours={"start": 0, "end": 12}, jitter_minutes=0, max_per_day=3)
    slots = timing.plan_slots(session, account, 6, spread_days=5, start_delay_hours=1)
    assert slots
    assert all(12 <= slot["local"].hour <= 23 for slot in slots)


def test_solo_los_dias_permitidos(session):
    account = _cuenta(session, allowed_days=[5, 6], jitter_minutes=0)
    slots = timing.plan_slots(session, account, 3, spread_days=14, start_delay_hours=1)
    assert slots
    assert all(slot["local"].weekday() in (5, 6) for slot in slots)


def test_los_huecos_evitan_lo_ya_programado(session):
    account = _cuenta(session, min_gap_hours=4)
    clip = _clip(session)
    primero = timing.plan_slots(session, account, 1, spread_days=7, start_delay_hours=1)[0]

    session.add(
        Post(
            clip_id=clip.id,
            account_id=account.id,
            scheduled_at=primero["utc"],
            status=PostStatus.scheduled.value,
        )
    )
    session.commit()

    siguientes = timing.plan_slots(session, account, 2, spread_days=7, start_delay_hours=1)
    for slot in siguientes:
        assert abs(slot["utc"] - primero["utc"]) >= timedelta(hours=4) - timedelta(minutes=25)


def test_calentamiento_de_cuentas_nuevas(session):
    nueva = _cuenta(session, max_per_day=4)
    nueva.stats = {"followers": 120}
    session.commit()
    estado = timing.account_state(session, nueva)
    assert estado["recommended_per_day"] <= 2
    assert estado["maturity"] == "nueva"
    assert 0 <= timing.health_score(estado) <= 100


def test_el_historial_manda_cuando_hay_datos(session):
    account = _cuenta(session, min_samples=4)
    clip = _clip(session)
    base = utcnow() - timedelta(days=30)
    for indice in range(8):
        session.add(
            Post(
                clip_id=clip.id,
                account_id=account.id,
                scheduled_at=base + timedelta(days=indice),
                published_at=(base + timedelta(days=indice)).replace(hour=9),
                status=PostStatus.published.value,
                metrics={"views": 10000 if indice % 2 == 0 else 400},
            )
        )
    session.commit()

    combinado = timing.combined_heatmap(session, account)
    assert combinado["using_history"] is True
    assert combinado["samples"] == 8
    mejores = timing.best_hours(session, account, top=3)
    assert len(mejores) == 3
    assert all("label" in hora for hora in mejores)
