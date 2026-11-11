// Send one chat request through the OpenAI-compatible endpoint of the LLM Application as the signed-in user.
const token = document.documentElement.getAttribute('data-xwiki-form-token');
const start = performance.now();
const r = await fetch('/rest/wikis/xwiki/aiLLM/v1/chat/completions', {method: 'POST',
  headers: {'Content-Type': 'application/json', 'XWiki-Form-Token': token, Accept: 'application/json'},
  body: JSON.stringify({model: 'AI.Models.ornith', stream: false, messages: [{role: 'user', content: 'Write one sentence about a wiki.'}]})});
const text = await r.text();
let answer = text.slice(0, 300);
try { answer = JSON.parse(text).choices[0].message.content.slice(0, 300); } catch (e) {}
return JSON.stringify({status: r.status, seconds: Math.round(performance.now() - start) / 1000, answer});
