"""Selección de momentos y generación de textos."""

from app.flow_schema import default_config
from app.services import metadata, segmenter


def _config(**overrides):
    config = default_config("segment")
    config.update(overrides)
    return config


def _transcripcion(duracion=1200):
    """Frases sintéticas, una cada 6 segundos."""
    frases = [
        "el error que casi todo el mundo comete al empezar.",
        "esto es lo normal en cualquier proyecto pequeño.",
        "¿por qué nadie te cuenta este truco tan sencillo?",
        "suscríbete al canal y activa la campana ahora.",
        "el secreto está en repetirlo 30 días seguidos.",
    ]
    segments, words = [], []
    tiempo = 0.0
    índice = 0
    while tiempo < duracion:
        texto = frases[índice % len(frases)]
        segments.append({"start": tiempo, "end": tiempo + 5.5, "text": texto})
        paso = 5.5 / max(1, len(texto.split()))
        for posición, palabra in enumerate(texto.split()):
            words.append(
                {"start": tiempo + posición * paso, "end": tiempo + (posición + 1) * paso, "text": palabra}
            )
        tiempo += 6.0
        índice += 1
    return {"words": words, "segments": segments, "language": "es", "source": "test"}


def test_estrategia_uniforme_respeta_duraciones():
    config = _config(strategy="uniform", min_duration=20, max_duration=40, clips_per_hour=10, max_clips=5)
    clips = segmenter.find_segments(
        media_path="x.mp4", duration=1800, transcript=None, config=config
    )
    assert clips
    assert len(clips) <= 5
    for clip in clips:
        assert 20 <= clip["end"] - clip["start"] <= 40 + 0.01


def test_estrategia_inteligente_prefiere_ganchos():
    config = _config(strategy="smart", min_duration=15, max_duration=45, clips_per_hour=12, max_clips=6, min_gap=10)
    clips = segmenter.find_segments(
        media_path="x.mp4", duration=1200, transcript=_transcripcion(), config=config
    )
    assert clips
    assert all(clip["hook"] for clip in clips)
    assert all(clip["score"] > 0 for clip in clips)
    # ordenados y sin solaparse
    for anterior, siguiente in zip(clips, clips[1:]):
        assert siguiente["start"] >= anterior["start"]
        assert siguiente["start"] >= anterior["end"] - 0.01


def test_las_palabras_a_evitar_penalizan():
    base = _config(strategy="smart", min_duration=15, max_duration=30, max_clips=3, min_gap=5)
    clips = segmenter.find_segments(
        media_path="x.mp4", duration=600, transcript=_transcripcion(600), config=base
    )
    textos = " ".join(clip.get("text", "") for clip in clips).lower()
    # "suscríbete" está en la lista de palabras que restan
    assert textos.count("suscríbete") <= 1


def test_se_respeta_el_salto_de_intro():
    config = _config(strategy="uniform", skip_intro=120, skip_outro=60, min_duration=20, max_duration=40)
    clips = segmenter.find_segments(
        media_path="x.mp4", duration=900, transcript=None, config=config
    )
    assert clips
    assert min(clip["start"] for clip in clips) >= 119
    assert max(clip["end"] for clip in clips) <= 841


def test_estrategia_manual_no_genera_nada():
    clips = segmenter.find_segments(
        media_path="x.mp4", duration=900, transcript=None, config=_config(strategy="manual")
    )
    assert clips == []


def test_metadatos_y_hashtags():
    config = default_config("metadata")
    resultado = metadata.build_metadata(
        config=config,
        video_title="Cómo montar un huerto en casa",
        channel="Mi Canal",
        hook="el error que casi todos cometen",
        text="huerto casero tomates riego huerto tomates macetas",
        index=2,
        total=5,
    )
    assert "parte 2" in resultado["title"]
    assert resultado["caption"].startswith("el error")
    assert "#fyp" in resultado["caption"]
    assert len(resultado["hashtags"]) <= config["max_hashtags"]
    assert all(tag == tag.lower() and tag.isalnum() for tag in resultado["hashtags"])


def test_la_descripcion_se_recorta():
    config = default_config("metadata")
    config["max_caption_chars"] = 120
    resultado = metadata.build_metadata(
        config=config, video_title="t" * 300, channel="c", hook="h" * 300,
        text="", index=1, total=1,
    )
    assert len(resultado["caption"]) <= 120
