#!/usr/bin/env node
// Local judge endpoint for promptfoo: forwards llm-rubric grading calls to Azure OpenAI.
// Direct connection (no proxy). Config: AUDIT_LLM_ENDPOINT / _DEPLOYMENT / _API_VERSION and OPENAI_API_KEY.

const express = require('express');

const app = express();
app.use(express.json({ limit: '1mb' }));

const AZURE_URL = (process.env.AUDIT_LLM_ENDPOINT || '').replace(/\/+$/, '').replace(/\/openai(?:\/v1)?$/i, '');
const DEPLOYMENT = process.env.AUDIT_LLM_DEPLOYMENT || 'gpt-5.1';
const API_VERSION = process.env.AUDIT_LLM_API_VERSION || '2024-10-21';
const API_KEY = process.env.OPENAI_API_KEY || process.env.AUDIT_LLM_API_KEY || '';
const TARGET = `${AZURE_URL}/openai/deployments/${DEPLOYMENT}/chat/completions?api-version=${API_VERSION}`;

if (!AZURE_URL || !API_KEY) {
  console.warn('[azure-grader-proxy] WARNING: AUDIT_LLM_ENDPOINT and OPENAI_API_KEY must be set.');
}

app.get('/health', (req, res) => {
  res.json({ ok: true, target: AZURE_URL, deployment: DEPLOYMENT });
});

app.post('/grade', async (req, res) => {
  // promptfoo may send messages as an array, a JSON string, or a plain-text rubric prompt.
  const incoming = req.body || {};
  let messages = incoming.messages;
  for (let i = 0; i < 2 && typeof messages === 'string'; i++) {
    try { messages = JSON.parse(messages); } catch (e) { break; }
  }
  if (typeof messages === 'string') messages = [{ role: 'user', content: messages }];

  try {
    const upstream = await fetch(TARGET, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'api-key': API_KEY },
      body: JSON.stringify({ ...incoming, messages }),
    });
    const text = await upstream.text();
    if (!upstream.ok) return res.status(502).json({ error: 'upstream_error', details: `HTTP ${upstream.status}: ${text}` });
    res.type('application/json').send(text);
  } catch (err) {
    res.status(502).json({ error: 'upstream_error', details: err.message });
  }
});

const port = process.env.AZURE_GRADER_PROXY_PORT || 8002;
app.listen(port, '127.0.0.1', () => {
  console.log(`[azure-grader-proxy] listening on http://127.0.0.1:${port}/grade`);
});
