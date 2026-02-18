
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import shutil
import os
from datetime import datetime
import sqlite3

from call_analyzer import CallAnalyzer

app = FastAPI(
    title="Pre-built Models Call Analysis API",
    description="Rule-based and pre-built ML model call analysis",
    version="1.0.0"
)

analyzer = CallAnalyzer(db_path="production_calls.db")

UPLOAD_DIR = "uploaded_audio_prebuilt"
os.makedirs(UPLOAD_DIR, exist_ok=True)


class CallAnalysisResponse(BaseModel):
    call_id: int
    intent: str
    intent_confidence: float
    sentiment: str
    sentiment_score: float
    emotion: str
    agent_score: float
    requirements: List[dict]
    duration: float
    transcript: str

class TextAnalysisRequest(BaseModel):
    text: str

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Pre-built Models Call Analysis API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/analyze/audio", response_model=CallAnalysisResponse)
async def analyze_audio(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        print(f"   Receiving file: {file.filename}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        print(f"   Saved file size: {file_size} bytes")
        
        result = analyzer.process_audio_file(file_path)
        
        return CallAnalysisResponse(
            call_id=result['call_id'],
            intent=result['intent']['intent'],
            intent_confidence=result['intent']['confidence'],
            sentiment=result['sentiment']['sentiment'],
            sentiment_score=result['sentiment']['sentiment_score'],
            emotion=result['sentiment']['emotion'],
            agent_score=result['agent_performance']['agent_score'],
            requirements=result['requirements'],
            duration=result['duration'],
            transcript=result['transcript']
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/text", response_model=CallAnalysisResponse)
async def analyze_text(request: TextAnalysisRequest):
    try:
        result = analyzer.process_text(request.text)
        
        return CallAnalysisResponse(
            call_id=result['call_id'],
            intent=result['intent']['intent'],
            intent_confidence=result['intent']['confidence'],
            sentiment=result['sentiment']['sentiment'],
            sentiment_score=result['sentiment']['sentiment_score'],
            emotion=result['sentiment']['emotion'],
            agent_score=result['agent_performance']['agent_score'],
            requirements=result['requirements'],
            duration=result['duration'],
            transcript=result['transcript']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/overall")
async def get_overall_stats():
    conn = sqlite3.connect(analyzer.db_path)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM calls')
    total_calls = cursor.fetchone()[0]
    
    cursor.execute('SELECT AVG(agent_score) FROM calls')
    avg_score = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM tickets WHERE status = "OPEN"')
    open_tickets = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_calls": total_calls,
        "average_agent_score": round(avg_score, 2),
        "open_tickets": open_tickets
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
