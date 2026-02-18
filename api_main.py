
import os
import shutil
import uuid
import logging
import sqlite3
import asyncio
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import json

# Add paths for imports
import sys
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
sys.path.append(str(root_dir / "with_langchain"))

from call_analyzer import CallAnalyzer
from with_langchain.main import CallAnalysisApp

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("unified_api")

app = FastAPI(
    title="Unified Call Analysis API",
    description="Asynchronous call analysis combining Pre-built models and LangChain agents",
    version="1.0.0"
)

# Initialize engines
prebuilt_analyzer = CallAnalyzer(db_path="production_calls.db")
langchain_app = CallAnalysisApp(model_name="qwen3")

UPLOAD_DIR = "uploaded_audio_unified"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class StatusResponse(BaseModel):
    call_id: int
    status: str
    transcript: Optional[str] = None
    prebuilt_result: Optional[dict] = None
    langchain_result: Optional[dict] = None
    created_at: str

async def background_transcribe(call_id: int, file_path: str):
    try:
        logger.info(f"Starting transcription for call_id: {call_id}")
        # Use prebuilt_analyzer to transcribe
        transcript, duration = prebuilt_analyzer.audio_to_text(file_path)
        
        # Update database with transcript and status
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE calls SET transcript = ?, call_duration = ?, status = 'TRANSCRIBED' WHERE call_id = ?",
            (transcript, duration, call_id)
        )
        conn.commit()
        conn.close()
        logger.info(f"Transcription complete for call_id: {call_id}")
    except Exception as e:
        logger.error(f"Transcription failed for {call_id}: {str(e)}")
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE calls SET status = 'FAILED' WHERE call_id = ?", (call_id,))
        conn.commit()
        conn.close()

async def background_analyze(call_id: int):
    try:
        logger.info(f"Starting analysis for call_id: {call_id}")
        
        # Get transcript from DB
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute("SELECT transcript FROM calls WHERE call_id = ?", (call_id,))
        transcript = cursor.fetchone()[0]
        conn.close()

        if not transcript:
            raise ValueError("No transcript found for analysis")

        # Run both in parallel
        # Note: prebuilt_analyzer.process_text handles its own DB saving, 
        # but we want to capture the result for the unified response/storage too.
        
        # 1. Pre-built Analysis
        prebuilt_res = prebuilt_analyzer.process_text(transcript, call_id=call_id)
        
        # 2. LangChain Analysis
        # langchain_app.analyze_call returns a dict with 'analysis' key
        langchain_res = await langchain_app.analyze_call(transcript=transcript, session_id=str(call_id))
        
        # Update DB with LangChain result and status
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE calls SET langchain_result = ?, status = 'COMPLETED' WHERE call_id = ?",
            (json.dumps(langchain_res), call_id)
        )
        conn.commit()
        conn.close()
        logger.info(f"Analysis complete for call_id: {call_id}")
        
    except Exception as e:
        logger.error(f"Analysis failed for {call_id}: {str(e)}")
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE calls SET status = 'FAILED' WHERE call_id = ?", (call_id,))
        conn.commit()
        conn.close()

@app.get("/")
async def root():
    return {"status": "online", "service": "Unified Call Analysis API"}

class TextAnalysisRequest(BaseModel):
    text: str

@app.post("/text")
async def analyze_text_input(request: TextAnalysisRequest):
    try:
        # Create DB entry with transcript already present
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO calls (transcript, status) VALUES (?, 'TRANSCRIBED')",
            (request.text,)
        )
        call_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return {"call_id": call_id, "status": "TRANSCRIBED"}
        
    except Exception as e:
        logger.error(f"Text analysis trigger failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        # Create DB entry
        conn = sqlite3.connect("production_calls.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO calls (audio_file, status) VALUES (?, 'PENDING')",
            (file.filename,)
        )
        call_id = cursor.lastrowid
        conn.commit()
        conn.close()

        file_path = os.path.join(UPLOAD_DIR, f"{call_id}_{file.filename}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Start background transcription
        background_tasks.add_task(background_transcribe, call_id, file_path)
        
        return {"call_id": call_id, "status": "PENDING"}
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process/{call_id}")
async def trigger_analysis(call_id: int, background_tasks: BackgroundTasks):
    # Check if transcribed
    conn = sqlite3.connect("production_calls.db")
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM calls WHERE call_id = ?", (call_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Call ID not found")
    
    status = row[0]
    if status != 'TRANSCRIBED' and status != 'PENDING': # Allow pending for text
        return {"status": status, "message": "Call is not ready for analysis yet"}
    
    # Start background analysis
    background_tasks.add_task(background_analyze, call_id)
    return {"call_id": call_id, "status": "ANALYZING"}

@app.get("/status/{call_id}")
async def get_status(call_id: int):
    conn = sqlite3.connect("production_calls.db")
    # Use Row factory for easier dict access
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,))
    call = cursor.fetchone()
    
    if not call:
        conn.close()
        raise HTTPException(status_code=404, detail="Call ID not found")
    
    # Get associated tickets and agent scores (Pre-built data)
    cursor.execute("SELECT * FROM tickets WHERE call_id = ?", (call_id,))
    tickets = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM agent_responses WHERE call_id = ?", (call_id,))
    agent_data = cursor.fetchone()
    
    conn.close()
    
    # Format results
    prebuilt_result = None
    if call['status'] in ['COMPLETED', 'ANALYZING'] and call['intent']:
        prebuilt_result = {
            "call_id": call['call_id'],
            "intent": call['intent'],
            "intent_confidence": call['intent_confidence'],
            "sentiment": call['sentiment'],
            "sentiment_score": call['sentiment_score'],
            "emotion": call['emotion'],
            "agent_score": call['agent_score'],
            "requirements": tickets,
            "duration": call['call_duration'],
            "transcript": call['transcript']
        }

    langchain_result = None
    if call['langchain_result']:
        langchain_result = json.loads(call['langchain_result'])

    return {
        "call_id": call['call_id'],
        "status": call['status'],
        "transcript": call['transcript'],
        "prebuilt_result": prebuilt_result,
        "langchain_result": langchain_result,
        "created_at": call['created_at']
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
