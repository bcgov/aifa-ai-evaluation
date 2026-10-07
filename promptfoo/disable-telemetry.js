// disable-telemetry.js
// Preload script to stub Promptfoo/related telemetry modules so shutdown won't block.
try {
  const Module = require('module');
  const origLoad = Module._load;
  Module._load = function(request, parent, isMain) {
    try {
      if (typeof request === 'string') {
        // Only stub promptfoo's telemetry module(s). Avoid stubbing
        // packages with "opentelemetry" in the name (they are real
        // libraries used by promptfoo and should not be replaced).
        const isTelemetry = /\btelemetry\b/i.test(request) && !/opentelemetry/i.test(request);
        const isPromptfooTelemetry = /promptfoo[-\/]?telemetry/i.test(request);
        if (isTelemetry || isPromptfooTelemetry) {
          return {
            shutdown: async () => {},
            send: () => {},
            start: () => {},
          };
        }
      }
    } catch (e) {
      // ignore
    }
    return origLoad.apply(this, arguments);
  };
  // also set a global shim if some modules reference global telemetry
  global.__PROMPTFOO_TELEMETRY_SHIM__ = {
    shutdown: async () => {},
    send: () => {},
    start: () => {},
  };
  // eslint-disable-next-line no-console
  console.log('[disable-telemetry] telemetry shim installed');
} catch (err) {
  // eslint-disable-next-line no-console
  console.warn('[disable-telemetry] failed to install shim', err && err.message);
}
