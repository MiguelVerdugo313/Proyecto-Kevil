"""Coach del canal: cadencia, regularidad, franjas, avisos e ideas."""

from datetime import timedelta

import pytest

from app.config import settings
from app.models import Notification, Video, utcnow
from app.services import coach, ideas, notifications


def _canal(session, *, huecos, visitas=None, hora=17):
    """Crea vídeos separados por `huecos` días (del más antiguo al más nuevo)."""
    visitas = visitas or [10000] * len(huecos)
    ahora = utcnow()
    dias = 0
    for indice, hueco in enumerate(huecos):
        dias += hueco
        session.add(
            Video(
                external_id=f"demo-{indice}",
                origin="youtube",
                title=f"Vídeo {indice}",
                url="x",
                duration_s=600,
                published_at=(ahora - timedelta(days=dias)).replace(hour=hora, minute=0),
                views=visitas[indice % len(visitas)],
            )
        )
    session.commit()


def test_sin_datos(session):
    data = coach.recommendation(session)
    assert data["state"] == "sin_datos"
    assert data["stats"]["has_data"] is False
    assert data["actions"]


def test_cadencia_y_regularidad(session):
    # un vídeo cada 7 días clavados
    _canal(session, huecos=[2] + [7] * 9)
    stats = coach.channel_stats(session)
    assert stats["cadence_days"] == 7.0
    assert stats["regularity"] > 0.9        # como un reloj
    assert stats["known_uploads"] == 10
    assert stats["days_since_last"] == pytest.approx(2, abs=1.5)


def test_ritmo_irregular_se_detecta(session):
    _canal(session, huecos=[1, 2, 30, 3, 25, 2, 20, 1])
    stats = coach.channel_stats(session)
    assert stats["regularity"] < 0.5


def test_estado_al_dia_y_retrasado(session):
    settings.target_uploads_per_week = 1.0     # objetivo: uno cada 7 días
    _canal(session, huecos=[1] + [7] * 6)
    assert coach.recommendation(session)["state"] == "al_dia"

    session.query(Video).delete()
    session.commit()
    _canal(session, huecos=[10] + [7] * 6)
    data = coach.recommendation(session)
    assert data["state"] == "retrasado"
    assert data["overdue_days"] > 0
    assert data["next_upload_at"] is not None


def test_canal_parado_avisa(session):
    settings.target_uploads_per_week = 2.0
    _canal(session, huecos=[40] + [7] * 5)
    data = coach.recommendation(session)
    assert data["state"] == "parado"

    creados = coach.daily_check(session)
    session.commit()
    assert "cadencia" in creados

    avisos = session.query(Notification).all()
    assert avisos and avisos[0].kind == "cadencia"
    assert notifications.unread_count(session) >= 1

    # no se repite el mismo aviso al momento
    coach.daily_check(session)
    session.commit()
    assert len(session.query(Notification).where(Notification.kind == "cadencia").all()) == 1


def test_mejores_franjas_desde_el_historial(session):
    # 8 vídeos maduros, los del día 17h con muchas más visitas
    _canal(session, huecos=[10] * 8, visitas=[50000, 1000], hora=17)
    stats = coach.channel_stats(session)
    assert stats["slots_source"] == "tu historial"
    assert stats["best_slots"]
    assert stats["best_slots"][0]["hour"] == 17


def test_franjas_de_referencia_sin_datos(session):
    _canal(session, huecos=[8, 8])
    stats = coach.channel_stats(session)
    assert stats["slots_source"] == "franjas de referencia"
    assert len(stats["best_slots"]) == 5


def test_marcar_avisos_leidos(session):
    notifications.notify(session, "Uno", "cuerpo", kind="test", desktop=False)
    notifications.notify(session, "Dos", "cuerpo", kind="test", desktop=False)
    session.commit()
    assert notifications.unread_count(session) == 2
    notifications.mark_read(session)
    session.commit()
    assert notifications.unread_count(session) == 0


# --------------------------------------------------------------------------
# Ideas
# --------------------------------------------------------------------------
def test_puntuacion_de_ideas():
    medida_buena = {"ok": True, "demand": 0.9, "competition": 0.1}
    medida_saturada = {"ok": True, "demand": 0.9, "competition": 0.95}
    assert ideas.score_idea(medida_buena, 1.0) > ideas.score_idea(medida_saturada, 1.0)
    # sin datos la nota es baja pero no cero
    sin_datos = ideas.score_idea({"ok": False}, 1.0)
    assert 0 < sin_datos < 0.5


def test_encaje_con_el_canal():
    palabras = ["minecraft", "granja", "redstone"]
    assert ideas._fit("minecraft granja automatica", palabras) > ideas._fit("recetas de cocina", palabras)


def test_ideas_locales_sin_ia(session):
    _canal(session, huecos=[7] * 5)
    for video in session.query(Video).all():
        video.title = "Granja automática de Minecraft con redstone"
    session.commit()

    creadas = ideas.generate(session, count=4, validate=False)
    session.commit()
    assert creadas
    assert all(idea.topic for idea in creadas)
    assert all(idea.source == "canal" for idea in creadas)
    assert all(0 <= idea.score <= 1 for idea in creadas)
