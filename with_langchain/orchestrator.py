import os
import json
import logging
import asyncio
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field
import re
import ast
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger(__name__)

# ==================== DATA MODELS ====================

class AnalysisResult(BaseModel):
    primary_intent: str = Field(..., description="The main purpose of the call")
    sentiment: str = Field(..., description="Overall customer sentiment (Positive/Negative/Neutral)")
    tone: str = Field(..., description="The emotional tone of the speaker (e.g., Polite, Frustrated)")
    conversation_rating: int = Field(..., ge=1, le=10, description="Overall conversation quality score (1-10)")
    need_callback: bool = Field(..., description="True if the customer requested or needs a callback")
    escalation_required: bool = Field(..., description="True if the issue requires supervisor intervention")
    fraud_risk: bool = Field(..., description="True if suspicious keywords or behavior suggest fraud")
    follow_up_tasks: List[Any] = Field(..., description="List of specific actions to be taken (can be strings or objects)")
    summary: str = Field(..., description="A clear and professional summary of the interaction")

# ==================== ANALYSIS TOOLS ====================

@tool
def transcribe_audio(audio_file_path: str) -> str:
    """
    Transcribe an audio file to text.
    Use this first if an audio file path is provided instead of a transcript.
    """
    logger.info(f"[TOOL] Transcribing: {audio_file_path}")
    # Simulating Faster Whisper transcription
    if "demo" in audio_file_path.lower() or audio_file_path == "sample.wav":
        return "Customer: Hello, I need help with my loan payment. I lost my job and can't pay this month. Agent: I understand. Let me help you set up a payment plan. I'll need you to upload some documents showing your employment status."
    
    # In a real scenario, this would import and call Faster Whisper
    return f"Transcript of {audio_file_path}: Customer needs assistance with banking services."

@tool
def classify_intent(transcript: str) -> Dict[str, Any]:
    """
    Classify the primary intent of a banking call transcript.
    Categories: loan_repayment, application, balance_inquiry, complaint, fraud, etc.
    """
    logger.info("[TOOL] Classifying intent")
    # Rule-based fallback logic (from legacy IntentAgent)
    transcript_lower = transcript.lower()
    if "loan" in transcript_lower:
        return {"intent": "loan_repayment_query", "confidence": 0.9, "reasoning": "Keywords related to loans detected"}
    if "fraud" in transcript_lower or "unauthorized" in transcript_lower:
        return {"intent": "fraud_report", "confidence": 0.9, "reasoning": "Fraud keywords detected"}
    
    return {"intent": "general_inquiry", "confidence": 0.5, "reasoning": "Default classification"}

@tool
def detect_requirements(transcript: str) -> List[Dict[str, Any]]:
    """
    Identify follow-up actions (requirements) from the transcript.
    Examples: document_upload, callback_request, escalation, payment_plan.
    """
    logger.info("[TOOL] Detecting requirements")
    requirements = []
    transcript_lower = transcript.lower()
    
    if "document" in transcript_lower or "upload" in transcript_lower:
        requirements.append({"type": "document_upload", "priority": "MEDIUM", "description": "Needs to submit verification documents"})
    if "call back" in transcript_lower or "callback" in transcript_lower:
        requirements.append({"type": "callback_request", "priority": "MEDIUM", "description": "Customer requested a call back"})
    if "supervisor" in transcript_lower or "manager" in transcript_lower:
        requirements.append({"type": "escalation", "priority": "HIGH", "description": "Requested supervisor attention"})
        
    return requirements

@tool
def analyze_sentiment(transcript: str) -> Dict[str, Any]:
    """
    Analyze customer sentiment and primary emotion from the transcript.
    Sentiments: POSITIVE, NEGATIVE, NEUTRAL.
    """
    logger.info("[TOOL] Analyzing sentiment")
    transcript_lower = transcript.lower()
    
    if any(w in transcript_lower for w in ["angry", "upset", "frustrated", "bad"]):
        return {"sentiment": "NEGATIVE", "score": 0.8, "emotion": "frustration"}
    if any(w in transcript_lower for w in ["thank", "great", "happy"]):
        return {"sentiment": "POSITIVE", "score": 0.8, "emotion": "contentment"}
        
    return {"sentiment": "NEUTRAL", "score": 0.5, "emotion": "neutral"}

@tool
def score_agent_performance(transcript: str, sentiment: str = "NEUTRAL") -> Dict[str, Any]:
    """
    Score the customer service agent's performance on a 0-100 scale.
    Evaluates: politeness, helpfulness, clarity, empathy.
    """
    logger.info("[TOOL] Scoring agent")
    # Heuristic scoring
    score = 75.0
    if sentiment == "NEGATIVE":
        score -= 5.0
    if "apologize" in transcript.lower() or "sorry" in transcript.lower():
        score += 10.0
    
    return {
        "overall_score": min(score, 100.0),
        "politeness": 80.0,
        "helpfulness": 75.0,
        "clarity": 70.0,
        "empathy": 80.0,
        "reasoning": "Rule-based scoring based on keywords and sentiment"
    }

@tool
def save_to_database(
    transcript: str, 
    intent: str, 
    requirements: List[Dict[str, Any]], 
    sentiment: str, 
    agent_score: float,
    session_id: str
) -> str:
    """
    Save all analysis results to the banking database.
    This should be the FINAL step in the analysis pipeline.
    """
    logger.info(f"[TOOL] Saving results to DB (Session: {session_id})")
    # Simulating database save
    import sqlite3
    db_path = "call_analysis.db"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS call_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                transcript TEXT,
                intent TEXT,
                sentiment TEXT,
                agent_score REAL,
                timestamp DATETIME
            )
        ''')
        cursor.execute('''
            INSERT INTO call_analysis (session_id, transcript, intent, sentiment, agent_score, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, transcript, intent, sentiment, agent_score, datetime.now().isoformat()))
        conn.commit()
        call_id = cursor.lastrowid
        conn.close()
        return f"SUCCESS: Call analysis saved with ID {call_id}"
    except Exception as e:
        return f"ERROR: Failed to save to database: {str(e)}"

# ==================== ORCHESTRATOR ====================

class CallAnalysisOrchestrator:
    def __init__(self, model_name: str = "qwen3"):
        logger.info(f"Initializing CallAnalysisOrchestrator with Ollama model: {model_name}")
        
        # Initialize Ollama model
        try:
            self.model = ChatOllama(
                model=model_name,
                temperature=0,
            )
            logger.info(f"Ollama {model_name} initialized successfully")
        except Exception as e:
            logger.warning(f"Could not initialize Ollama: {str(e)}. Fallback methods will be used via tools.")
            self.model = None


        self.tools = [
            transcribe_audio,
            classify_intent,
            detect_requirements,
            analyze_sentiment,
            score_agent_performance,
            save_to_database
        ]

        self.system_prompt = """
        You are an expert Banking Call Analysis Orchestrator. 
        Your goal is to perform a complete end-to-end analysis of a customer service interaction.
        
        REQUIRED WORKFLOW:
        1. TRANSCRIPTION: If an audio file path is provided, use 'transcribe_audio' to get the text.
        2. INTENT: Use 'classify_intent' to identify why the customer is calling.
        3. REQUIREMENTS: Use 'detect_requirements' to find follow-up actions.
        4. SENTIMENT: Use 'analyze_sentiment' to evaluate the customer's mood.
        5. AGENT SCORING: Use 'score_agent_performance' to rate the representative.
        6. PERSISTENCE: Use 'save_to_database' to store all results. This is your FINAL task.
        
        The 'session_id' provided in the task must be passed to the 'save_to_database' tool.
        If a transcript is provided directly, SKIP the transcription step.

        OUTPUT FORMAT:
        Your final response MUST be a SINGLE JSON object representing the analysis results. 
        Do NOT include any introduction, conclusion, or formatting outside the JSON block.
        The JSON must strictly follow this structure:
        {
            "primary_intent": "string",
            "sentiment": "Positive" | "Negative" | "Neutral",
            "tone": "string",
            "conversation_rating": 1-10,
            "need_callback": true | false,
            "escalation_required": true | false,
            "fraud_risk": true | false,
            "follow_up_tasks": ["string (simple task descriptions)"],
            "summary": "string"
        }
        """

        # self.checkpointer = MemorySaver()
        if self.model:
            self.agent = create_react_agent(
                self.model, 
                self.tools, 
                prompt=self.system_prompt,
                # checkpointer=self.checkpointer
            )
        else:
            self.agent = None
            logger.warning("React Agent not initialized: model is missing.")

    async def analyze_call(
        self,
        audio_file_path: Optional[str] = None,
        transcript: Optional[str] = None,
        user_id: str = "default_user",
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        session_id = session_id or str(uuid.uuid4())
        logger.info(f"Starting React analysis for session: {session_id}")

        input_msg = f"Analyze this interaction. Session ID: {session_id}. "
        if transcript:
            input_msg += f"Transcript: {transcript}"
        else:
            input_msg += f"Audio File: {audio_file_path}"

        config = {"configurable": {"thread_id": session_id}}
        
        if not self.agent:
            return self._run_fallback_analysis(audio_file_path, transcript, session_id)

        try:
            result = await self.agent.ainvoke(
                {"messages": [("human", input_msg)]},
                config=config
            )
            
            final_msg_content = result["messages"][-1].content
            
            json_data = {}
            try:
                match = re.search(r'(\{.*\})', final_msg_content, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    if "'" in json_str and '"' not in json_str:
                        json_str = json_str.replace("'", '"')
                    json_data = json.loads(json_str)
            except Exception:
                try:
                    match = re.search(r'(\{.*\})', final_msg_content, re.DOTALL)
                    if match:
                        json_data = ast.literal_eval(match.group(1))
                except:
                    pass

            try:
                validated_result = AnalysisResult(**json_data)
                return {
                    "status": "success",
                    "session_id": session_id,
                    "analysis": validated_result.model_dump()
                }
            except Exception as e:
                logger.error(f"Pydantic validation failed: {str(e)}")
                return {
                    "status": "success",
                    "session_id": session_id,
                    "analysis": json_data, 
                    "validation_error": str(e)
                }
        except Exception as e:
            logger.error(f" Agent failed: {str(e)}")
            return self._run_fallback_analysis(audio_file_path, transcript, session_id)

    def _run_fallback_analysis(self, audio_path, transcript, session_id):
        logger.warning("Running synchronous fallback analysis pipeline")
        text = transcript or transcribe_audio.invoke({"audio_file_path": audio_path})
        intent = classify_intent.invoke({"transcript": text})
        reqs = detect_requirements.invoke({"transcript": text})
        sent = analyze_sentiment.invoke({"transcript": text})
        score_details = score_agent_performance.invoke({"transcript": text, "sentiment": sent['sentiment']})
        
        json_data = {
            "sentiment": sent['sentiment'].capitalize(),
            "tone": "Professional",
            "conversation_rating": int(score_details['overall_score'] / 10),
            "need_callback": any(r['type'] == 'callback_request' for r in reqs),
            "escalation_required": any(r['type'] == 'escalation' for r in reqs),
            "fraud_risk": intent['intent'] == 'fraud_report',
            "primary_intent": intent['intent'],
            "follow_up_tasks": [r['description'] for r in reqs],
            "summary": "Rule-based analysis performed due to LLM unavailability."
        }

        db_res = save_to_database.invoke({
            "transcript": text,
            "intent": intent['intent'],
            "requirements": reqs,
            "sentiment": sent['sentiment'],
            "agent_score": score_details['overall_score'],
            "session_id": session_id
        })
        
        return {
            "status": "success",
            "session_id": session_id,
            "analysis": json_data
        }

    
