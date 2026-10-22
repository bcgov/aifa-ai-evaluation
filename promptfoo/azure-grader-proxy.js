#!/usr/bin/env node
// Thin compatibility wrapper around the single shared LLM request script.
// This keeps the legacy /grade endpoint available without duplicating the Azure/Fondry
// request logic in multiple files.

const express = require('express');
const { spawn } = require('child_process');
const path = require('path');

const app = express();
app.use(express.json({ limit: '1mb' }));

const AZURE_URL = (process.env.AUDIT_LLM_ENDPOINT || '').replace(/\/+$/, '').replace(/\/openai(?:\/v1)?$/i, '');
const DEPLOYMENT = process.env.AUDIT_LLM_DEPLOYMENT || process.env.AUDIT_LLM_MODEL || 'gpt-5.2';
const API_VERSION = process.env.AUDIT_LLM_API_VERSION || '2025-01-01-preview';
const API_KEY = process.env.OPENAI_API_KEY || process.env.AUDIT_LLM_API_KEY || '';
const SHARED_CLIENT = path.resolve(__dirname, '..', 'scripts', 'shared_llm_client.py');
const PYTHON = process.env.PYTHON || 'python3';

function extractMessages(reqBody) {
  let messages = reqBody && reqBody.messages;
  for (let i = 0; i < 2 && typeof messages === 'string'; i += 1) {
    try {
      messages = JSON.parse(messages);
    } catch (error) {
      break;
    }
  }
  if (!messages) {
    const prompt = typeof reqBody === 'string' ? reqBody : (reqBody && reqBody.prompt) || 'hello';
    return [{ role: 'user', content: prompt }];
  }
  if (typeof messages === 'string') {
    return [{ role: 'user', content: messages }];
  }
  return Array.isArray(messages) ? messages : [{ role: 'user', content: String(messages) }];
}

app.get('/health', (req, res) => {
  res.json({ ok: true, target: AZURE_URL, deployment: DEPLOYMENT });
});

app.post('/grade', async (req, res) => {
  try {
    const messages = extractMessages(req.body || {});
    const promptMessage = messages.filter((m) => (m.role || 'user') === 'user').slice(-1)[0] || messages[0] || { role: 'user', content: 'hello' };

    const child = spawn(PYTHON, [
      SHARED_CLIENT,
      '--endpoint', AZURE_URL,
      '--api-key', API_KEY,
      '--deployment', DEPLOYMENT,
      '--api-version', API_VERSION,
      '--message', String(promptMessage.content || ''),
    ], { stdio: ['ignore', 'pipe', 'pipe'] });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });

    child.on('close', (code) => {
      if (code !== 0) {
        return res.status(502).json({ error: 'upstream_error', details: stderr || 'shared llm client failed' });
      }
      try {
        const payload = JSON.parse(stdout || '{}');
        res.type('application/json').send(payload);
      } catch (error) {
        res.type('application/json').send({ content: stdout.trim() || '' });
      }
    });
  } catch (error) {
    res.status(502).json({ error: 'upstream_error', details: error.message || String(error) });
  }
});

const port = process.env.AZURE_GRADER_PROXY_PORT || 8002;
app.listen(port, '127.0.0.1', () => {
  console.log(`[azure-grader-proxy] listening on http://127.0.0.1:${port}/grade`);
});
