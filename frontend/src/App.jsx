import React, { useState } from 'react';
import axios from 'axios';
import { Upload, FileText, Send, Loader2, CheckCircle2, AlertCircle, Phone, BrainCircuit, Activity, Zap } from 'lucide-react';

// Logger utility
const logger = {
    info: (msg) => console.log(`%c[INFO] ${msg}`, 'color: #60a5fa; font-weight: bold;'),
    error: (msg) => console.error(`%c[ERROR] ${msg}`, 'color: #ef4444; font-weight: bold;'),
    debug: (msg) => console.debug(`%c[DEBUG] ${msg}`, 'color: #a78bfa; font-weight: bold;'),
    success: (msg) => console.log(`%c[SUCCESS] ${msg}`, 'color: #10b981; font-weight: bold;'),
    warn: (msg) => console.warn(`%c[WARN] ${msg}`, 'color: #f59e0b; font-weight: bold;')
};

// === DATA MAPPING FUNCTIONS ===

/**
 * UPDATED: Map BOTH prebuilt response formats to standard format
 * Detects format automatically and handles accordingly
 */
const mapPrebuiltResult = (data) => {
    try {
        if (!data) return null;

        logger.debug("Mapping prebuilt result:", JSON.stringify(data).substring(0, 200));

        // Detect format type
        const isComplexFormat = typeof data.primary_intent === 'object' && data.primary_intent?.intent;
        const hasSentimentObject = typeof data.sentiment === 'object' && data.sentiment?.sentiment;

        logger.info(`Detected prebuilt format: ${isComplexFormat ? 'COMPLEX' : 'SIMPLE'}`);

        return {
            // Intent
            intent: isComplexFormat
                ? (data.primary_intent?.intent || "Unknown")
                : (data.primary_intent || "Unknown"),

            intent_confidence: isComplexFormat
                ? (data.primary_intent?.confidence || 0)
                : 0,

            // Sentiment
            sentiment: hasSentimentObject
                ? (data.sentiment?.sentiment || "Neutral")
                : (data.sentiment || "Neutral"),

            sentiment_score: hasSentimentObject
                ? (data.sentiment?.sentiment_score || 0)
                : 0,

            // Emotion
            emotion: hasSentimentObject
                ? (data.sentiment?.emotion || "Neutral")
                : "Neutral",

            emotion_score: hasSentimentObject
                ? (data.sentiment?.emotion_score || 0)
                : 0,

            // Agent score (prefer raw_agent_score for simple format)
            agent_score: data.raw_agent_score !== undefined
                ? data.raw_agent_score
                : (data.conversation_rating || 0),

            conversation_rating: data.conversation_rating || 0,
            raw_agent_score: data.raw_agent_score || 0,

            // Other fields
            summary: data.summary || "No summary available",
            requirements: data.requirements || [],
            tone: data.tone || "Neutral",
            follow_up_tasks: data.follow_up_tasks || [],

            // Agent metrics
            clarity_score: data.clarity_score || 0,
            empathy_score: data.empathy_score || 0,
            politeness_score: data.politeness_score || 0,
            helpfulness_score: data.helpfulness_score || 0,
        };
    } catch (err) {
        logger.error(`Error mapping prebuilt: ${err.message}`);
        return { error: err.message };
    }
};

/**
 * Map LangChain response to standard format
 * Supports both nested "analysis" and flat structures
 */
const mapLangchainResult = (data) => {
    try {
        if (!data) return null;

        logger.debug("Mapping langchain result:", JSON.stringify(data).substring(0, 200));

        const analysis = data.analysis || data;

        return {
            primary_intent: analysis.primary_intent || "Unknown",
            conversation_rating: analysis.conversation_rating || 0,
            summary: analysis.summary || "No summary available",
            sentiment: analysis.sentiment || "Neutral",
            tone: analysis.tone || "Neutral",
            fraud_risk: analysis.fraud_risk || false,
            need_callback: analysis.need_callback || false,
            follow_up_tasks: analysis.follow_up_tasks || [],
            action_items: analysis.follow_up_tasks || [],
            escalation_required: analysis.escalation_required || false,
        };
    } catch (err) {
        logger.error(`Error mapping langchain: ${err.message}`);
        return { error: err.message };
    }
};

const App = () => {
    const [activeTab, setActiveTab] = useState('text');
    const [inputText, setInputText] = useState('');
    const [selectedFile, setSelectedFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [results, setResults] = useState({
        prebuilt: null,
        langchain: null
    });
    const [statusMessage, setStatusMessage] = useState('');

    const handleFileChange = (e) => {
        setSelectedFile(e.target.files[0]);
        setError(null);
    };

    const analyze = async () => {
        setLoading(true);
        setError(null);
        setResults({ prebuilt: null, langchain: null });
        setStatusMessage('Initializing...');

        try {
            let callId;

            if (activeTab === 'text') {
                if (!inputText.trim()) {
                    throw new Error('Please enter some text to analyze');
                }

                setStatusMessage('Submitting text for analysis...');
                const textRes = await axios.post('/api/text', { text: inputText });
                callId = textRes.data.call_id;
                setStatusMessage('Text submitted. Starting analysis...');
                logger.success(`Text submitted with call_id: ${callId}`);
            } else {
                if (!selectedFile) {
                    throw new Error('Please select an audio file');
                }

                setStatusMessage('Uploading audio file...');
                const formData = new FormData();
                formData.append('file', selectedFile);

                const uploadRes = await axios.post('/api/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                callId = uploadRes.data.call_id;
                setStatusMessage('Audio uploaded. Starting transcription...');
                logger.success(`Audio uploaded with call_id: ${callId}`);
            }

            // === TRANSCRIPTION POLLING ===
            let status = 'PENDING';
            let pollCount = 0;
            const maxTranscriptionAttempts = 240;

            logger.info('Starting transcription polling...');

            while (status === 'PENDING' && pollCount < maxTranscriptionAttempts) {
                await new Promise(r => setTimeout(r, 3000));
                pollCount++;

                setStatusMessage(`Transcribing... (${pollCount}s / ${maxTranscriptionAttempts * 3}s)`);

                try {
                    const res = await axios.get(`/api/status/${callId}`);
                    status = res.data.status;

                    if (status === 'FAILED') {
                        throw new Error('Transcription failed on server');
                    }
                } catch (pollErr) {
                    if (pollErr.response?.status === 404) {
                        throw new Error('Call ID not found');
                    }
                }
            }

            if (status === 'PENDING') {
                throw new Error(`Transcription timeout after ${pollCount * 3}s`);
            }

            logger.success('Transcription complete!');
            setStatusMessage('Transcription complete. Starting analysis...');

            // === ANALYSIS TRIGGER ===
            try {
                await axios.post(`/api/process/${callId}`);
                logger.success('Analysis triggered successfully');
            } catch (triggerErr) {
                throw new Error('Failed to trigger analysis');
            }

            // === ANALYSIS POLLING ===
            status = 'TRANSCRIBED';
            pollCount = 0;
            const maxAnalysisAttempts = 600;

            logger.info('Starting analysis polling...');

            while ((status === 'TRANSCRIBED' || status === 'ANALYZING') && pollCount < maxAnalysisAttempts) {
                await new Promise(r => setTimeout(r, 3000));
                pollCount++;

                setStatusMessage(`Analyzing... (${pollCount}s / ${maxAnalysisAttempts * 3}s)`);

                try {
                    const res = await axios.get(`/api/status/${callId}`);
                    status = res.data.status;

                    // Update results with mapped data
                    if (res.data.prebuilt_result || res.data.langchain_result) {
                        logger.debug('Results available, mapping...');
                        setResults({
                            prebuilt: mapPrebuiltResult(res.data.prebuilt_result),
                            langchain: mapLangchainResult(res.data.langchain_result)
                        });
                    }

                    if (status === 'FAILED') {
                        throw new Error('Analysis failed on server');
                    }

                    // === FINAL FETCH ===
                    if (status === 'COMPLETED') {
                        logger.success('Analysis marked as COMPLETED!');
                        setStatusMessage('Analysis complete. Retrieving final results...');

                        await new Promise(r => setTimeout(r, 2000));

                        const finalRes = await axios.get(`/api/status/${callId}`);

                        logger.success('Final results retrieved!');

                        const mappedPrebuilt = mapPrebuiltResult(finalRes.data.prebuilt_result);
                        const mappedLangchain = mapLangchainResult(finalRes.data.langchain_result);

                        logger.debug('Mapped prebuilt:', mappedPrebuilt);
                        logger.debug('Mapped langchain:', mappedLangchain);

                        setResults({
                            prebuilt: mappedPrebuilt,
                            langchain: mappedLangchain
                        });

                        setStatusMessage('');
                        logger.success('✅ Analysis complete!');
                        break;
                    }
                } catch (pollErr) {
                    if (pollErr.response?.status === 404) {
                        throw new Error('Call ID not found');
                    }
                }
            }

            if (status !== 'COMPLETED') {
                logger.warn('Attempting fallback fetch...');
                try {
                    const fallbackRes = await axios.get(`/api/status/${callId}`);
                    if (fallbackRes.data.prebuilt_result || fallbackRes.data.langchain_result) {
                        setResults({
                            prebuilt: mapPrebuiltResult(fallbackRes.data.prebuilt_result),
                            langchain: mapLangchainResult(fallbackRes.data.langchain_result)
                        });
                        setStatusMessage('');
                        logger.success('✅ Results retrieved via fallback!');
                    } else {
                        throw new Error('No results available');
                    }
                } catch (fallbackErr) {
                    throw new Error(`Analysis timeout - ${fallbackErr.message}`);
                }
            }

        } catch (err) {
            logger.error(`Analysis error: ${err.message}`);
            setError(err.message || 'An unexpected error occurred');
            setStatusMessage('');
        } finally {
            setLoading(false);
        }
    };

    const formatIntentName = (intent) => {
        return String(intent)
            .replace(/_/g, ' ')
            .replace(/\b\w/g, char => char.toUpperCase());
    };

    const ResultCard = ({ title, data, type }) => {
        if (!data) return null;

        try {
            if (data.error) {
                return (
                    <div className="result-card">
                        <div className="card-header">
                            <h3>{title}</h3>
                            <span className={`badge badge-${type}`}>{type.toUpperCase()}</span>
                        </div>
                        <div style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <AlertCircle size={20} />
                            <p>{data.error}</p>
                        </div>
                    </div>
                );
            }

            // Extract values
            const intent = type === 'prebuilt'
                ? (data.intent || "Unknown")
                : (data.primary_intent || "Unknown");

            const score = type === 'prebuilt'
                ? data.agent_score
                : (data.conversation_rating || 0);

            const sentiment = data.sentiment || "Neutral";
            const emotion = type === 'prebuilt'
                ? (data.emotion || data.tone || "Neutral")
                : (data.tone || "Neutral");

            const summary = data.summary || "No summary available";

            // Determine score display format
            const scoreDisplay = type === 'prebuilt'
                ? (score > 0 && score <= 1 ? `${Math.round(score * 100)}/100` : `${Math.round(score)}/10`)
                : `${Math.round(score * 100)}%`;

            return (
                <div className="result-card">
                    <div className="card-header">
                        <h3>{title}</h3>
                        <span className={`badge badge-${type}`}>{type.toUpperCase()}</span>
                    </div>

                    <div className="metric-grid">
                        <div className="metric-item">
                            <div className="section-title">PRIMARY INTENT</div>
                            <div className="metric-value" style={{ color: '#60a5fa' }}>
                                {formatIntentName(intent)}
                            </div>
                        </div>

                        <div className="metric-item">
                            <div className="section-title">
                                {type === 'prebuilt' && data.intent_confidence > 0 ? 'CONFIDENCE' : 'SCORE'}
                            </div>
                            <div className="metric-value" style={{ color: '#34d399' }}>
                                {type === 'prebuilt' && data.intent_confidence > 0
                                    ? `${Math.round(data.intent_confidence * 100)}%`
                                    : scoreDisplay
                                }
                            </div>
                        </div>

                        <div className="metric-item">
                            <div className="section-title">SENTIMENT</div>
                            <div className="metric-value" style={{
                                color: sentiment === 'Positive' ? '#10b981' : sentiment === 'Negative' ? '#ef4444' : '#f59e0b'
                            }}>
                                {String(sentiment).toUpperCase()}
                            </div>
                        </div>

                        <div className="metric-item">
                            <div className="section-title">TONE / EMOTION</div>
                            <div className="metric-value">
                                {typeof emotion === 'string' && emotion.length > 90
                                    ? `${emotion.substring(0, 90)}...`
                                    : emotion?.toUpperCase() || "N/A"
                                }
                            </div>
                        </div>
                    </div>

                    {/* Extended Metrics for Prebuilt */}
                    {type === 'prebuilt' && (
                        <>
                            {data.sentiment_score > 0 && (
                                <div>
                                    <div className="section-title">SENTIMENT CONFIDENCE</div>
                                    <div style={{ fontSize: '0.9rem', color: '#60a5fa' }}>
                                        {Math.round(data.sentiment_score * 100)}%
                                    </div>
                                </div>
                            )}

                            {data.emotion_score > 0 && (
                                <div>
                                    <div className="section-title">EMOTION CONFIDENCE</div>
                                    <div style={{ fontSize: '0.9rem', color: '#a78bfa' }}>
                                        {Math.round(data.emotion_score * 100)}%
                                    </div>
                                </div>
                            )}

                            {data.conversation_rating > 0 && (
                                <div>
                                    <div className="section-title">CONVERSATION RATING</div>
                                    <div style={{ fontSize: '0.9rem', color: '#fbbf24' }}>
                                        {(data.conversation_rating * 100).toFixed(1)}%
                                    </div>
                                </div>
                            )}
                        </>
                    )}

                    {/* Summary */}
                    {summary && summary !== "No summary available" && (
                        <div>
                            <div className="section-title">SUMMARY</div>
                            <p className="summary">{summary}</p>
                        </div>
                    )}

                    {/* Tone - Prebuilt specific */}
                    {type === 'prebuilt' && data.tone && typeof data.tone === 'string' && (
                        <div>
                            <div className="section-title">CALL TONE</div>
                            <p className="summary" style={{ fontSize: '0.9rem', fontStyle: 'italic' }}>
                                {data.tone}
                            </p>
                        </div>
                    )}

                    {/* Requirements - Prebuilt specific */}
                    {type === 'prebuilt' && data.requirements && data.requirements.length > 0 && (
                        <div>
                            <div className="section-title">REQUIREMENTS</div>
                            <ul className="tasks-list">
                                {data.requirements.map((req, idx) => (
                                    <li key={idx} className="task-item">
                                        <CheckCircle2 size={14} style={{ color: '#3b82f6' }} />
                                        <span>
                                            <strong>{formatIntentName(req.type)}</strong>
                                            {req.description && ` - ${req.description}`}
                                            {req.priority && ` [${req.priority}]`}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Follow-up Tasks - Both types */}
                    {(data.follow_up_tasks && data.follow_up_tasks.length > 0) && (
                        <div>
                            <div className="section-title">
                                {type === 'prebuilt' ? 'FOLLOW-UP TASKS' : 'ACTION ITEMS'}
                            </div>
                            <ul className="tasks-list">
                                {data.follow_up_tasks.map((task, idx) => (
                                    <li key={idx} className="task-item">
                                        <Zap size={14} style={{ color: '#fbbf24' }} />
                                        <span>{typeof task === 'string' ? task : JSON.stringify(task)}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Agent Metrics - Prebuilt specific */}
                    {type === 'prebuilt' && (data.clarity_score > 0 || data.empathy_score > 0 || data.politeness_score > 0 || data.helpfulness_score > 0) && (
                        <div>
                            <div className="section-title">AGENT METRICS</div>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(2, 1fr)',
                                gap: '0.75rem',
                                fontSize: '0.9rem'
                            }}>
                                {data.clarity_score > 0 && <div>✓ Clarity: {Math.round(data.clarity_score * 10)}/10</div>}
                                {data.empathy_score > 0 && <div>✓ Empathy: {Math.round(data.empathy_score * 10)}/10</div>}
                                {data.politeness_score > 0 && <div>✓ Politeness: {Math.round(data.politeness_score * 10)}/10</div>}
                                {data.helpfulness_score > 0 && <div>✓ Helpfulness: {Math.round(data.helpfulness_score * 10)}/10</div>}
                            </div>
                        </div>
                    )}

                    {/* Flags - LangChain specific */}
                    {type === 'langchain' && (data.fraud_risk || data.need_callback || data.escalation_required) && (
                        <div>
                            <div className="section-title">ALERTS & FLAGS</div>
                            <div style={{ fontSize: '0.9rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                {data.fraud_risk && (
                                    <div style={{ color: '#ef4444', fontWeight: 600 }}>🚨 FRAUD RISK DETECTED</div>
                                )}
                                {data.need_callback && (
                                    <div style={{ color: '#f59e0b', fontWeight: 600 }}>📞 CALLBACK REQUIRED</div>
                                )}
                                {data.escalation_required && (
                                    <div style={{ color: '#ef4444', fontWeight: 600 }}>⚠️ ESCALATION REQUIRED</div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            );
        } catch (err) {
            logger.error(`ResultCard render error: ${err.message}`);
            return (
                <div className="result-card">
                    <div className="card-header">
                        <h3>{title}</h3>
                        <span className={`badge badge-${type}`}>{type.toUpperCase()}</span>
                    </div>
                    <div style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <AlertCircle size={20} />
                        <p>Error rendering results: {err.message}</p>
                    </div>
                </div>
            );
        }
    };

    return (
        <div className="dashboard">
            <header className="header">
                <h1>Call Analysis POC</h1>
                <p>Compare AI Insights: Pre-built vs LangChain Models</p>
            </header>

            <div className="input-section">
                <div className="tabs">
                    <button
                        className={`tab ${activeTab === 'text' ? 'active' : ''}`}
                        onClick={() => setActiveTab('text')}
                        disabled={loading}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <FileText size={18} />
                            Text Input
                        </div>
                    </button>
                    <button
                        className={`tab ${activeTab === 'audio' ? 'active' : ''}`}
                        onClick={() => setActiveTab('audio')}
                        disabled={loading}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Upload size={18} />
                            Audio File
                        </div>
                    </button>
                </div>

                <div className="input-area">
                    {activeTab === 'text' ? (
                        <textarea
                            placeholder="Paste the call transcript here..."
                            value={inputText}
                            onChange={(e) => setInputText(e.target.value)}
                            disabled={loading}
                            rows={6}
                        />
                    ) : (
                        <div
                            className="file-input"
                            onClick={() => !loading && document.getElementById('audio-upload').click()}
                            style={{ opacity: loading ? 0.6 : 1, cursor: loading ? 'not-allowed' : 'pointer' }}
                        >
                            <input
                                id="audio-upload"
                                type="file"
                                accept="audio/*"
                                hidden
                                onChange={handleFileChange}
                                disabled={loading}
                            />
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
                                <Phone size={48} color="#3b82f6" />
                                <div>
                                    {selectedFile ? (
                                        <span style={{ fontWeight: 600, color: 'white' }}>{selectedFile.name}</span>
                                    ) : (
                                        <>
                                            <p style={{ fontWeight: 600, color: 'white', margin: 0 }}>
                                                Click to upload audio
                                            </p>
                                            <p style={{ fontSize: '0.8rem', margin: '0.5rem 0' }}>
                                                Supports WAV, MP3, M4A
                                            </p>
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {error && (
                        <div style={{
                            color: '#ef4444',
                            fontSize: '0.9rem',
                            margin: '1rem 0 0 0',
                            padding: '0.75rem',
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            borderRadius: '0.5rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem'
                        }}>
                            <AlertCircle size={18} />
                            {error}
                        </div>
                    )}

                    {statusMessage && (
                        <div style={{
                            color: '#3b82f6',
                            fontSize: '0.9rem',
                            margin: '1rem 0 0 0',
                            padding: '0.75rem',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            borderRadius: '0.5rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem'
                        }}>
                            <Loader2 size={18} className="animate-spin" />
                            {statusMessage}
                        </div>
                    )}

                    <button
                        className="analyze-button"
                        onClick={analyze}
                        disabled={loading}
                        style={{
                            opacity: loading ? 0.6 : 1,
                            cursor: loading ? 'not-allowed' : 'pointer'
                        }}
                    >
                        {loading ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Loader2 size={18} className="animate-spin" />
                                Analyzing...
                            </div>
                        ) : (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Send size={18} />
                                Run Simultaneous Analysis
                            </div>
                        )}
                    </button>
                </div>
            </div>

            <div className="comparison-grid">
                <ResultCard
                    title="Classical Pre-built Models"
                    data={results.prebuilt}
                    type="prebuilt"
                />
                <ResultCard
                    title="LangChain Agent (LLM)"
                    data={results.langchain}
                    type="langchain"
                />
            </div>

            {!results.prebuilt && !results.langchain && !loading && (
                <div style={{ textAlign: 'center', marginTop: '4rem', color: '#475569' }}>
                    <Activity size={64} style={{ opacity: 0.2, marginBottom: '1rem' }} />
                    <p>Upload a file or paste text to see the comparison results</p>
                </div>
            )}
        </div>
    );
};

export default App; 