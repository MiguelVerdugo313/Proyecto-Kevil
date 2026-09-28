"""Nota de viralidad: la IA puntúa y elige; sin IA, reglas. Nunca inventa ganchos."""

from app.flow_schema import normalize_steps
from app.models import Clip, Flow, Job, Video
from app.services import ai, pipeline, viralidad

FRASES = [
    "¿Sabes qué pasó ayer en la partida?",
    "Estaba jugando tranquilo y de repente apareció el jefe final.",
    "No puede ser, me mató con un solo golpe, qué locura.",
    "Bueno, sigamos, voy a mirar el inventario un momento.",
    "Aquí hay unas pociones, las cojo, vale.",
    "Ahora voy hacia el norte del mapa a ver qué hay.",
    "Increíble, 100 puntos de golpe, no me lo creo.",
    "Esto es brutal, mirad cómo salta el personaje.",
    "Vale, ahora a guardar la partida y descansar un rato.",
    "Y con esto terminamos por hoy, gracias por ver.",
]


def _transcripcion(repeticiones=12):
    segmentos, palabras, t = [], [], 0.0
    for vuelta in range(repeticiones):
        for frase in FRASES:
            duracion = 4.0
            segmentos.append({"start": t, "end": t + duracion, "text": frase})
            trozos = frase.split()
            paso = duracion / len(trozos)
            for n, palabra in enumerate(trozos):
                palabras.append({"start": t + n * paso, "end": t + (n + 1) * paso - 0.05,
                                 "text": palabra})
            t += duracion + 0.5
    return {"segments": segmentos, "words": palabras}, t


def test_reglas_dan_siempre_una_nota_desglosada():
    nota = viralidad.por_reglas({"start": 0, "end": 30, "text": FRASES[2] + " " + FRASES[6]})
    assert set(viralidad.CRITERIOS) <= set(nota)
    assert all(0 <= nota[c] <= 25 for c in viralidad.CRITERIOS)
    assert nota["total"] == sum(nota[c] for c in viralidad.CRITERIOS)
    assert nota["fuente"] == "reglas" and nota["tipo_gancho"] == "reaccion"
    sosa = viralidad.por_reglas({"start": 0, "end": 30, "text": FRASES[4] + " " + FRASES[5]})
    assert sosa["total"] < nota["total"]
    muda = viralidad.por_reglas({"start": 0, "end": 30, "text": ""})
    assert muda["total"] == 12


def test_el_gancho_de_la_ia_no_puede_inventar():
    texto = "No puede ser, me mató el jefe final con un solo golpe"
    assert viralidad.gancho_fiel("Un solo golpe del jefe final", texto)
    assert viralidad.gancho_fiel("¡No puede ser!", texto)
    assert not viralidad.gancho_fiel("Gané 500 partidas en Fortnite", texto)
    assert not viralidad.gancho_fiel("Tutorial de edición con Premiere", texto)


def test_con_ia_se_leen_las_notas_y_se_limpian(monkeypatch):
    candidatos = [
        {"start": 0, "end": 30, "text": FRASES[2], "score": 0.5},
        {"start": 40, "end": 70, "text": FRASES[4], "score": 0.5},
    ]

    def responde(prompt, **_k):
        assert "REGLAS DE VERDAD" in prompt and "[1]" in prompt
        return {"momentos": [
            {"i": 0, "gancho": 30, "enganche": "20", "valor": 18, "compartible": 22,
             "tipo_gancho": "Reaccion", "motivo": "Reacción fuerte al morir",
             "gancho_titulo": "¡Me mató de un golpe!"},
            {"i": 1, "gancho": 3, "enganche": 4, "valor": 5, "compartible": 2,
             "tipo_gancho": "rarísimo", "motivo": "Nada pasa",
             "gancho_titulo": "El secreto de los 1000 diamantes"},
            {"i": 9, "gancho": 25},                           # fuera de rango: se ignora
        ]}

    monkeypatch.setattr(ai, "chat_json", responde)
    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    avisos = []
    salida = viralidad.puntuar(candidatos, usar_ia=True, titulo="Partida", avisar=avisos.append)
    primero, segundo = salida
    assert primero["viralidad"]["gancho"] == 25                  # se recorta a 25
    assert primero["viralidad"]["total"] == 25 + 20 + 18 + 22
    assert primero["viralidad"]["tipo_gancho"] == "reaccion"
    assert primero["hook"] == "¡Me mató de un golpe!"
    assert primero["reason"] == "Reacción fuerte al morir"
    assert segundo["viralidad"]["tipo_gancho"] == "ninguno"
    assert "hook" not in segundo or "diamantes" not in segundo.get("hook", "")   # inventado: fuera
    assert primero["score"] > segundo["score"]
    assert "2 de 2" in avisos[0]


def test_si_la_ia_falla_se_usan_reglas(monkeypatch):
    def revienta(*_a, **_k):
        raise ai.AIError("sin conexión")

    monkeypatch.setattr(ai, "chat_json", revienta)
    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    salida = viralidad.puntuar([{"start": 0, "end": 30, "text": FRASES[6]}], usar_ia=True, titulo="x")
    assert salida[0]["viralidad"]["fuente"] == "reglas"


def _preparar(session, *, con_ia: bool):
    transcripcion, duracion = _transcripcion()
    pasos = normalize_steps([])
    for paso in pasos:
        if paso["type"] == "segment":
            paso["config"].update({"strategy": "smart", "max_clips": 4, "ai_pick": con_ia,
                                   "min_duration": 20, "max_duration": 40})
    flujo = Flow(name="Prueba", steps=pasos)
    video = Video(external_id="v-viral", title="Partida épica", url="x",
                  duration_s=duracion, transcript=transcripcion)
    session.add_all([flujo, video])
    session.commit()
    job = Job(kind="process", payload={"video_id": video.id, "flow_id": flujo.id}, status="running")
    session.add(job)
    session.commit()
    return video, pipeline.JobContext(session, job)


def test_la_ia_elige_entre_el_doble_de_momentos(session, monkeypatch):
    vistos = []

    def responde(prompt, **_k):
        # puntúa alto los momentos donde se dice «increíble»
        momentos = []
        for linea in prompt.splitlines():
            if linea.startswith("["):
                n = int(linea[1:linea.index("]")])
                vistos.append(n)
                alto = "Increíble" in linea
                momentos.append({"i": n, "gancho": 25 if alto else 5, "enganche": 20 if alto else 5,
                                 "valor": 20 if alto else 5, "compartible": 20 if alto else 5,
                                 "tipo_gancho": "dato", "motivo": "Cifra y reacción" if alto else "Flojo",
                                 "gancho_titulo": "100 puntos de golpe" if alto else ""})
        return {"momentos": momentos}

    monkeypatch.setattr(ai, "chat_json", responde)
    monkeypatch.setattr(ai, "is_enabled", lambda: True)
    video, ctx = _preparar(session, con_ia=True)
    pipeline.job_process(session, ctx)

    clips = session.query(Clip).filter_by(video_id=video.id).order_by(Clip.start_s).all()
    assert len(clips) == 4
    assert len(vistos) > 4                               # se le enseñaron más de los que se quedan
    assert all(c.viralidad.get("fuente") == "ia" for c in clips)
    assert all("Increíble" in " ".join(w["text"] for w in c.words) for c in clips)
    assert all(c.hook == "100 puntos de golpe" for c in clips)
    assert [c.index for c in clips] == [1, 2, 3, 4]    # en orden del vídeo
    assert "La IA ha puntuado" in ctx.job.log


def test_sin_ia_la_nota_sale_de_reglas(session, monkeypatch):
    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    video, ctx = _preparar(session, con_ia=True)
    pipeline.job_process(session, ctx)
    clips = session.query(Clip).filter_by(video_id=video.id).all()
    assert clips and all(c.viralidad["fuente"] == "reglas" for c in clips)
    assert all(0 <= c.viralidad["total"] <= 100 for c in clips)
