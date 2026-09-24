"""Proveedores de IA: la lista de claves, sus modelos de verdad y la prueba."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.bootstrap import save_settings
from app.config import settings
from app.db import get_db
from app.services import ai

router = APIRouter(prefix="/api/ia", tags=["ia"])


def _tapada(clave: str) -> str:
    """La clave nunca vuelve entera a la interfaz: sólo sus 4 últimas letras."""
    clave = (clave or "").strip()
    if not clave:
        return ""
    return "••••" + clave[-4:] if len(clave) > 8 else "••••"


def _fila(key: str) -> dict[str, Any]:
    """Un proveedor tal como lo ve la interfaz (configurado o no)."""
    principal = (settings.ai_primary or "openrouter")
    estado = ai.status()
    if key in ai.PROVIDERS:
        meta = ai.PROVIDERS[key]
        clave = getattr(settings, f"{key}_api_key", "") or ""
        proveedor = ai._provider(key)
        return {
            "id": key, "tipo": key, "nombre": meta["label"], "fijo": True,
            "clave": _tapada(clave), "tiene_clave": bool(clave),
            "modelo": proveedor.text_model if proveedor else meta["text_models"][0],
            "base_url": meta["base_url"], "activo": bool(clave),
            "keys_url": meta["keys_url"], "principal": principal == key,
            "fallo": estado["failures"].get(key, ""), "imagenes": True,
            "aviso": estado["model_changes"].get(key, ""),
        }
    item = next((i for i in ai.extras() if i["id"] == key), None)
    if item is None:
        raise HTTPException(404, "Proveedor no encontrado")
    meta = ai.CATALOGO.get(item.get("tipo", ""), ai.CATALOGO["personalizado"])
    proveedor = ai._extra(key)
    return {
        "id": key, "tipo": item.get("tipo", "personalizado"),
        "nombre": item.get("nombre") or meta["label"], "fijo": False,
        "clave": _tapada(item.get("api_key", "")),
        "tiene_clave": bool(item.get("api_key")) or bool(meta.get("sin_clave")),
        "modelo": proveedor.text_model if proveedor else (item.get("modelo") or ""),
        "base_url": item.get("base_url") or meta.get("base_url", ""),
        "activo": bool(item.get("activo", True)),
        "keys_url": meta.get("keys_url", ""), "principal": principal == key,
        "fallo": estado["failures"].get(key, ""), "imagenes": False,
        "aviso": estado["model_changes"].get(key, ""),
    }


def _todo() -> dict[str, Any]:
    estado = ai.status()
    return {
        "proveedores": [_fila(key) for key in ai.orden_de_proveedores()],
        "catalogo": [
            {"tipo": tipo, "nombre": meta["label"], "base_url": meta.get("base_url", ""),
             "keys_url": meta.get("keys_url", ""), "nota": meta.get("nota", ""),
             "sin_clave": bool(meta.get("sin_clave"))}
            for tipo, meta in ai.CATALOGO.items()
        ],
        "activos": len(estado["active"]),
        "ultimo": estado["last_used"],
        "cambios": estado["failovers"],
    }


def _guardar_extras(db: Session, lista: list[dict[str, Any]]) -> None:
    save_settings(db, {"ia_proveedores": lista})
    db.commit()


@router.get("")
def listar():
    return _todo()


class NuevoIn(BaseModel):
    tipo: str
    api_key: str = ""
    base_url: str = ""
    nombre: str = ""
    modelo: str = ""


@router.post("/proveedores")
def anadir(body: NuevoIn, db: Session = Depends(get_db)):
    tipo = body.tipo.strip().lower()
    if tipo not in ai.CATALOGO:
        raise HTTPException(400, "Proveedor desconocido")
    meta = ai.CATALOGO[tipo]
    clave = body.api_key.strip()
    if not clave and not meta.get("sin_clave"):
        raise HTTPException(400, "Falta la clave de API")
    base = (body.base_url or meta.get("base_url") or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "Pon la dirección del servicio (empieza por https://)")

    # OpenRouter y NVIDIA tienen su hueco de siempre: si está libre, va ahí
    if tipo in ai.PROVIDERS and not getattr(settings, f"{tipo}_api_key", ""):
        cambios = {f"{tipo}_api_key": clave}
        if body.modelo:
            cambios[f"{tipo}_text_model"] = body.modelo.strip()
        save_settings(db, cambios)
        db.commit()
        return {"id": tipo, **_todo()}

    lista = ai.extras()
    nuevo = {
        "id": ai.nuevo_id(tipo), "tipo": tipo, "nombre": body.nombre.strip() or meta["label"],
        "api_key": clave, "base_url": base, "modelo": body.modelo.strip(), "activo": True,
    }
    if sum(1 for i in lista if i.get("tipo") == tipo) or tipo in ai.PROVIDERS:
        # segunda clave del mismo sitio: se numera para distinguirlas
        repetidas = 1 + sum(1 for i in lista if i.get("tipo") == tipo) + (tipo in ai.PROVIDERS)
        nuevo["nombre"] = f"{meta['label']} ({repetidas})"
    lista.append(nuevo)
    _guardar_extras(db, lista)
    # si no había ninguno configurado, éste pasa a ser el principal
    if len(ai.configured_providers()) == 1:
        save_settings(db, {"ai_primary": nuevo["id"]})
        db.commit()
    return {"id": nuevo["id"], **_todo()}


class CambioIn(BaseModel):
    api_key: str | None = None
    modelo: str | None = None
    activo: bool | None = None
    nombre: str | None = None
    base_url: str | None = None


@router.patch("/proveedores/{key}")
def cambiar(key: str, body: CambioIn, db: Session = Depends(get_db)):
    clave = (body.api_key or "").strip()
    if clave.startswith("••••"):
        clave = ""                            # la tapada no pisa la de verdad
    if key in ai.PROVIDERS:
        cambios: dict[str, Any] = {}
        if clave:
            cambios[f"{key}_api_key"] = clave
        if body.modelo is not None:
            cambios[f"{key}_text_model"] = body.modelo.strip()
        save_settings(db, cambios)
        db.commit()
        return _todo()

    lista = ai.extras()
    item = next((i for i in lista if i["id"] == key), None)
    if item is None:
        raise HTTPException(404, "Proveedor no encontrado")
    if clave:
        item["api_key"] = clave
    if body.modelo is not None:
        item["modelo"] = body.modelo.strip()
    if body.activo is not None:
        item["activo"] = bool(body.activo)
    if body.nombre:
        item["nombre"] = body.nombre.strip()[:60]
    if body.base_url:
        item["base_url"] = body.base_url.strip().rstrip("/")
    _guardar_extras(db, lista)
    return _todo()


@router.delete("/proveedores/{key}")
def quitar(key: str, db: Session = Depends(get_db)):
    if key in ai.PROVIDERS:
        save_settings(db, {f"{key}_api_key": "", f"{key}_text_model": ""})
        settings.__setattr__(f"{key}_api_key", "")
    else:
        _guardar_extras(db, [i for i in ai.extras() if i["id"] != key])
    if (settings.ai_primary or "") == key:
        restantes = ai.configured_providers()
        save_settings(db, {"ai_primary": restantes[0].key if restantes else "openrouter"})
    db.commit()
    return _todo()


class PrincipalIn(BaseModel):
    id: str


@router.post("/principal")
def principal(body: PrincipalIn, db: Session = Depends(get_db)):
    if body.id not in ai.orden_de_proveedores():
        raise HTTPException(404, "Proveedor no encontrado")
    save_settings(db, {"ai_primary": body.id})
    db.commit()
    return _todo()


class OrdenIn(BaseModel):
    ids: list[str]


@router.post("/orden")
def ordenar(body: OrdenIn, db: Session = Depends(get_db)):
    """Cambia el orden de reserva de los añadidos (el primero de la lista manda)."""
    por_id = {i["id"]: i for i in ai.extras()}
    nueva = [por_id[i] for i in body.ids if i in por_id]
    nueva += [i for i in por_id.values() if i not in nueva]
    _guardar_extras(db, nueva)
    if body.ids:
        save_settings(db, {"ai_primary": body.ids[0]})
        db.commit()
    return _todo()


@router.get("/modelos")
def modelos(id: str, refrescar: bool = False):
    proveedor = ai._provider(id)
    if proveedor is None:
        raise HTTPException(400, "Pon antes la clave de este proveedor")
    try:
        lista = ai.listar_modelos(proveedor, refrescar=refrescar)
    except ai.AIError as exc:
        return {"modelos": [], "actual": proveedor.text_model, "recomendado": "",
                "error": str(exc)}
    return {
        "modelos": lista,
        "actual": proveedor.text_model,
        "recomendado": ai.recomendado(proveedor, lista, set()),
        "error": "",
    }


class ProbarIn(BaseModel):
    id: str | None = None


@router.post("/probar")
def probar(body: ProbarIn):
    try:
        resultado = ai.test_connection(only=body.id or "")
    except ai.AINotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**resultado, **_todo()}
