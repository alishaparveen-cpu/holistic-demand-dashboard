/* ask-widget.js — shared "Ask the dashboard" Claude copilot, reusable on any page.
 *
 * Bring-your-own-key: the Anthropic API key is stored ONLY in this browser's
 * localStorage and sent directly to api.anthropic.com — never to the repo or a server.
 *
 * Usage on a host page (after its data has loaded):
 *   <script src="ask-widget.js"></script>
 *   AskWidget.init({
 *     title: 'Demand copilot',
 *     suggestions: ['Why did bookings drop in Pune?', ...],
 *     systemPrompt: 'You are ... Schema: ...',
 *     contextFn: () => ({ ...compact JSON built from THIS page's data globals... })
 *   });
 * The contextFn is called fresh on every question, so it reflects the current filters.
 */
(function () {
  var LS = 'allo_anthropic_key', MODEL = 'claude-sonnet-5';
  var HIST = [], CFG = { title: 'Copilot', suggestions: [], systemPrompt: '', contextFn: function () { return {}; } };

  var CSS = `
  #askLaunch{position:fixed;bottom:20px;right:20px;z-index:2147483000;background:#2C6CAE;color:#fff;border:0;border-radius:26px;padding:11px 18px;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-weight:600;cursor:pointer;box-shadow:0 6px 20px rgba(44,108,174,.4);display:flex;align-items:center;gap:7px}
  #askPanel{position:fixed;bottom:20px;right:20px;z-index:2147483001;width:400px;max-width:calc(100vw - 32px);height:580px;max-height:calc(100vh - 40px);background:#fff;border:1px solid #e6e9ee;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1f2733}
  #askPanel.on{display:flex}
  #askPanel .h{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid #e6e9ee;background:#eef3f9}
  #askPanel .h b{font-size:14px}#askPanel .h .sm{font-size:11px;color:#6b7580}
  #askPanel .h .x,#askPanel .h .gear{margin-left:0;cursor:pointer;color:#6b7580;font-size:16px;border:0;background:none}
  #askPanel .h .x{margin-left:auto;font-size:18px}
  #askMsgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
  #askPanel .m{max-width:88%;padding:8px 11px;border-radius:11px;font-size:13px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word}
  #askPanel .m.u{align-self:flex-end;background:#2C6CAE;color:#fff;border-bottom-right-radius:3px}
  #askPanel .m.a{align-self:flex-start;background:#f1f4f8;color:#1f2733;border-bottom-left-radius:3px}
  #askPanel .m.sys{align-self:center;background:#fbf7ee;color:#7a6a3f;font-size:11.5px;border:1px solid #efe3c8;text-align:center}
  #askSug{display:flex;flex-wrap:wrap;gap:6px;padding:0 11px 8px}
  #askSug span{font-size:11px;border:1px solid #e6e9ee;border-radius:12px;padding:3px 9px;cursor:pointer;color:#2C6CAE}
  #askForm{display:flex;gap:7px;padding:11px;border-top:1px solid #e6e9ee}
  #askForm textarea{flex:1;resize:none;border:1px solid #e6e9ee;border-radius:8px;padding:7px 9px;font:13px inherit;height:38px;max-height:120px;color:#1f2733}
  #askForm button{border:0;background:#2C6CAE;color:#fff;border-radius:8px;padding:0 14px;font-weight:600;cursor:pointer}
  #askForm button:disabled{opacity:.5;cursor:default}`;

  function el(id) { return document.getElementById(id); }
  function key() { return localStorage.getItem(LS) || ''; }
  function setKey() {
    var k = prompt('Paste your Anthropic API key (starts with sk-ant-…).\nStored ONLY in this browser (localStorage) and sent directly to Anthropic — never to our servers or the repo.', key());
    if (k !== null) { localStorage.setItem(LS, k.trim()); return k.trim(); } return key();
  }
  function add(role, text) {
    var d = document.createElement('div');
    d.className = 'm ' + (role === 'user' ? 'u' : role === 'sys' ? 'sys' : 'a');
    d.textContent = text; el('askMsgs').appendChild(d); el('askMsgs').scrollTop = 1e9; return d;
  }
  async function send(q) {
    var k = key(); if (!k) { k = setKey(); if (!k) { add('sys', 'No API key set — click ⚙ to add one.'); return; } }
    add('user', q); HIST.push({ role: 'user', content: q });
    var wait = add('assistant', '…'); el('askSend').disabled = true;
    var ctx; try { ctx = CFG.contextFn() || {}; } catch (e) { ctx = { error: 'context build failed: ' + e.message }; }
    try {
      var res = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-api-key': k, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: MODEL, max_tokens: 1200, system: CFG.systemPrompt + '\n\nDATA (JSON, reflects the on-screen filters):\n' + JSON.stringify(ctx), messages: HIST })
      });
      if (!res.ok) { var t = await res.text(); wait.textContent = res.status === 401 ? 'Invalid API key — click ⚙ to re-enter.' : ('Error ' + res.status + ': ' + t.slice(0, 220)); wait.className = 'm sys'; el('askSend').disabled = false; return; }
      var j = await res.json(); var txt = (j.content || []).map(function (b) { return b.text || ''; }).join('').trim() || '(no answer)';
      wait.textContent = txt; HIST.push({ role: 'assistant', content: txt });
    } catch (e) { wait.textContent = 'Network error: ' + e.message; wait.className = 'm sys'; }
    el('askSend').disabled = false;
  }

  function mount() {
    var style = document.createElement('style'); style.textContent = CSS; document.head.appendChild(style);
    var wrap = document.createElement('div');
    wrap.innerHTML =
      '<button id="askLaunch">💬 Ask the dashboard</button>' +
      '<div id="askPanel"><div class="h"><b id="askTitle">Copilot</b><span class="sm">Claude · your data</span>' +
      '<button class="gear" id="askGear" title="change API key">⚙</button><button class="x" id="askClose">✕</button></div>' +
      '<div id="askMsgs"></div><div id="askSug"></div>' +
      '<form id="askForm"><textarea id="askInput" placeholder="Ask… e.g. why did this drop?" rows="1"></textarea>' +
      '<button type="submit" id="askSend">➤</button></form></div>';
    document.body.appendChild(wrap);
    el('askLaunch').onclick = function () {
      el('askPanel').classList.add('on'); el('askLaunch').style.display = 'none';
      if (!el('askMsgs').children.length) add('sys', 'Ask me anything about the data on screen — I read your current scope, filters and week window. (Powered by Claude with your own API key.)');
      el('askInput').focus();
    };
    el('askClose').onclick = function () { el('askPanel').classList.remove('on'); el('askLaunch').style.display = 'flex'; };
    el('askGear').onclick = function () { setKey(); };
    el('askForm').onsubmit = function (e) { e.preventDefault(); var q = el('askInput').value.trim(); if (!q) return; el('askInput').value = ''; send(q); };
    el('askInput').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); el('askForm').requestSubmit(); } });
  }

  window.AskWidget = {
    init: function (opts) {
      CFG = Object.assign(CFG, opts || {});
      var go = function () {
        if (!el('askPanel')) mount();
        el('askTitle').textContent = CFG.title;
        el('askSug').innerHTML = (CFG.suggestions || []).map(function (s) { return '<span>' + s.replace(/</g, '&lt;') + '</span>'; }).join('');
        Array.prototype.forEach.call(el('askSug').querySelectorAll('span'), function (sp) {
          sp.onclick = function () { el('askInput').value = sp.textContent; el('askInput').focus(); };
        });
      };
      if (document.body) go(); else document.addEventListener('DOMContentLoaded', go);
    }
  };
})();
