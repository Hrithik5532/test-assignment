import os
import shutil
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mangum import Mangum

# ---- Local Imports ----
import sys
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
sys.path.append(str(root_dir / "with_langchain"))

from call_analyzer import CallAnalyzer
from with_langchain.main import CallAnalysisApp
from db_utils import get_connection, get_cursor
from s3_utils import upload_file_to_s3

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lambda_api")

# ------------------------------------------------------------
# FastAPI App
# ------------------------------------------------------------
app = FastAPI(
    title="Unified Call Analysis API",
    description="Lambda-Optimized Synchronous Call Analysis",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# Initialize Engines (Cold Start Initialization)
# ------------------------------------------------------------
prebuilt_analyzer = CallAnalyzer()
langchain_app = CallAnalysisApp(model_name="gpt-5.1")

UPLOAD_DIR = "/tmp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ------------------------------------------------------------
# Request Model
# ------------------------------------------------------------
class TextAnalysisRequest(BaseModel):
    text: str

# ------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------
def extract_prebuilt_result(raw_result):
    try:
        if not raw_result:
            return None

        if isinstance(raw_result, str):
            raw_result = json.loads(raw_result)

        return {
            "primary_intent": raw_result.get("intent", "Unknown"),
            "sentiment": raw_result.get("sentiment", "Neutral"),
            "tone": raw_result.get("emotion", "Neutral"),
            "conversation_rating": float(raw_result.get("agent_score", 0)) / 10.0,
            "summary": raw_result.get("summary", ""),
            "follow_up_tasks": raw_result.get("follow_up_tasks", []),
            "requirements": raw_result.get("requirements", []),
            "raw_agent_score": float(raw_result.get("agent_score", 0))
        }
    except Exception as e:
        logger.error(f"Prebuilt extraction error: {str(e)}")
        return {"error": str(e)}


def extract_langchain_result(raw_result):
    try:
        if not raw_result:
            return None

        if isinstance(raw_result, str):
            raw_result = json.loads(raw_result)

        analysis = raw_result.get("analysis", raw_result)

        return {
            "primary_intent": analysis.get("primary_intent", "Unknown"),
            "sentiment": analysis.get("sentiment", "Neutral"),
            "tone": analysis.get("tone", "Neutral"),
            "conversation_rating": float(analysis.get("conversation_rating", 0)),
            "summary": analysis.get("summary", ""),
            "follow_up_tasks": analysis.get("follow_up_tasks", []),
            "requirements": analysis.get("requirements", []),
            "raw_agent_score": float(analysis.get("conversation_rating", 0)) * 10
        }
    except Exception as e:
        logger.error(f"LangChain extraction error: {str(e)}")
        return {"error": str(e)}

# ------------------------------------------------------------
# Health Check
# ------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Lambda Call Analysis API",
        "version": "3.0.0"
    }

# ------------------------------------------------------------
# TEXT ANALYSIS (Fully Sync)
# ------------------------------------------------------------
@app.post("/text-sync")
async def analyze_text_sync(request: TextAnalysisRequest):
    try:
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")

        conn = get_connection()
        cursor = get_cursor(conn)

        cursor.execute(
            "INSERT INTO calls (transcript, status) VALUES (%s, 'ANALYZING') RETURNING call_id",
            (request.text,)
        )
        call_id = cursor.fetchone()[0]
        conn.commit()

        transcript = request.text

        # --- Prebuilt ---
        raw_prebuilt = prebuilt_analyzer.process_text(transcript, call_id=call_id)
        prebuilt_res = extract_prebuilt_result(raw_prebuilt)

        # --- LangChain ---
        raw_langchain = await langchain_app.analyze_call(
            transcript=transcript,
            session_id=str(call_id)
        )
        langchain_res = extract_langchain_result(raw_langchain)

        cursor.execute(
            """UPDATE calls
               SET prebuilt_result=%s,
                   langchain_result=%s,
                   status='COMPLETED'
               WHERE call_id=%s""",
            (json.dumps(prebuilt_res),
             json.dumps(langchain_res),
             call_id)
        )

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "call_id": call_id,
            "status": "COMPLETED",
            "prebuilt_result": prebuilt_res,
            "langchain_result": langchain_res
        }

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------
# AUDIO UPLOAD + TRANSCRIBE + ANALYZE (Fully Sync)
# ------------------------------------------------------------
@app.post("/upload-sync")
async def upload_audio_sync(file: UploadFile = File(...)):
    local_path = None
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Invalid file")

        local_path = os.path.join(UPLOAD_DIR, file.filename)

        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Upload to S3
        s3_key = upload_file_to_s3(local_path, prefix="raw-audio/")

        conn = get_connection()
        cursor = get_cursor(conn)

        cursor.execute(
            "INSERT INTO calls (audio_file, s3_key, status) VALUES (%s,%s,'ANALYZING') RETURNING call_id",
            (file.filename, s3_key)
        )
        call_id = cursor.fetchone()[0]
        conn.commit()

        # --- Transcription ---
        transcript, duration = prebuilt_analyzer.audio_to_text(local_path)

        cursor.execute(
            "UPDATE calls SET transcript=%s, call_duration=%s WHERE call_id=%s",
            (transcript, duration, call_id)
        )
        conn.commit()

        # --- Prebuilt Analysis ---
        raw_prebuilt = prebuilt_analyzer.process_text(transcript, call_id=call_id)
        prebuilt_res = extract_prebuilt_result(raw_prebuilt)

        # --- LangChain Analysis ---
        raw_langchain = await langchain_app.analyze_call(
            transcript=transcript,
            session_id=str(call_id)
        )
        langchain_res = extract_langchain_result(raw_langchain)

        cursor.execute(
            """UPDATE calls
               SET prebuilt_result=%s,
                   langchain_result=%s,
                   status='COMPLETED'
               WHERE call_id=%s""",
            (json.dumps(prebuilt_res),
             json.dumps(langchain_res),
             call_id)
        )

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "call_id": call_id,
            "status": "COMPLETED",
            "duration": duration,
            "prebuilt_result": prebuilt_res,
            "langchain_result": langchain_res
        }

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

# ------------------------------------------------------------
# Lambda Handler
# ------------------------------------------------------------
handler = Mangum(app, lifespan="off")

# ------------------------------------------------------------
# Local Run
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)