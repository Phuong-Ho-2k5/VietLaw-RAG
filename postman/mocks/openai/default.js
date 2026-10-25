// Locally authored subset of the official Responses API contract; no real credentials.
// Fault markers are test fixtures, never runtime application switches.
const http = require('http');

http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const send = (status, body, headers = {}) => {
    res.writeHead(status, {'Content-Type': 'application/json', ...headers});
    res.end(JSON.stringify(body));
  };
  if (req.method !== 'POST' || pathname !== '/v1/responses') {
    return send(501, {error: {message: 'Endpoint not modeled'}});
  }
  try {
    const body = req.body || await new Promise((resolve, reject) => {
      let data = '';
      req.on('data', part => { data += part; });
      req.on('end', () => { try { resolve(JSON.parse(data)); } catch (e) { reject(e); } });
    });
    if (body.store !== false || body.text?.format?.type !== 'json_schema' ||
        body.text.format.strict !== true || body.tools || body.previous_response_id ||
        !body.model || typeof body.instructions !== 'string') {
      return send(400, {error: {message: 'Invalid Responses request contract'}});
    }
    const input = JSON.parse(body.input);
    const question = input.question || '';
    if (question.includes('__429__')) return send(429, {error: {message: 'Rate limited'}}, {'Retry-After': '0'});
    if (question.includes('__500__')) return send(500, {error: {message: 'Upstream unavailable'}});
    if (question.includes('__401__')) return send(401, {error: {message: 'Invalid key'}});
    if (question.includes('__timeout__')) await new Promise(resolve => setTimeout(resolve, 1500));
    let draft;
    if (body.text.format.name === 'RewriteResult') {
      draft = {standalone_question: question, needs_clarification: false, reason: '', fallback: false};
    } else if (question.includes('__abstain__')) {
      draft = {status: 'insufficient_evidence', clarification_question: null, claims: []};
    } else if (question.includes('__out_of_scope__')) {
      draft = {status: 'out_of_scope', clarification_question: null, claims: []};
    } else {
      const source = input.evidence?.[0];
      draft = source ? {status: 'answered', clarification_question: null,
        claims: [{text: source.text.trim(), source_ids: [question.includes('__fake_source__') ? 'fake' : source.chunk_id]}]}
        : {status: 'insufficient_evidence', clarification_question: null, claims: []};
    }
    const content = question.includes('__refusal__')
      ? [{type: 'refusal', refusal: 'Fixture refusal'}]
      : [{type: 'output_text', text: question.includes('__invalid_json__') ? '{' : JSON.stringify(draft), annotations: []}];
    return send(200, {id: 'resp_local', object: 'response', created_at: Math.floor(Date.now()/1000),
      status: question.includes('__incomplete__') ? 'incomplete' : 'completed', model: body.model,
      incomplete_details: question.includes('__incomplete__') ? {reason: 'max_output_tokens'} : null,
      output: [{id: 'msg_local', type: 'message', role: 'assistant', status: 'completed', content}],
      usage: {input_tokens: 20, output_tokens: 10, total_tokens: 30,
        input_tokens_details: {cached_tokens: 0}, output_tokens_details: {reasoning_tokens: 0}}});
  } catch (error) {
    return send(400, {error: {message: 'Invalid local fixture request'}});
  }
}).listen(process.env.PORT || 4500);
