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
    # Se pueden configurar los dos proveedores: si uno falla, se usa el otro.
    ai_primary: str = "openrouter"          # cuál se intenta primero

    openrouter_api_key: str = ""
    openrouter_text_model: str = ""
    openrouter_image_model: str = ""
    openrouter_base_url: str = ""           # sólo para pruebas o pasarelas

    nvidia_api_key: str = ""
    nvidia_text_model: str = ""
    nvidia_image_model: str = ""
    nvidia_base_url: str = ""
    nvidia_image_base_url: str = ""

    # --- Datos del canal (contexto para el asistente) --------------------
    channel_topic: str = ""          # de qué va tu canal
    channel_language: str = "es"
    # Colores de tu marca (se pueden sacar del avatar de tu canal)
    brand_accent: str = ""
    brand_accent_2: str = ""
    brand_source: str = ""
    target_uploads_per_week: float = 2.0
    notifications_desktop: bool = True

    # --- Espacio en disco -------------------------------------------------
    # Kevil no está pensado para dejarte el disco lleno de vídeos: por defecto
    # baja sólo los trozos que va a usar y borra todo en cuanto lo publica.
    light_mode: bool = True           # descargar sólo los tramos de cada clip
    keep_originals: bool = False      # guardar el vídeo original al terminar
    keep_clips: bool = False          # guardar el .mp4 del clip tras publicarlo
    disk_budget_gb: float = 3.0       # tope de la carpeta de medios (0 = sin tope)

    # Modo simulación: procesa y programa todo pero no publica de verdad.
    dry_run: bool = False

    # --- Ventana de la aplicación ----------------------------------------
    window_mode: str = "app"          # «app» = ventana propia, «navegador»

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
    def branding_path(self) -> Path:
        """Tu marca: logos, fondos, fotos y tipografías que quieras que use.

        Es una carpeta normal: metes ahí tus archivos y Kevil los reconoce solo
        por lo que son (un PNG con transparencia es un logo, una imagen ancha es
        un fondo, un .ttf es una tipografía…).
        """
        return self.data_path / "branding"

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
            self.branding_path,
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
