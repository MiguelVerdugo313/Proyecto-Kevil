"""Configuración global de la aplicación.

Todo se guarda en local: no hay servidor remoto, ni base de datos en la nube.
El directorio de datos por defecto es ./data (junto al programa) y puede
cambiarse con la variable de entorno KEVIL_DATA_DIR.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KEVIL_",
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Servidor local -------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8756
    open_browser: bool = True

    # --- Almacenamiento -------------------------------------------------
    data_dir: str = str(BASE_DIR / "data")

    # --- Binarios externos ----------------------------------------------
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    # --- Motor de trabajos ----------------------------------------------
    workers: int = 2
    watch_interval_minutes: int = 15
    publisher_interval_seconds: int = 60

    # --- Credenciales de plataformas (opcionales) ------------------------
    # YouTube funciona sin credenciales (vía yt-dlp). Sólo hacen falta para
    # canales privados o para leer analíticas con la API oficial.
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_api_key: str = ""

    # TikTok: necesarias para publicar automáticamente.
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""

    # --- Inteligencia artificial (opcional) ------------------------------
    # Proveedor: "openrouter" o "nvidia". Sin clave, todo funciona igual pero
    # con generación local en vez de IA.
    ai_provider: str = ""
    ai_api_key: str = ""
    ai_text_model: str = ""
    ai_image_model: str = ""
    ai_base_url: str = ""

    # --- Datos del canal (contexto para el asistente) --------------------
    channel_topic: str = ""          # de qué va tu canal
    channel_language: str = "es"
    target_uploads_per_week: float = 2.0
    notifications_desktop: bool = True

    # Modo simulación: procesa y programa todo pero no publica de verdad.
    dry_run: bool = False

    # --- Rutas derivadas -------------------------------------------------
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.data_path / "kevil.db"

    @property
    def media_path(self) -> Path:
        return self.data_path / "media"

    @property
    def sources_path(self) -> Path:
        """Vídeos originales descargados de YouTube."""
        return self.media_path / "originales"

    @property
    def clips_path(self) -> Path:
        """Clips verticales ya renderizados."""
        return self.media_path / "clips"

    @property
    def thumbs_path(self) -> Path:
        return self.media_path / "miniaturas"

    @property
    def work_path(self) -> Path:
        return self.data_path / "temp"

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def fonts_path(self) -> Path:
        """Tipografías propias: basta con dejar aquí los .ttf que quieras usar."""
        return self.data_path / "fonts"

    @property
    def redirect_base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_path,
            self.media_path,
            self.sources_path,
            self.clips_path,
            self.thumbs_path,
            self.work_path,
            self.logs_path,
            self.fonts_path,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # --- Comprobaciones --------------------------------------------------
    def ffmpeg_available(self) -> bool:
        return shutil.which(self.ffmpeg_path) is not None or os.path.isfile(self.ffmpeg_path)

    def ffprobe_available(self) -> bool:
        return shutil.which(self.ffprobe_path) is not None or os.path.isfile(self.ffprobe_path)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
