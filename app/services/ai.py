"""Conector de inteligencia artificial, con respaldo automático.

Puedes tener configurados **los dos proveedores a la vez**:

* **OpenRouter** — https://openrouter.ai  (una clave, cientos de modelos).
* **NVIDIA NIM** — https://build.nvidia.com  (créditos gratuitos).

Se usa el que hayas marcado como principal y, si falla (se acaban los créditos,
te limitan por peticiones, se cae el servicio…), se pasa solo al otro y lo
apunta en el registro. Si no hay ninguno configurado, cada función tiene una
alternativa local: peor, pero la aplicación nunca se queda bloqueada.
"""

from __future__ import annotations

import base64
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from app.config import settings

TIMEOUT = httpx.Timeout(30.0, read=180.0)

PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_url": "https://openrouter.ai/keys",
        "text_models": [
            "google/gemini-2.5-flash",
            "anthropic/claude-sonnet-4.5",
            "openai/gpt-4.1-mini",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "image_models": [
            "google/gemini-2.5-flash-image-preview",
            "black-forest-labs/flux-1.1-pro",
        ],
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "image_base_url": "https://ai.api.nvidia.com/v1/genai",
        "keys_url": "https://build.nvidia.com",
        "text_models": [
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "mistralai/mistral-large-2-instruct",
        ],
        "image_models": [
            "black-forest-labs/flux.1-dev",
            "stabilityai/stable-diffusion-3.5-large",
        ],
    },
}

# Se recuerda cuál se usó por última vez y cuántas veces hubo que cambiar
_estado: dict[str, Any] = {"ultimo": "", "ultimo_modelo": "", "fallos": {}, "cambios": 0}
_lock = threading.Lock()


class AIError(RuntimeError):
    pass


class AINotConfigured(AIError):
    pass


@dataclass
class Provider:
    key: str
    api_key: str
    text_model: str
    image_model: str
    base_url: str
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------
def _provider(key: str) -> Provider | None:
    meta = PROVIDERS.get(key)
    if not meta:
        return None
    api_key = (getattr(settings, f"{key}_api_key", "") or "").strip()
    if not api_key:
        return None
    return Provider(
        key=key,
        api_key=api_key,
        text_model=(getattr(settings, f"{key}_text_model", "") or "").strip()
        or meta["text_models"][0],
        image_model=(getattr(settings, f"{key}_image_model", "") or "").strip()
        or meta["image_models"][0],
        base_url=(getattr(settings, f"{key}_base_url", "") or "").strip() or meta["base_url"],
        label=meta["label"],
        meta=meta,
    )


def configured_providers() -> list[Provider]:
    """Los proveedores disponibles, en orden de preferencia."""
    principal = (settings.ai_primary or "openrouter").strip().lower()
    orden = [principal] + [k for k in PROVIDERS if k != principal]
    return [p for p in (_provider(key) for key in orden) if p]


def is_enabled() -> bool:
    return bool(configured_providers())


def last_used() -> str:
    """Proveedor y modelo que atendieron la última petición."""
    if _estado["ultimo"]:
        return f"{_estado['ultimo']}/{_estado['ultimo_modelo']}"
    disponibles = configured_providers()
    return f"{disponibles[0].key}/{disponibles[0].text_model}" if disponibles else ""


def status() -> dict[str, Any]:
    disponibles = configured_providers()
    return {
        "enabled": bool(disponibles),
        "primary": (settings.ai_primary or "openrouter"),
        "active": [
            {
                "key": p.key,
                "label": p.label,
                "text_model": p.text_model,
                "image_model": p.image_model,
            }
            for p in disponibles
        ],
        "has_backup": len(disponibles) > 1,
        "last_used": _estado["ultimo"],
        "failovers": _estado["cambios"],
        "failures": dict(_estado["fallos"]),
        "images_supported": bool(disponibles),
        "providers": {
            key: {
                "label": value["label"],
                "keys_url": value["keys_url"],
                "text_models": value["text_models"],
                "image_models": value["image_models"],
                "configured": _provider(key) is not None,
            }
            for key, value in PROVIDERS.items()
        },
    }


# --------------------------------------------------------------------------
# Llamadas con respaldo
# --------------------------------------------------------------------------
def _headers(provider: Provider) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    if provider.key == "openrouter":
        headers["HTTP-Referer"] = "http://localhost/kevil-studio"
        headers["X-Title"] = "Kevil Studio"
    return headers


def _describe_error(response: httpx.Response) -> str:
    if response.status_code in (401, 403):
        return "la clave no es válida o no tiene permisos"
    if response.status_code == 402:
        return "se han acabado los créditos"
    if response.status_code == 429:
        return "demasiadas peticiones seguidas"
    if response.status_code >= 500:
        return f"el servicio no responde ({response.status_code})"
    return f"error {response.status_code}: {response.text[:200]}"


def _con_respaldo(operacion: Callable[[Provider], Any], que: str) -> Any:
    """Ejecuta la operación probando los proveedores uno tras otro."""
    disponibles = configured_providers()
    if not disponibles:
        raise AINotConfigured(
            "No hay ninguna clave de IA configurada. Añádela en Ajustes → Inteligencia artificial."
        )

    errores: list[str] = []
    for indice, provider in enumerate(disponibles):
        try:
            resultado = operacion(provider)
        except AIError as exc:
            errores.append(f"{provider.label}: {exc}")
            with _lock:
                _estado["fallos"][provider.key] = str(exc)[:200]
                if indice + 1 < len(disponibles):
                    _estado["cambios"] += 1
            continue

        with _lock:
            _estado["ultimo"] = provider.key
            _estado["ultimo_modelo"] = provider.text_model
            _estado["fallos"].pop(provider.key, None)
        return resultado

    raise AIError(f"No se ha podido {que}. " + " · ".join(errores))


def chat(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1600,
) -> str:
    """Una consulta de texto, con cambio automático de proveedor si hace falta."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    def pedir(provider: Provider) -> str:
        payload = {
            "model": provider.text_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=_headers(provider),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise AIError(f"no se ha podido conectar ({exc})") from exc

        if response.status_code >= 400:
            raise AIError(_describe_error(response))

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise AIError("respuesta vacía")
        content = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not content.strip():
            raise AIError("no ha devuelto texto")
        return content.strip()

    return _con_respaldo(pedir, "generar el texto")


def extract_json(text: str) -> Any:
    """Saca el JSON de una respuesta aunque venga con explicaciones alrededor."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opening, closing in (("{", "}"), ("[", "]")):
        start = text.find(opening)
        end = text.rfind(closing)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise AIError("El modelo no ha devuelto un JSON válido.")


def chat_json(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    retries: int = 1,
) -> Any:
    """Consulta esperando JSON, con un reintento si el modelo se despista."""
    instruction = (
        "Responde ÚNICAMENTE con JSON válido, sin texto antes ni después, "
        "sin bloques de código y sin comentarios."
    )
    system = f"{system}\n\n{instruction}".strip() if system else instruction

    ultimo: Exception | None = None
    for intento in range(retries + 1):
        raw = chat(
            prompt,
            system=system,
            temperature=temperature if intento == 0 else min(0.3, temperature),
            max_tokens=max_tokens,
        )
        try:
            return extract_json(raw)
        except AIError as exc:
            ultimo = exc
    raise ultimo or AIError("No se ha podido interpretar la respuesta.")


def test_connection(only: str = "") -> dict[str, Any]:
    """Comprueba cada proveedor configurado. Lo usa el botón «Probar»."""
    disponibles = [p for p in configured_providers() if not only or p.key == only]
    if not disponibles:
        raise AINotConfigured("No hay ninguna clave configurada.")

    resultados = []
    for provider in disponibles:
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=_headers(provider),
                    json={
                        "model": provider.text_model,
                        "messages": [{"role": "user", "content": "Responde: LISTO"}],
                        "max_tokens": 10,
                        "temperature": 0,
                    },
                )
            if response.status_code >= 400:
                resultados.append(
                    {"provider": provider.key, "label": provider.label,
                     "ok": False, "detail": _describe_error(response)}
                )
                continue
            texto = (
                ((response.json().get("choices") or [{}])[0].get("message") or {})
                .get("content") or ""
            )
            resultados.append(
                {"provider": provider.key, "label": provider.label, "ok": True,
                 "model": provider.text_model, "detail": str(texto)[:60].strip()}
            )
        except Exception as exc:
            resultados.append(
                {"provider": provider.key, "label": provider.label,
                 "ok": False, "detail": str(exc)[:160]}
            )
    return {"ok": any(r["ok"] for r in resultados), "results": resultados}


# --------------------------------------------------------------------------
# Imagen
# --------------------------------------------------------------------------
def generate_image(prompt: str, *, width: int = 1280, height: int = 720) -> bytes:
    """Genera una imagen; también cambia de proveedor si el primero falla."""

    def pedir(provider: Provider) -> bytes:
        if provider.key == "nvidia":
            return _nvidia_image(provider, prompt, width, height)
        return _openrouter_image(provider, prompt)

    return _con_respaldo(pedir, "generar la imagen")


def _openrouter_image(provider: Provider, prompt: str) -> bytes:
    payload = {
        "model": provider.image_model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{provider.base_url}/chat/completions",
                headers=_headers(provider), json=payload,
            )
    except httpx.HTTPError as exc:
        raise AIError(f"no se ha podido conectar ({exc})") from exc
    if response.status_code >= 400:
        raise AIError(_describe_error(response))

    message = ((response.json().get("choices") or [{}])[0].get("message") or {})
    for image in message.get("images") or []:
        url = ((image or {}).get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1])
        if url.startswith("http"):
            with httpx.Client(timeout=TIMEOUT) as client:
                return client.get(url).content
    raise AIError("no ha devuelto ninguna imagen")


def _nvidia_image(provider: Provider, prompt: str, width: int, height: int) -> bytes:
    base = (
        (settings.nvidia_image_base_url or "").strip()
        or PROVIDERS["nvidia"]["image_base_url"]
    )
    payload = {
        "prompt": prompt[:1000], "width": width, "height": height,
        "cfg_scale": 3.5, "steps": 30, "seed": 0,
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{base}/{provider.image_model}",
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise AIError(f"no se ha podido conectar ({exc})") from exc
    if response.status_code >= 400:
        raise AIError(_describe_error(response))

    data = response.json()
    for key in ("image", "b64_json"):
        if isinstance(data.get(key), str):
            return base64.b64decode(data[key])
    for artifact in data.get("artifacts") or []:
        if artifact.get("base64"):
            return base64.b64decode(artifact["base64"])
    raise AIError("la respuesta no contiene ninguna imagen")
