from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime, timezone

demo_app = FastAPI(title="Existing Notes API")

NOTES_DB = [
    {"id": 1, "title": "Q3 Architecture Review", "content": "Migrate legacy APIs behind PlanGate.", "created_at": "2026-10-18T10:00:00Z"},
    {"id": 2, "title": "Advantix Hackathon Pitch", "content": "Highlight zero-code retrofit and explainable blocks.", "created_at": "2026-10-18T11:30:00Z"}
]

class NoteCreate(BaseModel):
    title: str
    content: str

@demo_app.get("/notes")
def list_notes():
    return {"count": len(NOTES_DB), "notes": NOTES_DB}

@demo_app.post("/notes")
def create_note(note: NoteCreate):
    new_note = {
        "id": len(NOTES_DB) + 1,
        "title": note.title,
        "content": note.content,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    NOTES_DB.append(new_note)
    return {"status": "created", "note": new_note}

@demo_app.get("/export")
def export_notes():
    csv_lines = ["id,title,content,created_at"]
    for n in NOTES_DB:
        csv_lines.append(f'{n["id"]},"{n["title"]}","{n["content"]}",{n["created_at"]}')
    return {"export_format": "CSV", "record_count": len(NOTES_DB), "data": "\n".join(csv_lines)}
