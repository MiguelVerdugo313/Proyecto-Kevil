"""Modelo de datos de Kevil Studio.

Flujo general:

    Canal de YouTube  ->  Vídeo original  ->  (Flujo)  ->  Clips verticales
                                                              |
                                                              v
                                                    Publicaciones en TikTok
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Enumeraciones (se guardan como texto para que la BD sea legible)
# --------------------------------------------------------------------------
class Platform(str, enum.Enum):
    youtube = "youtube"
    tiktok = "tiktok"


class AccountStatus(str, enum.Enum):
    connected = "connected"       # conectada y operativa
    needs_auth = "needs_auth"     # falta autorizar / token caducado
    error = "error"
    disabled = "disabled"


class VideoStatus(str, enum.Enum):
    discovered = "discovered"     # detectado en el canal
    queued = "queued"             # en cola de descarga
    downloading = "downloading"
    ready = "ready"               # descargado y analizado
    processing = "processing"     # generando clips
    done = "done"                 # clips generados
    error = "error"
    ignored = "ignored"


class ClipStatus(str, enum.Enum):
    draft = "draft"               # segmento propuesto, sin renderizar
    rendering = "rendering"
    rendered = "rendered"         # vídeo vertical listo
    approved = "approved"         # aprobado para publicar
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    rejected = "rejected"


class PostStatus(str, enum.Enum):
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    cancelled = "cancelled"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


# --------------------------------------------------------------------------
# Tablas
# --------------------------------------------------------------------------
class Account(Base):
    """Una cuenta conectada: un canal de YouTube o un perfil de TikTok."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    handle: Mapped[str] = mapped_column(String(200), default="")
    external_id: Mapped[str] = mapped_column(String(200), default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default=AccountStatus.connected.value)
    status_detail: Mapped[str] = mapped_column(Text, default="")

    # Credenciales OAuth (sólo en tu disco). access_token/refresh_token/expires_at
    credentials: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Estado de la cuenta usado por el motor de horarios: seguidores, cadencia...
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Estrategia editable de publicación (ver services/timing.py)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sources: Mapped[list["Source"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        foreign_keys="Source.account_id",
    )


class Source(Base):
    """Origen de contenido a vigilar: canal, playlist o lista de directos."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500))
    channel_id: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(20), default="channel")  # channel|playlist|lives

    # Automatización
    auto_ingest: Mapped[bool] = mapped_column(Boolean, default=True)
    include_lives: Mapped[bool] = mapped_column(Boolean, default=True)
    include_shorts: Mapped[bool] = mapped_column(Boolean, default=False)
    min_duration_s: Mapped[int] = mapped_column(Integer, default=120)
    backfill_limit: Mapped[int] = mapped_column(Integer, default=20)

    flow_id: Mapped[int | None] = mapped_column(
        ForeignKey("flows.id", ondelete="SET NULL"), nullable=True
    )
    target_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped[Account | None] = relationship(
        back_populates="sources", foreign_keys=[account_id]
    )
    videos: Mapped[list["Video"]] = relationship(back_populates="source")


class Video(Base):
    """Vídeo original: de YouTube (subida o directo) o subido desde tu disco."""

    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("external_id", name="uq_video_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    origin: Mapped[str] = mapped_column(String(20), default="youtube")  # youtube|local
    title: Mapped[str] = mapped_column(String(400), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    thumbnail_url: Mapped[str] = mapped_column(String(500), default="")
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    was_live: Mapped[bool] = mapped_column(Boolean, default=False)

    local_path: Mapped[str] = mapped_column(String(700), default="")
    transcript: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    probe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Rendimiento del vídeo en YouTube (lo devuelve yt-dlp al sincronizar)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)

    # Kit de publicación generado: títulos, descripción, etiquetas, miniaturas…
    kit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(20), default=VideoStatus.discovered.value)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source: Mapped[Source | None] = relationship(back_populates="videos")
    clips: Mapped[list["Clip"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )


class Flow(Base):
    """Flujo de trabajo editable: cómo se corta, se edita y se publica."""

    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="⚡")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Lista ordenada de pasos: [{"type": "segment", "enabled": true, "config": {...}}, ...]
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    clips: Mapped[list["Clip"]] = relationship(back_populates="flow")


class Clip(Base):
    """Un trozo vertical generado a partir de un vídeo original."""

    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    flow_id: Mapped[int | None] = mapped_column(
        ForeignKey("flows.id", ondelete="SET NULL"), nullable=True
    )

    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300), default="")
    hook: Mapped[str] = mapped_column(String(300), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)

    start_s: Mapped[float] = mapped_column(Float, default=0.0)
    end_s: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(300), default="")

    render_path: Mapped[str] = mapped_column(String(700), default="")
    thumb_path: Mapped[str] = mapped_column(String(700), default="")
    render_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    words: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(20), default=ClipStatus.draft.value)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    video: Mapped[Video] = relationship(back_populates="clips")
    flow: Mapped[Flow | None] = relationship(back_populates="clips")
    posts: Mapped[list["Post"]] = relationship(
        back_populates="clip", cascade="all, delete-orphan"
    )

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


class Post(Base):
    """Publicación programada o ya realizada en TikTok."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))

    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=PostStatus.scheduled.value)
    slot_score: Mapped[float] = mapped_column(Float, default=0.0)
    slot_reason: Mapped[str] = mapped_column(String(300), default="")

    external_post_id: Mapped[str] = mapped_column(String(200), default="")
    publish_id: Mapped[str] = mapped_column(String(200), default="")
    share_url: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    clip: Mapped[Clip] = relationship(back_populates="posts")
    account: Mapped[Account] = relationship()


class Job(Base):
    """Trabajo en segundo plano (descargar, cortar, renderizar, publicar)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.pending.value, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(400), default="")
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Setting(Base):
    """Ajustes globales editables desde la interfaz."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MetricSample(Base):
    """Histórico de rendimiento: alimenta el motor de mejores horas."""

    __tablename__ = "metric_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    followers: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Notification(Base):
    """Avisos del asistente: cadencia, ideas, cosas que requieren tu atención."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="general", index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info|warn|success|error
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    action_label: Mapped[str] = mapped_column(String(80), default="")
    action_url: Mapped[str] = mapped_column(String(200), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Idea(Base):
    """Propuesta de contenido: qué juego o tema grabar y por qué."""

    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    topic: Mapped[str] = mapped_column(String(200), default="")      # el juego o tema
    title: Mapped[str] = mapped_column(String(300), default="")      # título propuesto
    hook: Mapped[str] = mapped_column(Text, default="")
    angle: Mapped[str] = mapped_column(Text, default="")             # el enfoque
    reason: Mapped[str] = mapped_column(Text, default="")            # por qué encaja
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    score: Mapped[float] = mapped_column(Float, default=0.0)         # oportunidad 0..1
    demand: Mapped[float] = mapped_column(Float, default=0.0)        # interés medido
    competition: Mapped[float] = mapped_column(Float, default=0.0)   # saturación
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[str] = mapped_column(String(20), default="ia")    # ia|canal
    status: Mapped[str] = mapped_column(String(20), default="nueva")  # nueva|guardada|descartada


class EventLog(Base):
    """Registro de actividad mostrado en el panel."""

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info|warn|error|success
    scope: Mapped[str] = mapped_column(String(40), default="app")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
