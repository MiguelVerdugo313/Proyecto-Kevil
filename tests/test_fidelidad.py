"""El kit habla del vídeo de verdad: pregunta si no sabe y no se inventa el tema."""

from app.services import ai, fidelidad, seo

MUSICA = {"segments": [
    {"start": i * 5.0, "end": i * 5.0 + 4, "text": "Subtítulos realizados por la comunidad de Amara.org"}
    for i in range(20)
]}
CONTEXTO = "Gameplay de Friday Night Funkin', jugué la actualización del mod Animania"


def test_nombre_de_archivo_no_cuenta_como_titulo():
    assert fidelidad.titulo_generico("2026-09-24 20-30-11")
    assert fidelidad.titulo_generico("VID_0001")
    assert not fidelidad.titulo_generico("Animania")


def test_la_musica_no_es_una_transcripcion():
    util, motivo = fidelidad.transcripcion_util(MUSICA, 600)
    assert not util and motivo
    voz = {"segments": [
        {"start": i, "end": i + 1, "text": f"ahora voy a por el nivel {i} que es muy difícil de pasar"}
        for i in range(40)
    ]}
    assert fidelidad.transcripcion_util(voz, 300)[0]


def test_terminos_de_lo_que_cuentas():
    terminos = fidelidad.terminos(CONTEXTO)
    assert "Friday Night Funkin'" in terminos and "Animania" in terminos


def test_sin_contexto_ni_voz_pregunta_en_vez_de_inventar(monkeypatch):
    llamadas = []
    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat_json", lambda *a, **k: llamadas.append(a) or {})
    kit = seo.build_kit(title="Animania", transcript=MUSICA, duration=900)
    assert kit["falta_contexto"] and not kit["titles"]
    assert not llamadas                       # ni se le pregunta a la IA


def test_forzar_escribe_solo_con_el_titulo(monkeypatch):
    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    kit = seo.build_kit(title="Animania", transcript=MUSICA, duration=900, forzar=True)
    assert kit["titles"] == ["Animania"]
    texto = " ".join(kit["titles"] + [kit["description"]] + kit["tags"]).lower()
    assert "amara" not in texto and "guía" not in texto


def test_sin_ia_usa_lo_que_cuentas(monkeypatch):
    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    kit = seo.build_kit(title="2026-09-24 20-30-11", transcript=MUSICA, duration=900,
                        contexto=CONTEXTO)
    assert any("Friday Night Funkin'" in t for t in kit["titles"])
    assert not any("2026" in t for t in kit["titles"])
    assert "friday night funkin'" in kit["tags"]
    assert kit["description"].startswith("Gameplay de Friday Night Funkin'")
    assert "Friday Night Funkin'" in kit["thumbnail_prompt"]
    assert "Guía completa" not in " ".join(kit["titles"])


def _kit_ia(titulos, descripcion="Un vídeo.", tags=None):
    return {"titles": titulos, "description": descripcion, "tags": tags or ["fnf"],
            "hashtags": [], "chapters": [], "thumbnail_texts": ["FNF"],
            "thumbnail_prompt": "", "notes": ""}


def test_la_ia_que_se_inventa_un_tutorial_se_repite(monkeypatch):
    respuestas = [
        _kit_ia(["Aprende a editar vídeo como un profesional", "Tutorial de edición"],
                "Cómo transformar tus grabaciones", ["edición de video"]),
        _kit_ia(["Friday Night Funkin': el mod Animania", "Animania | FNF nueva actualización"]),
    ]
    prompts = []

    def responder(prompt, **_k):
        prompts.append(prompt)
        return respuestas[len(prompts) - 1]

    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat_json", responder)
    kit = seo.build_kit(title="Animania", transcript=MUSICA, duration=900, contexto=CONTEXTO)
    assert len(prompts) == 2
    assert CONTEXTO in prompts[0]
    assert "Amara" not in prompts[0]                  # la música no llega a la IA
    assert "DEBE nombrar" in prompts[1]
    assert kit["titles"][0].startswith("Friday Night Funkin'")
    assert kit["thumbnail_prompt"]                     # siempre hay prompt de miniatura


def test_si_insiste_en_inventar_se_usa_el_kit_local(monkeypatch):
    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat_json", lambda *a, **k: _kit_ia(
        ["Guía de edición profesional", "Aprende a editar"], "Tutorial", ["edición"]))
    kit = seo.build_kit(title="Animania", transcript=MUSICA, duration=900, contexto=CONTEXTO)
    assert kit["generated_by"] == "local"
    assert "se salía del tema" in kit["warning"]
    assert any("Friday Night Funkin'" in t for t in kit["titles"])
