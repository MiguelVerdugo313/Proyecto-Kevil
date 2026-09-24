"""Propuestas para la pestaña Comunidad y los carruseles de TikTok."""

from datetime import datetime, timedelta
from pathlib import Path

from app.models import Account, Clip, Notification, Platform, Video, utcnow
from app.services import ai, comunidad


def _canal(session, carpeta=None):
    session.add(Account(platform=Platform.youtube.value, display_name="Kevil",
                        external_id="UC" + "k" * 22))
    ahora = utcnow()
    videos = []
    for i, titulo in enumerate([
        "MINECRAFT HARDCORE | Día 5", "Fortnite con subs - locura", "MINECRAFT HARDCORE | Día 4",
        "Fortnite con subs - otra vez",
    ]):
        video = Video(external_id=f"v{i}", title=titulo, url=f"https://youtu.be/v{i}",
                      published_at=ahora - timedelta(days=i * 3), was_live=True, duration_s=7200)
        session.add(video)
        videos.append(video)
    session.flush()
    for i in range(3):
        miniatura = ""
        if carpeta is not None and i < 2:            # la tercera aún sin miniatura
            miniatura = str(carpeta / f"m{i}.jpg")
            Path(miniatura).write_bytes(b"jpg")
        session.add(Clip(video_id=videos[0].id, title=f"Clip {i}", hook=f"¡Qué susto {i}!",
                         score=0.9 - i / 10, status="rendered", start_s=0, end_s=40,
                         thumb_path=miniatura))
    session.flush()


def test_juego_del_titulo():
    assert comunidad._juego("MINECRAFT HARDCORE | Día 5") == "Minecraft Hardcore"
    assert comunidad._juego("FNAF 2 PLUS ?!!! | Si existiera") == "FNAF 2 PLUS"
    assert comunidad._corto("FNAF 2 PLUS ?!!! | Si existiera un FNAF") == "FNAF 2 PLUS ?!"
    assert comunidad._juego("Fortnite con subs - locura") == "Fortnite con subs"
    assert comunidad._juego("") == ""


def test_propone_con_tus_datos_sin_ia(session, monkeypatch, tmp_path):
    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    _canal(session, tmp_path)
    ideas = comunidad.proponer(session)

    tipos = {i["tipo"] for i in ideas}
    assert {"encuesta", "imagen", "texto", "tiktok_fotos"} <= tipos
    encuesta = next(i for i in ideas if i["tipo"] == "encuesta")
    assert "Minecraft Hardcore" in encuesta["opciones"]
    assert 2 <= len(encuesta["opciones"]) <= comunidad.OPCIONES_MAX
    imagen = next(i for i in ideas if i["tipo"] == "imagen")
    assert imagen["imagenes"][0].startswith("/api/clips/")
    assert imagen["enlace"].endswith("/community")
    carrusel = next(i for i in ideas if i["tipo"] == "tiktok_fotos")
    # sólo las miniaturas que existen: nada de imágenes rotas
    assert carrusel["plataforma"] == "tiktok" and len(carrusel["imagenes"]) == 2
    # todas con hora, en el futuro y sin amontonarse el mismo día
    horas = [datetime.fromisoformat(i["cuando"].rstrip("Z")) for i in ideas if i["cuando"]]
    assert horas and all(h > utcnow() for h in horas)
    assert len({h.date() for h in horas}) == len(horas)


def test_la_ia_mejora_el_texto_sin_perder_enlaces(session, monkeypatch):
    _canal(session)
    base = comunidad._plantillas(comunidad.contexto(session))
    n_encuesta = next(i for i, idea in enumerate(base) if idea["tipo"] == "encuesta")
    n_texto = next(i for i, idea in enumerate(base) if idea["tipo"] == "texto")
    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat_json", lambda *a, **k: [
        {"n": n_encuesta, "titulo": "¡Decidís vosotros!", "texto": "Votad 👇",
         "opciones": ["Minecraft", "Fortnite"]},
        {"n": n_texto, "titulo": "Opinión", "texto": "¿Qué tal el último?"},
        {"n": 99, "titulo": "fuera de rango"},
        "basura",
    ])
    ideas = comunidad.proponer(session)
    encuesta = next(i for i in ideas if i["titulo"] == "¡Decidís vosotros!")
    assert encuesta["opciones"] == ["Minecraft", "Fortnite"] and encuesta["origen"] == "ia"
    texto = next(i for i in ideas if i["titulo"] == "Opinión")
    assert "https://youtu.be/v0" in texto["texto"]


def test_programar_avisar_y_contar(session, monkeypatch):
    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    _canal(session)
    ideas = comunidad.proponer(session)
    primera, segunda = ideas[0], ideas[1]

    pasada = (utcnow() - timedelta(minutes=1)).isoformat() + "Z"
    comunidad.cambiar(session, primera["id"], estado="programada", cuando=pasada)
    assert comunidad.tocan(session) == 1
    assert comunidad.avisar_las_que_tocan(session) == 1
    assert session.query(Notification).filter_by(kind="comunidad").count() == 1
    assert comunidad.avisar_las_que_tocan(session) == 0          # sólo una vez

    comunidad.cambiar(session, primera["id"], estado="hecha")
    comunidad.cambiar(session, segunda["id"], estado="hecha")
    resumen = comunidad.resumen(session)
    assert resumen["hechas_semana"] == 2 and resumen["objetivo_semana"] == 3

    # proponer otras no se lleva por delante lo hecho
    comunidad.proponer(session)
    estados = [i["estado"] for i in comunidad.listar(session)]
    assert estados.count("hecha") == 2


def test_asegurar_propone_si_no_hay(session, monkeypatch):
    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    ideas = comunidad.asegurar(session)       # canal vacío: aun así hay algo que proponer
    assert ideas and ideas[0]["tipo"] == "encuesta"
