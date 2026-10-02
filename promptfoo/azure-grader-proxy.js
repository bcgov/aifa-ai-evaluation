#!/usr/bin/env node
// Simple local proxy that forwards grading requests to Azure OpenAI via curl.
// It uses the SOCKS5 proxy from env (ALL_PROXY/HTTPS_PROXY/HTTP_PROXY) and
// the API key from OPENAI_API_KEY in evaluation/.env.

const express = require('express');
const bodyParser = require('body-parser');
const { spawn } = require('child_process');

const app = express();
app.use(bodyParser.json({ limit: '1mb' }));

const AZURE_URL = process.env.AZURE_OPENAI_ENDPOINT || 'https://css-ai-dev-openai-east.openai.azure.com';
const DEPLOYMENT = process.env.AZURE_OPENAI_DEPLOYMENT || 'gpt-5.1-chat';
const API_VERSION = process.env.AZURE_OPENAI_API_VERSION || '2025-01-01-preview';
const OPENAI_KEY = process.env.OPENAI_API_KEY || '';
const PROXY = process.env.ALL_PROXY || process.env.HTTPS_PROXY || process.env.HTTP_PROXY || '';

if (!OPENAI_KEY) {
  console.warn('[azure-grader-proxy] WARNING: OPENAI_API_KEY is not set in env; set it in evaluation/.env or export it before running this proxy.');
}

app.post('/grade', async (req, res) => {
  try {
    const targetUrl = `${AZURE_URL.replace(/\/$/, '')}/openai/deployments/${DEPLOYMENT}/chat/completions?api-version=${API_VERSION}`;

    const body = JSON.stringify(req.body || {});

    const curlArgs = ['-s', '-S', '--fail'];
    if (PROXY && /^socks/i.test(PROXY)) {
      // --socks5-hostname expects host:port
      const m = PROXY.replace(/^socks5h?:\/\//i, '');
      curlArgs.push('--socks5-hostname', m);
    }
    curlArgs.push('-H', 'Content-Type: application/json');
    curlArgs.push('-H', `api-key: ${OPENAI_KEY}`);
    curlArgs.push('-d', body);
    curlArgs.push(targetUrl);

    const curl = spawn('curl', curlArgs);
    let stdout = '';
    let stderr = '';
    curl.stdout.on('data', (d) => { stdout += d.toString(); });
    curl.stderr.on('data', (d) => { stderr += d.toString(); });

    curl.on('close', (code) => {
      if (code === 0) {
        res.setHeader('Content-Type', 'application/json');
        try {
          const parsed = JSON.parse(stdout);
          return res.status(200).json(parsed);
        } catch (e) {
          return res.status(200).send(stdout);
        }
      }
      // Curl failed
      res.status(502).json({ error: 'upstream_error', details: stderr || stdout });
    });
  } catch (err) {
    res.status(500).json({ error: err && err.message });
  }
});

const port = process.env.AZURE_GRADER_PROXY_PORT || 8002;
app.listen(port, '127.0.0.1', () => {
  console.log(`[azure-grader-proxy] listening on http://127.0.0.1:${port}/grade`);
  console.log('[azure-grader-proxy] proxy:', PROXY || '(none)');
});
