"""Paper Forge Assistant API: the open issues of a finished job and a conversation about fixing them."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents import assistant
from app.routes.deps import Services, services
from app.routes.jobs import TERMINAL, _job_or_404
from app.services.settings_store import redact
from app.services.workspace import JobWorkspace

router = APIRouter(prefix="/api/jobs", tags=["assistant"])


class Question(BaseModel):
    question: str = Field(default="", max_length=assistant.MAX_QUESTION_CHARS)
    issue_id: str | None = Field(default=None, max_length=100)


def _paper(svc: Services, job_id: str) -> assistant.JobPaper:
    job = _job_or_404(svc, job_id)
    if job.status not in TERMINAL:
        raise HTTPException(409, "The assistant opens when the job has finished.")
    paper = assistant.load_paper(JobWorkspace(svc.settings.jobs_dir, job_id), svc.registry, job.venue_id)
    if paper is None:
        raise HTTPException(409, "This job has no compliance report, so the assistant has nothing to work from. "
                                 "Upload the paper again.")
    return paper


@router.get("/{job_id}/assistant")
def get_assistant(job_id: str, svc: Services = Depends(services)) -> dict:
    paper = _paper(svc, job_id)
    provider = assistant.ai_provider(svc.settings_store.load())
    return {"issues": [i.public() for i in paper.issues], "messages": assistant.load_chat(paper.chat_path),
            "ai": provider.name if provider else None, "privacy": assistant.privacy_line(provider)}


@router.post("/{job_id}/assistant")
def ask_assistant(job_id: str, body: Question, svc: Services = Depends(services)) -> dict:
    paper = _paper(svc, job_id)
    settings = svc.settings_store.load()
    question = redact(body.question.strip(), settings)
    issue = None
    if body.issue_id:
        issue = paper.issue(body.issue_id)
        if issue is None:
            raise HTTPException(400, "That issue is not in this job's report.")
    elif not question:
        raise HTTPException(400, "Type a question, or press \"Help me fix this\" next to an issue.")
    history = assistant.load_chat(paper.chat_path)
    cleared = assistant.times_cleared(paper.chat_path)
    messages = [assistant.user_message(question, issue),
                assistant.reply(paper, question, issue, history, settings)]
    assistant.add_to_chat(paper.chat_path, messages, cleared)
    return {"messages": messages}


@router.delete("/{job_id}/assistant")
def clear_assistant(job_id: str, svc: Services = Depends(services)) -> dict:
    assistant.clear_chat(_paper(svc, job_id).chat_path)
    return {"cleared": True}
