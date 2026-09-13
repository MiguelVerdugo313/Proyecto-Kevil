"""Cola de trabajos en segundo plano.

Todo lo pesado (descargar, cortar, renderizar, publicar) pasa por aquí para que
la interfaz no se quede bloqueada nunca. Es una cola sencilla apoyada en la
propia base de datos: sobrevive a reinicios del programa.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.models import Job, JobStatus, utcnow

Handler = Callable[[Session, "JobContext"], None]

_handlers: dict[str, Handler] = {}
_claim_lock = threading.Lock()


def register(kind: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _handlers[kind] = func
        return func

    return decorator


class JobContext:
    """Acceso cómodo al trabajo actual desde dentro del manejador."""

    def __init__(self, session: Session, job: Job):
        self.session = session
        self.job = job
        self.payload: dict[str, Any] = job.payload or {}
        self._last_write = 0.0

    def progress(self, value: float, message: str = "") -> None:
        self.job.progress = max(0.0, min(1.0, float(value)))
        if message:
            self.job.message = message[:400]
        now = time.time()
        if now - self._last_write > 0.8:
            self._last_write = now
            self.session.commit()

    def log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.job.log = ((self.job.log or "") + f"[{stamp}] {line}\n")[-8000:]
        self.session.commit()


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 100,
    message: str = "",
    dedupe: bool = True,
    run_at: datetime | None = None,
) -> Job:
    payload = payload or {}
    if dedupe:
        existing = session.scalars(
            select(Job).where(
                Job.kind == kind,
                Job.status.in_([JobStatus.pending.value, JobStatus.running.value]),
            )
        ).all()
        for job in existing:
            if (job.payload or {}) == payload:
                return job

    job = Job(
        kind=kind, payload=payload, priority=priority, message=message,
        run_at=run_at or utcnow(),
    )
    session.add(job)
    session.flush()
    return job


class Worker(threading.Thread):
    def __init__(self, index: int, stop_event: threading.Event):
        super().__init__(name=f"kevil-worker-{index}", daemon=True)
        self.stop_event = stop_event

    def _claim(self) -> int | None:
        with _claim_lock, session_scope() as session:
            job = session.scalars(
                select(Job)
                .where(
                    Job.status == JobStatus.pending.value,
                    # los trabajos de una base anterior no tienen hora: van ya
                    or_(Job.run_at.is_(None), Job.run_at <= utcnow()),
                )
                .order_by(Job.priority.asc(), Job.created_at.asc())
                .limit(1)
            ).first()
            if not job:
                return None
            session.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(
                    status=JobStatus.running.value,
                    started_at=utcnow(),
                    attempts=job.attempts + 1,
                )
            )
            return job.id

    def run(self) -> None:  # pragma: no cover - hilo de fondo
        while not self.stop_event.is_set():
            job_id = None
            try:
                job_id = self._claim()
            except Exception:
                traceback.print_exc()

            if job_id is None:
                self.stop_event.wait(1.5)
                continue

            with session_scope() as session:
                job = session.get(Job, job_id)
                if not job:
                    continue
                handler = _handlers.get(job.kind)
                context = JobContext(session, job)
                try:
                    if handler is None:
                        raise RuntimeError(f"No hay manejador para «{job.kind}»")
                    handler(session, context)
                    job.status = JobStatus.done.value
                    job.progress = 1.0
                    job.finished_at = utcnow()
                except Exception as exc:  # noqa: BLE001
                    job.status = JobStatus.failed.value
                    job.error = f"{exc}\n{traceback.format_exc()}"[:4000]
                    job.message = str(exc)[:400]
                    job.finished_at = utcnow()


class JobRunner:
    def __init__(self, workers: int | None = None):
        self.stop_event = threading.Event()
        self.workers: list[Worker] = []
        self.size = max(1, int(workers or settings.workers))

    def start(self) -> None:
        # los trabajos que se quedaron a medias vuelven a la cola
        with session_scope() as session:
            session.execute(
                update(Job)
                .where(Job.status == JobStatus.running.value)
                .values(status=JobStatus.pending.value, message="Reanudado tras reiniciar")
            )
        for index in range(self.size):
            worker = Worker(index + 1, self.stop_event)
            worker.start()
            self.workers.append(worker)

    def stop(self) -> None:
        self.stop_event.set()
        for worker in self.workers:
            worker.join(timeout=2)
        self.workers.clear()


runner = JobRunner()
