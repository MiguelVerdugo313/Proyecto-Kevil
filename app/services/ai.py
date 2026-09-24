"""Conector de inteligencia artificial, con respaldo automático.

Puedes tener configurados **varios proveedores a la vez**, y varias claves del
mismo si quieres:

* **OpenRouter** y **NVIDIA NIM**, los de siempre;
* y los que añadas de la lista: Groq, Google Gemini, Mistral, Cerebras,
  DeepSeek, OpenAI, Together, Hugging Face, Ollama en tu propio PC o cualquier
  servicio compatible con la API de OpenAI.

Se usa el que hayas marcado como principal y, si falla (se acaban los créditos,
te limitan por peticiones, se cae el servicio…), se pasa solo al siguiente y lo
apunta en el registro. Si el modelo elegido se retira (como le pasó a
«meta/llama-3.1-8b-instruct» en NVIDIA), se busca otro disponible en ese mismo
proveedor, se queda guardado y se sigue. Sin ninguno configurado, cada función
tiene una alternativa local: peor, pero la aplicación nunca se queda bloqueada.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
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
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "qwen/qwen3-235b-a22b",
            "deepseek-ai/deepseek-v3.1",
            "openai/gpt-oss-120b",
            "mistralai/mistral-medium-3-instruct",
        ],
        "image_models": [
            "black-forest-labs/flux.1-dev",
            "stabilityai/stable-diffusion-3.5-large",
        ],
    },
}

# Los que se pueden añadir a la lista. Todos hablan la API de OpenAI
# (/chat/completions y /models), así que basta con la dirección y la clave.
CATALOGO: dict[str, dict[str, Any]] = {
    "openrouter": {**PROVIDERS["openrouter"], "nota": "Una clave, cientos de modelos (muchos gratis)."},
    "nvidia": {**PROVIDERS["nvidia"], "nota": "Créditos gratuitos al registrarte."},
    "groq": {
        "label": "Groq", "base_url": "https://api.groq.com/openai/v1",
        "keys_url": "https://console.groq.com/keys",
        "text_models": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen/qwen3-32b",
                        "llama-3.1-8b-instant"],
        "nota": "Gratis con límites generosos y muy rápido.",
    },
    "gemini": {
        "label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "keys_url": "https://aistudio.google.com/apikey",
        "text_models": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "nota": "Clave gratuita en Google AI Studio.",
    },
    "mistral": {
        "label": "Mistral", "base_url": "https://api.mistral.ai/v1",
        "keys_url": "https://console.mistral.ai/api-keys",
        "text_models": ["mistral-small-latest", "mistral-medium-latest", "open-mistral-nemo"],
        "nota": "Tiene un plan gratuito para pruebas.",
    },
    "cerebras": {
        "label": "Cerebras", "base_url": "https://api.cerebras.ai/v1",
        "keys_url": "https://cloud.cerebras.ai",
        "text_models": ["llama-3.3-70b", "gpt-oss-120b", "qwen-3-32b", "llama3.1-8b"],
        "nota": "Gratis con límite diario, rapidísimo.",
    },
    "deepseek": {
        "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
        "keys_url": "https://platform.deepseek.com/api_keys",
        "text_models": ["deepseek-chat"],
        "nota": "De pago, muy barato.",
    },
    "openai": {
        "label": "OpenAI", "base_url": "https://api.openai.com/v1",
        "keys_url": "https://platform.openai.com/api-keys",
        "text_models": ["gpt-4.1-mini", "gpt-4o-mini"],
        "nota": "De pago.",
    },
    "together": {
        "label": "Together AI", "base_url": "https://api.together.xyz/v1",
        "keys_url": "https://api.together.ai/settings/api-keys",
        "text_models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
        "nota": "Da un saldo inicial gratis.",
    },
    "huggingface": {
        "label": "Hugging Face", "base_url": "https://router.huggingface.co/v1",
        "keys_url": "https://huggingface.co/settings/tokens",
        "text_models": ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen3-32B"],
        "nota": "Saldo gratuito cada mes.",
    },
    "ollama": {
        "label": "Ollama (en tu PC)", "base_url": "http://localhost:11434/v1",
        "keys_url": "https://ollama.com/download", "sin_clave": True,
        "text_models": ["llama3.2", "qwen3", "gemma3"],
        "nota": "Gratis y sin internet: los modelos corren en tu ordenador.",
    },
    "personalizado": {
        "label": "Otro compatible con OpenAI", "base_url": "", "keys_url": "",
        "text_models": [],
        "nota": "Cualquier servicio con la API de OpenAI: pon su dirección y su clave.",
    },
}

# Modelos que sus dueños ya han retirado: si alguien los tenía elegidos, se
# olvidan y se usa el recomendado.
RETIRADOS = {"meta/llama-3.1-8b-instruct", "meta/llama3-70b-instruct", "meta/llama3-8b-instruct"}

# Lo que no sirve para escribir texto y aparece en las listas de /models.
NO_ES_DE_CHAT = (
    "embed", "rerank", "guard", "safety", "reward", "whisper", "tts", "asr", "ocr",
    "retriever", "parakeet", "clip", "flux", "stable-diffusion", "sdxl", "cosmos",
    "detector", "segment", "moderation", "dall-e", "image", "audio", "transcribe",
    "vision-only", "bge", "e5-", "nv-embed", "canary", "riva", "fastpitch",
)

# Se recuerda cuál se usó por última vez y cuántas veces hubo que cambiar
_estado: dict[str, Any] = {
    "ultimo": "", "ultimo_modelo": "", "fallos": {}, "cambios": 0,
    "modelos_cambiados": {},      # proveedor → «X se retiró; ahora usa Y»
}
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
    tipo: str = ""                  # openrouter, nvidia, groq… (para los añadidos)
    imagenes: bool = False


class ModeloRetirado(AIError):
    """El modelo elegido ya no existe en ese proveedor."""


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------
def _provider(key: str) -> Provider | None:
    meta = PROVIDERS.get(key)
    if not meta:
        return _extra(key)
    api_key = (getattr(settings, f"{key}_api_key", "") or "").strip()
    if not api_key:
        return None
    modelo = (getattr(settings, f"{key}_text_model", "") or "").strip()
    if modelo in RETIRADOS:
        modelo = ""
    return Provider(
        key=key,
        api_key=api_key,
        text_model=modelo or meta["text_models"][0],
        image_model=(getattr(settings, f"{key}_image_model", "") or "").strip()
        or meta["image_models"][0],
        base_url=(getattr(settings, f"{key}_base_url", "") or "").strip() or meta["base_url"],
        label=meta["label"],
        meta=meta,
        tipo=key,
        imagenes=True,
    )


def extras() -> list[dict[str, Any]]:
    """Los proveedores añadidos desde la lista (además de OpenRouter y NVIDIA)."""
    lista = getattr(settings, "ia_proveedores", None) or []
    return [dict(item) for item in lista if isinstance(item, dict) and item.get("id")]


def _extra(key: str) -> Provider | None:
    for item in extras():
        if item["id"] != key or not item.get("activo", True):
            continue
        meta = CATALOGO.get(item.get("tipo", ""), CATALOGO["personalizado"])
        api_key = (item.get("api_key") or "").strip()
        if not api_key and not meta.get("sin_clave"):
            return None
        base = (item.get("base_url") or meta.get("base_url") or "").strip().rstrip("/")
        if not base:
            return None
        modelo = (item.get("modelo") or "").strip()
        if modelo in RETIRADOS:
            modelo = ""
        return Provider(
            key=key,
            api_key=api_key or "sin-clave",
            text_model=modelo or (meta.get("text_models") or [""])[0],
            image_model="",
            base_url=base,
            label=item.get("nombre") or meta["label"],
            meta=meta,
            tipo=item.get("tipo", "personalizado"),
            imagenes=False,
        )
    return None


def orden_de_proveedores() -> list[str]:
    principal = (settings.ai_primary or "openrouter").strip()
    todos = list(PROVIDERS) + [item["id"] for item in extras()]
    return [principal] + [k for k in todos if k != principal] if principal in todos else todos


def configured_providers() -> list[Provider]:
    """Los proveedores disponibles, en orden de preferencia."""
    return [p for p in (_provider(key) for key in orden_de_proveedores()) if p]


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
        "model_changes": dict(_estado["modelos_cambiados"]),
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
        "extra_count": len(extras()),
    }


# --------------------------------------------------------------------------
# Llamadas con respaldo
# --------------------------------------------------------------------------
def _headers(provider: Provider) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    if provider.tipo == "openrouter" or provider.key == "openrouter":
        headers["HTTP-Referer"] = "http://localhost/kevil-studio"
        headers["X-Title"] = "Kevil Studio"
    return headers


def _es_modelo_retirado(response: httpx.Response) -> bool:
    if response.status_code in (404, 410):
        return True
    texto = response.text.lower()[:600]
    return response.status_code in (400, 422) and "model" in texto and any(
        marca in texto for marca in (
            "not found", "does not exist", "end of life", "no longer available",
            "not supported", "invalid model", "unknown model", "decommissioned",
        )
    )


def _describe_error(response: httpx.Response, modelo: str = "") -> str:
    if _es_modelo_retirado(response):
        return f"el modelo «{modelo}» ya no existe o lo han retirado" if modelo else (
            "el modelo elegido ya no existe o lo han retirado")
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
            try:
                resultado = operacion(provider)
            except ModeloRetirado:
                # El modelo se retiró: se busca otro en ese mismo proveedor, se
                # guarda para la próxima y se vuelve a intentar una vez.
                nuevo = reparar_modelo(provider)
                if not nuevo:
                    raise
                provider = replace(provider, text_model=nuevo)
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
            if _es_modelo_retirado(response):
                raise ModeloRetirado(_describe_error(response, provider.text_model))
            raise AIError(_describe_error(response, provider.text_model))

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
            response = _prueba(provider)
            reparado = ""
            if response.status_code >= 400 and _es_modelo_retirado(response):
                reparado = reparar_modelo(provider) or ""
                if reparado:
                    provider = replace(provider, text_model=reparado)
                    response = _prueba(provider)
            if response.status_code >= 400:
                resultados.append(
                    {"provider": provider.key, "label": provider.label,
                     "ok": False, "detail": _describe_error(response, provider.text_model)}
                )
                continue
            if reparado:
                resultados.append(
                    {"provider": provider.key, "label": provider.label, "ok": True,
                     "model": provider.text_model,
                     "detail": f"el modelo anterior se retiró; ahora usa {reparado}"}
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


def _prueba(provider: Provider) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT) as client:
        return client.post(
            f"{provider.base_url}/chat/completions",
            headers=_headers(provider),
            json={
                "model": provider.text_model,
                "messages": [{"role": "user", "content": "Responde: LISTO"}],
                "max_tokens": 10,
                "temperature": 0,
            },
        )


# --------------------------------------------------------------------------
# Modelos: la lista de verdad de cada proveedor
# --------------------------------------------------------------------------
_cache_modelos: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CACHE_MODELOS_S = 600


def _parece_de_chat(nombre: str) -> bool:
    bajo = nombre.lower()
    return not any(marca in bajo for marca in NO_ES_DE_CHAT)


def listar_modelos(provider: Provider, *, refrescar: bool = False) -> list[dict[str, Any]]:
    """Los modelos de texto que ese proveedor ofrece AHORA (no una lista fija).

    Por eso al elegir modelo salía sólo el básico: la lista era la de fábrica.
    Ahora se pregunta al proveedor y se marcan los gratuitos.
    """
    guardado = _cache_modelos.get(provider.key)
    if guardado and not refrescar and time.monotonic() - guardado[0] < CACHE_MODELOS_S:
        return guardado[1]
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0)) as client:
            response = client.get(f"{provider.base_url}/models", headers=_headers(provider))
    except httpx.HTTPError as exc:
        raise AIError(f"no se ha podido pedir la lista de modelos ({exc})") from exc
    if response.status_code >= 400:
        raise AIError(_describe_error(response))
    try:
        datos = response.json()
    except ValueError as exc:
        raise AIError("la lista de modelos no se entiende") from exc
    crudos = datos.get("data") if isinstance(datos, dict) else datos
    modelos: list[dict[str, Any]] = []
    for item in crudos or []:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("id") or item.get("name") or "").strip()
        if not nombre or not _parece_de_chat(nombre):
            continue
        precio = item.get("pricing") or {}
        gratis = nombre.endswith(":free") or (
            bool(precio) and str(precio.get("prompt")) in {"0", "0.0"}
            and str(precio.get("completion")) in {"0", "0.0"}
        )
        modelos.append({"id": nombre, "gratis": gratis,
                        "nombre": item.get("name") or nombre})
    preferidos = list(provider.meta.get("text_models") or [])
    modelos.sort(key=lambda m: (
        m["id"] not in preferidos,
        preferidos.index(m["id"]) if m["id"] in preferidos else 0,
        not m["gratis"],
        m["id"].lower(),
    ))
    _cache_modelos[provider.key] = (time.monotonic(), modelos)
    return modelos


def recomendado(provider: Provider, modelos: list[dict[str, Any]], evitar: set[str]) -> str:
    """El mejor modelo disponible: uno de los preferidos o, si no, uno «instruct»."""
    ids = [m["id"] for m in modelos if m["id"] not in evitar and m["id"] not in RETIRADOS]
    for preferido in provider.meta.get("text_models") or []:
        if preferido in ids:
            return preferido
    for marca in ("instruct", "chat", "versatile", "flash", "turbo"):
        for modelo in ids:
            if marca in modelo.lower():
                return modelo
    return ids[0] if ids else ""


def reparar_modelo(provider: Provider) -> str | None:
    """Busca otro modelo que funcione en ese proveedor y lo deja guardado."""
    try:
        modelos = listar_modelos(provider, refrescar=True)
    except AIError:
        return None
    nuevo = recomendado(provider, modelos, {provider.text_model})
    if not nuevo:
        return None
    guardar_modelo(provider.key, nuevo)
    with _lock:
        _estado["modelos_cambiados"][provider.key] = (
            f"«{provider.text_model}» se retiró; ahora usa «{nuevo}»"
        )
    return nuevo


def guardar_modelo(key: str, modelo: str) -> None:
    """Deja elegido el modelo de un proveedor (también para próximos arranques)."""
    try:
        from app.bootstrap import save_settings
        from app.db import session_scope
    except Exception:  # noqa: BLE001
        return
    if key in PROVIDERS:
        setattr(settings, f"{key}_text_model", modelo)
        cambios: dict[str, Any] = {f"{key}_text_model": modelo}
    else:
        lista = extras()
        for item in lista:
            if item["id"] == key:
                item["modelo"] = modelo
        settings.ia_proveedores = lista
        cambios = {"ia_proveedores": lista}
    try:
        with session_scope() as session:
            save_settings(session, cambios)
    except Exception:  # noqa: BLE001 - en pruebas puede no haber base de datos
        pass


def nuevo_id(tipo: str) -> str:
    return f"{tipo}-{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------
# Imagen
# --------------------------------------------------------------------------
def generate_image(prompt: str, *, width: int = 1280, height: int = 720) -> bytes:
    """Genera una imagen; también cambia de proveedor si el primero falla."""

    def pedir(provider: Provider) -> bytes:
        if not provider.imagenes:
            raise AIError("este proveedor no genera imágenes")
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
