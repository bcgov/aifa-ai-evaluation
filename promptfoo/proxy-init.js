// Proxy init script — require this with NODE_OPTIONS to enable SOCKS5 proxying
// Usage: install `socks-proxy-agent` then run:
// NODE_OPTIONS='-r ./proxy-init.js' npx promptfoo ...

try {
  const proxy = process.env.HTTPS_PROXY || process.env.ALL_PROXY || process.env.HTTP_PROXY;
  if (!proxy) {
    // nothing to do
    // eslint-disable-next-line no-console
    console.log('[proxy-init] no proxy env var set (HTTPS_PROXY/ALL_PROXY/HTTP_PROXY)');
    return;
  }

  // Only handle socks protocols here; http(s) proxies are handled by many libs automatically
  if (!/^socks/i.test(proxy)) {
    // eslint-disable-next-line no-console
    console.log('[proxy-init] proxy is not a socks proxy, skipping socks agent init:', proxy);
    return;
  }

  // Lazy require so running without the package gives a clear message
  let SocksProxyAgent;
  try {
    SocksProxyAgent = require('socks-proxy-agent').SocksProxyAgent;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('[proxy-init] please install the dependency: npm install --save-dev socks-proxy-agent');
    return;
  }

  const agent = new SocksProxyAgent(proxy);

  // Attach to Node core http/https global agents so many libraries pick it up
  try {
    const http = require('http');
    const https = require('https');
    http.globalAgent = agent;
    https.globalAgent = agent;
    // eslint-disable-next-line no-console
    console.log('[proxy-init] http(s) globalAgent set to socks proxy:', proxy);
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[proxy-init] failed to set http/https globalAgent', e && e.message);
  }

  // Do NOT set undici global dispatcher here. undici expects a Dispatcher
  // implementation; supplying a SocksProxyAgent can cause protocol errors
  // (UND_ERR_INVALID_ARG) because it's not an undici Dispatcher.
  // Libraries that use undici may need a compatible dispatcher set explicitly
  // or the user can run Node under a shim (e.g., proxychains) if required.
} catch (err) {
  // eslint-disable-next-line no-console
  console.error('[proxy-init] unexpected error while initializing proxy agent:', err && err.stack);
}
