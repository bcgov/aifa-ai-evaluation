// disable-telemetry-loader.mjs
// Node ESM loader to stub telemetry modules imported via `import`.
export async function resolve(specifier, context, defaultResolve) {
  // Intercept modules whose specifier contains 'telemetry' but not '@opentelemetry'
  if (typeof specifier === 'string' && /telemetry/i.test(specifier) && !/opentelemetry/i.test(specifier)) {
    return { url: `file://${process.cwd()}/promptfoo/__promptfoo_telemetry_stub__.js`, shortCircuit: true };
  }
  return defaultResolve(specifier, context, defaultResolve);
}

export async function load(url, context, defaultLoad) {
  if (typeof url === 'string' && url.endsWith('__promptfoo_telemetry_stub__.js')) {
    const source = `export async function shutdown() { return; }\nexport function send() { return; }\nexport function start() { return; }\nexport default { shutdown, send, start };`;
    return { format: 'module', source, shortCircuit: true };
  }
  return defaultLoad(url, context, defaultLoad);
}
