"""Conector de inteligencia artificial.

Admite dos proveedores, ambos con API compatible con OpenAI:

* **OpenRouter** — https://openrouter.ai  (una sola clave, cientos de modelos,
  incluidos modelos de imagen).
* **NVIDIA NIM** — https://build.nvidia.com  (clave gratuita con créditos;
  texto por `integrate.api.nvidia.com` e imagen por `ai.api.nvidia.com`).

Todo lo que pide la aplicación pasa por aquí, y **nada es obligatorio**: si no
hay clave configurada, cada función tiene una alternativa que funciona sin IA
(peor, pero funciona). Así el programa nunca se queda bloqueado.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

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
            "qwen/qwen-2.5-72b-instruct",
        ],
        "image_models": [
            "google/gemini-2.5-flash-image-preview",
            "black-forest-labs/flux-1.1-pro",
        ],
        "supports_images": True,
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "keys_url": "https://build.nvidia.com",
        "text_models": [
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "mistralai/mistral-large-2-instruct",
            "qwen/qwen2.5-7b-instruct",
        ],
        "image_models": [
            "black-forest-labs/flux.1-dev",
            "stabilityai/stable-diffusion-3.5-large",
        ],
        "image_base_url": "https://ai.api.nvidia.com/v1/genai",
        "supports_images": True,
    },
}


class AIError(RuntimeError):
    pass


class AINotConfigured(AIError):
    pass


@dataclass
class AIConfig:
    provider: str
    api_key: str
    text_model: str
    image_model: str
    base_url: str

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.api_key)


def current_config() -> AIConfig:
    provider = (settings.ai_provider or "").strip().lower()
    meta = PROVIDERS.get(provider, {})
    return AIConfig(
        provider=provider,
        api_key=(settings.ai_api_key or "").strip(),
        text_model=(settings.ai_text_model or "").strip()
        or (meta.get("text_models") or [""])[0],
        image_model=(settings.ai_image_model or "").strip()
        or (meta.get("image_models") or [""])[0],
        base_url=(settings.ai_base_url or "").strip() or meta.get("base_url", ""),
    )


def is_enabled() -> bool:
    return current_config().enabled


def status() -> dict[str, Any]:
    config = current_config()
    meta = PROVIDERS.get(config.provider, {})
    return {
        "enabled": config.enabled,
        "provider": config.provider,
        "provider_label": meta.get("label", ""),
        "text_model": config.text_model,
        "image_model": config.image_model,
        "images_supported": bool(meta.get("supports_images")) and config.enabled,
        "providers": {
            key: {
                "label": value["label"],
                "keys_url": value["keys_url"],
                "text_models": value["text_models"],
                "image_models": value["image_models"],
            }
            for key, value in PROVIDERS.items()
        },
    }


# --------------------------------------------------------------------------
# Texto
# --------------------------------------------------------------------------
def _headers(config: AIConfig) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    if config.provider == "openrouter":
        # OpenRouter pide identificar la aplicación
        headers["HTTP-Referer"] = "http://localhost/kevil-studio"
        headers["X-Title"] = "Kevil Studio"
    return headers


def chat(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1600,
    config: AIConfig | None = None,
) -> str:
    """Una consulta de texto. Devuelve la respuesta en crudo."""
    config = config or current_config()
    if not config.enabled:
        raise AINotConfigured(
            "No hay proveedor de IA configurado. Añade tu clave en Ajustes → Inteligencia artificial."
        )

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": config.text_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers=_headers(config),
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise AIError(f"No se ha podido contactar con {config.provider}: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:400]
        if response.status_code in (401, 403):
            raise AIError("La clave de IA no es válida o no tiene permisos.")
        if response.status_code == 429:
            raise AIError("El proveedor de IA ha limitado las peticiones. Prueba en un rato.")
        raise AIError(f"El proveedor respondió {response.status_code}: {detail}")

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise AIError(f"Respuesta vacía del modelo: {str(data)[:300]}")
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):  # algunos modelos devuelven partes
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not content.strip():
        raise AIError("El modelo no ha devuelto texto.")
    return content.strip()


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
    # último recurso: el primer objeto o lista bien formados
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

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        raw = chat(
            prompt,
            system=system,
            temperature=temperature if attempt == 0 else min(0.3, temperature),
            max_tokens=max_tokens,
        )
        try:
            return extract_json(raw)
        except AIError as exc:
            last_error = exc
    raise last_error or AIError("No se ha podido interpretar la respuesta.")


def test_connection() -> dict[str, Any]:
    """Comprueba que la clave funciona (lo usa el botón «Probar» de Ajustes)."""
    config = current_config()
    if not config.enabled:
        raise AINotConfigured("Falta el proveedor o la clave.")
    answer = chat(
        "Responde exactamente con la palabra: LISTO",
        system="Eres un servicio de comprobación.",
        temperature=0,
        max_tokens=10,
    )
    return {
        "ok": True,
        "provider": config.provider,
        "model": config.text_model,
        "answer": answer[:80],
    }


# --------------------------------------------------------------------------
# Imagen
# --------------------------------------------------------------------------
def generate_image(prompt: str, *, width: int = 1280, height: int = 720) -> bytes:
    """Genera una imagen y devuelve los bytes (PNG o JPEG)."""
    config = current_config()
    if not config.enabled:
        raise AINotConfigured("No hay proveedor de IA configurado.")

    if config.provider == "nvidia":
        return _nvidia_image(config, prompt, width, height)
    return _openrouter_image(config, prompt)


def _openrouter_image(config: AIConfig, prompt: str) -> bytes:
    """OpenRouter devuelve las imágenes dentro del mensaje del chat."""
    payload = {
        "model": config.image_model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{config.base_url}/chat/completions", headers=_headers(config), json=payload
        )
    if response.status_code >= 400:
        raise AIError(f"Error al generar la imagen ({response.status_code}): {response.text[:300]}")

    data = response.json()
    choices = data.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    for image in message.get("images") or []:
        url = ((image or {}).get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1])
        if url.startswith("http"):
            with httpx.Client(timeout=TIMEOUT) as client:
                return client.get(url).content
    raise AIError("El modelo no ha devuelto ninguna imagen.")


def _nvidia_image(config: AIConfig, prompt: str, width: int, height: int) -> bytes:
    base = PROVIDERS["nvidia"]["image_base_url"]
    payload = {
        "prompt": prompt[:1000],
        "width": width,
        "height": height,
        "cfg_scale": 3.5,
        "steps": 30,
        "seed": 0,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{base}/{config.image_model}",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise AIError(f"Error al generar la imagen ({response.status_code}): {response.text[:300]}")

    data = response.json()
    for key in ("image", "b64_json"):
        if isinstance(data.get(key), str):
            return base64.b64decode(data[key])
    for artifact in data.get("artifacts") or []:
        if artifact.get("base64"):
            return base64.b64decode(artifact["base64"])
    raise AIError("La respuesta no contiene ninguna imagen.")
