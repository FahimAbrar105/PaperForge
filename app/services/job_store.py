"""Persist jobs and their live event log in SQLite."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import Database
from app.models.job import FinalOutput, JobEvent, JobStatus, UploadedFile, UploadJob


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- jobs -------------------------------------------------------------
    def create(self, job: UploadJob) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO jobs (job_id, venue_id, status, current_step, created_at, updated_at, files_json,"
                " agentic_level, camera_ready) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.venue_id,
                    job.status.value,
                    job.current_step,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    json.dumps([f.model_dump() for f in job.files]),
                    job.agentic_level,
                    int(job.camera_ready),
                ),
            )

    def update(self, job_id: str, **fields: object) -> None:
        allowed = {"status", "current_step", "error", "overall_status", "title", "outputs_json",
                   "agentic_achieved"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unknown job field {key}")
            if isinstance(value, JobStatus):
                value = value.value
            sets.append(f"{key} = ?")
            values.append(value)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(job_id)
        with self.db.transaction() as c:
            c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?", tuple(values))

    def set_outputs(self, output: FinalOutput) -> None:
        self.update(output.job_id, outputs_json=output.model_dump_json())

    def get(self, job_id: str) -> UploadJob | None:
        rows = self.db.query("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        return self._row_to_job(rows[0]) if rows else None

    def get_outputs(self, job_id: str) -> FinalOutput | None:
        rows = self.db.query("SELECT outputs_json FROM jobs WHERE job_id = ?", (job_id,))
        if not rows or not rows[0]["outputs_json"]:
            return None
        return FinalOutput.model_validate_json(rows[0]["outputs_json"])

    def list(self, limit: int = 100) -> list[UploadJob]:
        rows = self.db.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_job(r) for r in rows]

    def delete(self, job_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM job_events WHERE job_id = ?", (job_id,))
            c.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def older_than(self, iso_cutoff: str) -> list[str]:
        rows = self.db.query(
            "SELECT job_id FROM jobs WHERE created_at < ? AND status NOT IN ('queued', 'running')",
            (iso_cutoff,),
        )
        return [r["job_id"] for r in rows]

    def mark_interrupted(self) -> int:
        """Jobs left running when the app stopped can never finish: mark them failed."""
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE jobs SET status = 'failed', error = 'Interrupted: Paper Forge was stopped while this job was running.',"
                " updated_at = ? WHERE status IN ('queued', 'running')",
                (_now(),),
            )
            return cur.rowcount

    @staticmethod
    def _row_to_job(row) -> UploadJob:
        return UploadJob(
            job_id=row["job_id"],
            venue_id=row["venue_id"],
            status=JobStatus(row["status"]),
            current_step=row["current_step"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            files=[UploadedFile(**f) for f in json.loads(row["files_json"] or "[]")],
            error=row["error"],
            overall_status=row["overall_status"],
            title=row["title"],
            agentic_level=row["agentic_level"] or "off",
            agentic_achieved=row["agentic_achieved"],
            camera_ready=bool(row["camera_ready"]),
        )

    # ---- events -----------------------------------------------------------
    def add_event(self, job_id: str, step: str, message: str, level: str = "info") -> JobEvent:
        ts = _now()
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO job_events (job_id, timestamp, step, level, message) VALUES (?, ?, ?, ?, ?)",
                (job_id, ts, step, level, message),
            )
            seq = cur.lastrowid or 0
        return JobEvent(job_id=job_id, seq=seq, timestamp=datetime.fromisoformat(ts), step=step, level=level, message=message)

    def events(self, job_id: str, after: int = 0) -> list[JobEvent]:
        rows = self.db.query(
            "SELECT * FROM job_events WHERE job_id = ? AND id > ? ORDER BY id", (job_id, after)
        )
        return [
            JobEvent(
                job_id=r["job_id"],
                seq=r["id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                step=r["step"],
                level=r["level"],
                message=r["message"],
            )
            for r in rows
        ]
