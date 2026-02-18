
import os
import shutil
import uuid
import logging
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import asyncio

# Add the parent and child directory to sys.path to import modules correctly
import sys
from pathlib import Path
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
sys.path.append(str(root_dir / "with_langchain"))

from with_langchain.main import CallAnalysisApp

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langchain_api")

app = FastAPI(
    title="LangChain Call Analysis API",
    description="LLM-powered call analysis using LangChain agents",
    version="1.0.0"
)

# Initialize the application
# Using qwen3 as requested in the original code
analysis_app = CallAnalysisApp(model_name="qwen3")

UPLOAD_DIR = "uploaded_audio_langchain"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class TextAnalysisRequest(BaseModel):
    text: str
    session_id: Optional[str] = None

class AnalysisResponse(BaseModel):
    status: str
    session_id: str
    analysis: dict

@app.get("/")
async def root():
    return {"status": "online", "service": "LangChain Call Analysis API"}

@app.post("/analyze/audio", response_model=AnalysisResponse)
async def analyze_audio(file: UploadFile = File(...)):
    try:
        session_id = str(uuid.uuid4())
        file_path = os.path.join(UPLOAD_DIR, f"{session_id}_{file.filename}")
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Analyze using the LangChain app
        result = await analysis_app.analyze_call(
            audio_file=file_path,
            session_id=session_id
        )
        
        return AnalysisResponse(**result)
        
    except Exception as e:
        logger.error(f"Error in analyze_audio: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/text", response_model=AnalysisResponse)
async def analyze_text(request: TextAnalysisRequest):
    try:
        session_id = request.session_id or str(uuid.uuid4())
        
        # Analyze using the LangChain app
        result = await analysis_app.analyze_call(
            transcript=request.text,
            session_id=session_id
        )
        
        return AnalysisResponse(**result)
        
    except Exception as e:
        logger.error(f"Error in analyze_text: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
