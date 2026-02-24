import os
import shutil
import uuid
import logging
import json
import asyncio
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime

from mangum import Mangum

# Add paths for imports
import sys
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
sys.path.append(str(root_dir / "with_langchain"))

from call_analyzer import CallAnalyzer
from with_langchain.main import CallAnalysisApp
from db_utils import get_connection, get_cursor
from s3_utils import upload_file_to_s3, download_file_from_s3

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("unified_api")

app = FastAPI(
    title="Unified Call Analysis API",
    description="Asynchronous call analysis combining Pre-built models and LangChain agents",
    version="2.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize engines
prebuilt_analyzer = CallAnalyzer()
langchain_app = CallAnalysisApp(model_name="gpt-5.1") 

# Lambda-compatible upload dir
UPLOAD_DIR = "/tmp/uploaded_audio_unified"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def extract_prebuilt_result(raw_result):
    """
    Standardizes Pre-built model result into a unified schema for the frontend.
    """
    try:
        if not raw_result:
            return None
        if isinstance(raw_result, str):
            raw_result = json.loads(raw_result)
        
        # Mapping pre-built keys to unified keys
        return {
            "primary_intent": raw_result.get("intent", "Unknown"),
            "sentiment": raw_result.get("sentiment", "Neutral"),
            "tone": raw_result.get("emotion", "Neutral"),
            "conversation_rating": float(raw_result.get("agent_score", 0)) / 10.0, # Convert 0-100 to 1-10
            "summary": raw_result.get("summary") or raw_result.get("transcript", "")[:200] + "...",
            "follow_up_tasks": raw_result.get("follow_up_tasks", []),
            "requirements": raw_result.get("requirements", []),
            "raw_agent_score": float(raw_result.get("agent_score", 0))
        }
    except Exception as e:
        logger.error(f"Error extracting prebuilt result: {str(e)}")
        return {"error": str(e)}


def extract_langchain_result(raw_result):
    """
    Standardizes LangChain model result into the same unified schema.
    """
    try:
        if not raw_result:
            return None
        if isinstance(raw_result, str):
            raw_result = json.loads(raw_result)
        
        # Check if result is nested under 'analysis' key (common in our LangChain app)
        analysis = raw_result.get("analysis", raw_result)
        
        return {
            "primary_intent": analysis.get("primary_intent", analysis.get("intent", "Unknown")),
            "sentiment": analysis.get("sentiment", "Neutral"),
            "tone": analysis.get("tone", analysis.get("emotion", "Neutral")),
            "conversation_rating": float(analysis.get("conversation_rating", 0)), # Already 1-10
            "summary": analysis.get("summary", ""),
            "follow_up_tasks": (analysis.get("follow_up_tasks") or analysis.get("action_items") or []),
            "requirements": analysis.get("requirements", []),
            "raw_agent_score": float(analysis.get("conversation_rating", 0)) * 10.0
        }
    except Exception as e:
        logger.error(f"Error extracting langchain result: {str(e)}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Background Tasks
# ---------------------------------------------------------------------------

async def background_transcribe(call_id: int, file_path: str):
    """Background task to transcribe audio files."""
    try:
        logger.info(f"Starting background transcription for call_id: {call_id}")
        
        transcript, duration = prebuilt_analyzer.audio_to_text(file_path)
        
        conn = get_connection()
        cursor = get_cursor(conn)
        cursor.execute(
            "UPDATE calls SET transcript = %s, call_duration = %s, status = 'TRANSCRIBED' WHERE call_id = %s",
            (transcript, duration, call_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Transcription complete for call_id: {call_id}")
        
    except Exception as e:
        logger.error(f"❌ Transcription failed for {call_id}: {str(e)}")
        try:
            conn = get_connection()
            cursor = get_cursor(conn)
            cursor.execute("UPDATE calls SET status = 'FAILED' WHERE call_id = %s", (call_id,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as db_err:
            logger.error(f"Failed to update DB on transcription error: {str(db_err)}")


async def background_analyze(call_id: int):
    """Background task to perform analysis on transcribed text."""
    conn = None
    try:
        logger.info(f"Starting background analysis for call_id: {call_id}")
        
        # Update status to ANALYZING
        conn = get_connection()
        cursor = get_cursor(conn)
        cursor.execute("UPDATE calls SET status = 'ANALYZING' WHERE call_id = %s", (call_id,))
        conn.commit()
        
        # Get transcript from DB
        cursor.execute("SELECT transcript FROM calls WHERE call_id = %s", (call_id,))
        row = cursor.fetchone()
        transcript = row[0] if row else None
        cursor.close()
        conn.close()
        conn = None

        if not transcript:
            raise ValueError("No transcript found for analysis")

        logger.info(f"Processing transcript for call_id: {call_id} (length: {len(transcript)} chars)")

        # 1. Pre-built Analysis
        logger.info(f"Running pre-built analysis for call_id: {call_id}")
        try:
            raw_prebuilt = prebuilt_analyzer.process_text(transcript, call_id=call_id)
            prebuilt_res = extract_prebuilt_result(raw_prebuilt)
            logger.info(f"Pre-built analysis complete for call_id: {call_id}")
            logger.debug(f"Formatted pre-built result: {json.dumps(prebuilt_res, default=str)}")
        except Exception as prebuilt_err:
            logger.error(f"Pre-built analysis failed: {str(prebuilt_err)}")
            prebuilt_res = {"error": str(prebuilt_err), "status": "failed"}
        
        # 2. LangChain Analysis
        logger.info(f"Running LangChain analysis for call_id: {call_id}")
        try:
            raw_langchain = await langchain_app.analyze_call(transcript=transcript, session_id=str(call_id))
            langchain_res = extract_langchain_result(raw_langchain)
            logger.info(f"LangChain analysis complete for call_id: {call_id}")
            logger.debug(f"Formatted langchain result: {json.dumps(langchain_res, default=str)}")
        except Exception as langchain_err:
            logger.error(f"LangChain analysis failed: {str(langchain_err)}")
            langchain_res = {"error": str(langchain_err), "status": "failed"}
        
        # Store BOTH formatted results in database
        logger.info(f"Storing both analysis results for call_id: {call_id}")
        conn = get_connection()
        cursor = get_cursor(conn)
        
        cursor.execute(
            """UPDATE calls 
               SET prebuilt_result = %s, 
                   langchain_result = %s, 
                   status = 'COMPLETED' 
               WHERE call_id = %s""",
            (json.dumps(prebuilt_res, default=str), json.dumps(langchain_res, default=str), call_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        conn = None
        
        logger.info(f"✅ Analysis complete for call_id: {call_id} - Both results stored!")
        
    except Exception as e:
        logger.error(f"❌ Analysis failed for {call_id}: {str(e)}", exc_info=True)
        try:
            if conn is None:
                conn = get_connection()
            cursor = get_cursor(conn)
            cursor.execute("UPDATE calls SET status = 'FAILED' WHERE call_id = %s", (call_id,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as db_err:
            logger.error(f"Failed to update DB on analysis error: {str(db_err)}")

# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class TextAnalysisRequest(BaseModel):
    text: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "Unified Call Analysis API",
        "version": "2.2.0"
    }


@app.post("/text")
async def analyze_text_input(request: TextAnalysisRequest, background_tasks: BackgroundTasks):
    """Endpoint to analyze text directly (no transcription needed)."""
    try:
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")

        conn = get_connection()
        cursor = get_cursor(conn)
        cursor.execute(
            "INSERT INTO calls (transcript, status) VALUES (%s, 'TRANSCRIBED') RETURNING call_id",
            (request.text,)
        )
        call_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        
        # Start analysis immediately for text input
        background_tasks.add_task(background_analyze, call_id)
        
        logger.info(f"Received text input | call_id={call_id}")
        return {"call_id": call_id, "status": "TRANSCRIBED", "message": "Analysis started"}
        
    except Exception as e:
        logger.error(f"Text analysis trigger failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Endpoint to upload audio files."""
    local_path = None
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Invalid file")

        # Save to local /tmp
        local_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"File saved locally: {local_path}")

        # Upload to S3
        s3_key = upload_file_to_s3(local_path, prefix="raw-audio/")
        logger.info(f"File uploaded to S3: {s3_key}")

        # Create DB entry
        conn = get_connection()
        cursor = get_cursor(conn)
        cursor.execute(
            "INSERT INTO calls (audio_file, s3_key, status) VALUES (%s, %s, 'PENDING') RETURNING call_id",
            (file.filename, s3_key)
        )
        call_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        
        # Start background transcription
        background_tasks.add_task(background_transcribe, call_id, local_path)
        
        logger.info(f"✅ Uploaded {file.filename} -> call_id={call_id}. Starting transcription.")
        return {"call_id": call_id, "status": "PENDING"}
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process/{call_id}")
async def trigger_analysis(call_id: int, background_tasks: BackgroundTasks):
    """Endpoint to manually trigger analysis for a transcribed call."""
    conn = get_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT status FROM calls WHERE call_id = %s", (call_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Call ID not found")
    
    status = row[0]
    if status == 'COMPLETED' or status == 'ANALYZING':
        return {"status": status, "message": "Call is already being analyzed or completed"}
    
    # Start background analysis
    background_tasks.add_task(background_analyze, call_id)
    logger.info(f"Analysis triggered for call_id: {call_id}")
    return {"call_id": call_id, "status": "ANALYZING"}


@app.get("/status/{call_id}")
async def get_status(call_id: int):
    """Poll status and results. Returns BOTH pre-built and LangChain results."""
    conn = get_connection()
    cursor = get_cursor(conn, use_dict_cursor=True)
    
    cursor.execute("SELECT * FROM calls WHERE call_id = %s", (call_id,))
    call = cursor.fetchone()
    
    if not call:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Call ID not found")
    
    cursor.close()
    conn.close()
    
    # === Parse Pre-built Result ===
    prebuilt_result = None
    if call.get('prebuilt_result'):
        try:
            if isinstance(call['prebuilt_result'], str):
                prebuilt_result = json.loads(call['prebuilt_result'])
            else:
                prebuilt_result = call['prebuilt_result']
            logger.debug(f"Prebuilt result for call_id {call_id}: {prebuilt_result}")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse prebuilt_result for call_id {call_id}")
            prebuilt_result = None
    
    # === Parse LangChain Result ===
    langchain_result = None
    if call.get('langchain_result'):
        try:
            if isinstance(call['langchain_result'], str):
                langchain_result = json.loads(call['langchain_result'])
            else:
                langchain_result = call['langchain_result']
            logger.debug(f"LangChain result for call_id {call_id}: {langchain_result}")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse langchain_result for call_id {call_id}")
            langchain_result = None

    return {
        "call_id": call.get('call_id'),
        "status": call.get('status'),
        "transcript": call.get('transcript'),
        "prebuilt_result": prebuilt_result,
        "langchain_result": langchain_result,
        "created_at": str(call.get('created_at')) if call.get('created_at') else None
    }

# Lambda handler
handler = Mangum(app, lifespan="off")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)