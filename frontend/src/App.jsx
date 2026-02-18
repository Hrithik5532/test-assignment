
import React, { useState } from 'react';
import axios from 'axios';
import { Upload, FileText, Send, Loader2, CheckCircle2, AlertCircle, Phone, BrainCircuit, Activity } from 'lucide-react';

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

    const handleFileChange = (e) => {
        setSelectedFile(e.target.files[0]);
        setError(null);
    };

    const analyze = async () => {
        setLoading(true);
        setError(null);
        setResults({ prebuilt: null, langchain: null });
        setInputText(''); // Clear text on audio upload start if needed

        try {
            let callId;

            if (activeTab === 'text') {
                if (!inputText.trim()) throw new Error('Please enter some text to analyze');

                const textRes = await axios.post('/api/text', { text: inputText });
                callId = textRes.data.call_id;
            } else {
                if (!selectedFile) throw new Error('Please select an audio file');

                const formData = new FormData();
                formData.append('file', selectedFile);

                const uploadRes = await axios.post('/api/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                callId = uploadRes.data.call_id;
            }

            // Start Polling for Transcription
            let status = 'PENDING';
            let data;

            while (status === 'PENDING') {
                await new Promise(r => setTimeout(r, 3000));
                const res = await axios.get(`/api/status/${callId}`);
                data = res.data;
                status = data.status;
                if (status === 'FAILED') throw new Error('Transcription failed');
            }

            // Once Transcribed, Trigger Analysis
            await axios.post(`/api/process/${callId}`);

            // Poll for Completion
            while (status === 'TRANSCRIBED' || status === 'ANALYZING') {
                await new Promise(r => setTimeout(r, 3000));
                const res = await axios.get(`/api/status/${callId}`);
                data = res.data;
                status = data.status;

                // Update results in real-time if we have partials
                setResults({
                    prebuilt: data.prebuilt_result,
                    langchain: data.langchain_result
                });

                if (status === 'FAILED') throw new Error('Analysis failed');
                if (status === 'COMPLETED') break;
            }

        } catch (err) {
            console.error('Analysis error:', err);
            setError(err.message || 'An unexpected error occurred');
        } finally {
            setLoading(false);
        }
    };

    const ResultCard = ({ title, data, type }) => {
        if (!data) return null;

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

        // Adapt langchain result format for unified display if needed
        // The current api_langchain returns results in a slightly different structure than prebuilt
        const analysis = type === 'langchain' ? data.analysis : data;

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
                            {(analysis.primary_intent || analysis.intent || 'Unknown').replace(/_/g, ' ')}
                        </div>
                    </div>
                    <div className="metric-item">
                        <div className="section-title">AGENT SCORE</div>
                        <div className="metric-value" style={{ color: '#34d399' }}>
                            {Math.round(analysis.conversation_rating ? analysis.conversation_rating * 10 : (analysis.agent_score || 0))}/100
                        </div>
                    </div>
                    <div className="metric-item">
                        <div className="section-title">SENTIMENT</div>
                        <div className="metric-value">
                            {analysis.sentiment}
                        </div>
                    </div>
                    <div className="metric-item">
                        <div className="section-title">EMOTION / TONE</div>
                        <div className="metric-value">
                            {analysis.emotion || analysis.tone || 'Neutral'}
                        </div>
                    </div>
                </div>

                <div>
                    <div className="section-title">SUMMARY</div>
                    <p className="summary">{analysis.summary || analysis.transcript?.substring(0, 150) + '...'}</p>
                </div>

                {analysis.follow_up_tasks && (
                    <div>
                        <div className="section-title">FOLLOW-UP TASKS</div>
                        <ul className="tasks-list">
                            {analysis.follow_up_tasks.map((task, idx) => (
                                <li key={idx} className="task-item">
                                    <CheckCircle2 size={14} style={{ color: '#3b82f6' }} />
                                    {typeof task === 'string' ? task : task.description}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {analysis.requirements && analysis.requirements.length > 0 && (
                    <div>
                        <div className="section-title">REQUIREMENTS</div>
                        <ul className="tasks-list">
                            {analysis.requirements.map((req, idx) => (
                                <li key={idx} className="task-item">
                                    <CheckCircle2 size={14} style={{ color: '#3b82f6' }} />
                                    {req.description} ({req.priority})
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        );
    };

    return (
        <div className="dashboard">
            <header className="header">
                <h1>Call Analysis POC</h1>
                <p>Compare AI Insights: LangChain vs. Pre-built Models</p>
            </header>

            <div className="input-section">
                <div className="tabs">
                    <button
                        className={`tab ${activeTab === 'text' ? 'active' : ''}`}
                        onClick={() => setActiveTab('text')}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <FileText size={18} />
                            Text Input
                        </div>
                    </button>
                    <button
                        className={`tab ${activeTab === 'audio' ? 'active' : ''}`}
                        onClick={() => setActiveTab('audio')}
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
                        />
                    ) : (
                        <div className="file-input" onClick={() => document.getElementById('audio-upload').click()}>
                            <input
                                id="audio-upload"
                                type="file"
                                accept="audio/*"
                                hidden
                                onChange={handleFileChange}
                            />
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
                                <Phone size={48} color="#3b82f6" />
                                <div>
                                    {selectedFile ? (
                                        <span style={{ fontWeight: 600, color: 'white' }}>{selectedFile.name}</span>
                                    ) : (
                                        <>
                                            <p style={{ fontWeight: 600, color: 'white', margin: 0 }}>Click to upload audio</p>
                                            <p style={{ fontSize: '0.8rem', margin: '0.5rem 0' }}>Supports WAV, MP3, M4A</p>
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {error && <p style={{ color: '#ef4444', fontSize: '0.9rem', margin: 0 }}>{error}</p>}

                    <button
                        className="analyze-button"
                        onClick={analyze}
                        disabled={loading}
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
