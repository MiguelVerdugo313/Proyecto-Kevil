"""Piloto automático: conectar las cuentas y no volver a tocar nada."""

from sqlalchemy import select

from app.flow_schema import normalize_steps, step_config
from app.models import Account, AccountStatus, Flow, Platform, Source
from app.services import autopilot


def _todo_listo(session, *, con_canal=True, con_destino=True):
    flujo = Flow(name="Mi flujo", steps=normalize_steps([]), is_default=True)
    session.add(flujo)
    if con_destino:
        session.add(Account(
            platform=Platform.tiktok.value, display_name="Mi TikTok", handle="@yo",
            external_id="tt1", status=AccountStatus.connected.value, enabled=True,
        ))
    session.flush()
    if con_canal:
        session.add(Source(name="Mi canal", url="https://example.invalid/c",
                           flow_id=flujo.id, auto_ingest=False))
    session.commit()
    return flujo


def _modo(session, flujo):
    session.refresh(flujo)
    return step_config(normalize_steps(flujo.steps or []), "publish").get("mode")


# --------------------------------------------------------------------------
# Qué falta
# --------------------------------------------------------------------------
def test_sin_canal_ni_destino_dice_que_falta(session):
    estado = autopilot.estado(session)
    assert estado["enabled"] is False
    assert estado["ready"] is False
    assert len(estado["missing"]) == 2
    # y dice a dónde ir a arreglarlo, no sólo que falta
    assert all(r["accion"] for r in estado["requirements"] if not r["cumplido"])


def test_con_canal_pero_sin_donde_publicar_tampoco_vale(session):
    _todo_listo(session, con_destino=False)
    estado = autopilot.estado(session)
    assert estado["ready"] is False
    assert "Al menos una cuenta donde publicar" in estado["missing"]


def test_con_todo_conectado_ya_se_puede(session):
    _todo_listo(session)
    estado = autopilot.estado(session)
    assert estado["ready"] is True
    assert estado["missing"] == []


# --------------------------------------------------------------------------
# Encender
# --------------------------------------------------------------------------
def test_al_encenderlo_todo_pasa_a_publicar_solo(session):
    flujo = _todo_listo(session)
    assert _modo(session, flujo) == "review"          # de fábrica te pregunta

    resultado = autopilot.activar(session)
    session.commit()

    assert resultado["enabled"] is True
    assert _modo(session, flujo) == "auto"            # ya no pregunta
    # y los canales se vigilan solos
    canal = session.scalars(select(Source)).first()
    assert canal.auto_ingest is True and canal.enabled is True
    # la programación automática tiene que estar puesta, o no publicaría nada
    pasos = normalize_steps(flujo.steps or [])
    assert step_config(pasos, "schedule").get("auto_schedule") is True


def test_al_apagarlo_vuelve_a_pedirte_permiso(session):
    flujo = _todo_listo(session)
    autopilot.activar(session)
    session.commit()

    autopilot.desactivar(session)
    session.commit()

    assert autopilot.esta_activo(session) is False
    assert _modo(session, flujo) == "review"


def test_se_respeta_el_modo_que_tenia_cada_flujo(session):
    """Al apagar no se pone «revisar» a lo bruto: vuelve lo que había."""
    flujo = _todo_listo(session)
    pasos = normalize_steps(flujo.steps or [])
    for paso in pasos:
        if paso["type"] == "publish":
            paso["config"]["mode"] = "draft"          # el usuario lo quería así
    flujo.steps = pasos
    session.commit()

    autopilot.activar(session)
    session.commit()
    assert _modo(session, flujo) == "auto"

    autopilot.desactivar(session)
    session.commit()
    assert _modo(session, flujo) == "draft"           # no «review»


def test_encenderlo_dos_veces_no_pierde_el_modo_original(session):
    flujo = _todo_listo(session)
    pasos = normalize_steps(flujo.steps or [])
    for paso in pasos:
        if paso["type"] == "publish":
            paso["config"]["mode"] = "draft"
    flujo.steps = pasos
    session.commit()

    autopilot.activar(session)
    session.commit()
    autopilot.activar(session)      # otra vez, sin apagarlo
    session.commit()

    autopilot.desactivar(session)
    session.commit()
    assert _modo(session, flujo) == "draft"


def test_el_estado_que_devuelve_encender_ya_esta_al_dia(session):
    """Si no, la pantalla enseñaría el estado viejo justo tras el clic."""
    _todo_listo(session)
    resultado = autopilot.activar(session)
    assert resultado["enabled"] is True
    assert resultado["sources_watched"] == 1
    assert resultado["flows_auto"] == resultado["flows_total"]
