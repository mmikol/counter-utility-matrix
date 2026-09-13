/* the board: TEAM and BANS are set by the page before this loads */
var el = function (id) { return document.getElementById(id); };
var ROSTER = null, st = { map: '', red: [], blue: [], bans: [], side: '' };
try { var saved = JSON.parse(localStorage.getItem('owdb-board2'));
      if (saved && saved.red && saved.blue) st = saved; } catch (e) {}
if (!st.bans) st.bans = [];
if (!st.side) st.side = '';
function currentMap() { return ROSTER ? ROSTER.maps.filter(function (x) { return x.name === st.map; })[0] : null; }

function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'); }
function save() { try { localStorage.setItem('owdb-board2', JSON.stringify(st)); } catch (e) {} }
function hero(name) { return ROSTER.byName[name]; }
function portrait(h, cls) {
  var initials = h.name.split(/[\s:.]+/).map(function (w) { return w[0]; }).join('').slice(0, 2);
  return h.portrait
    ? "<img src='" + esc(h.portrait) + "' alt='' loading='lazy' onerror=\"this.style.display='none';this.nextSibling.style.display='flex'\"><span class='ph' style='display:none'>" + esc(initials) + '</span>'
    : "<span class='ph'>" + esc(initials) + '</span>';
}

function buildTeam(team) {
  var slots = '';
  for (var i = 0; i < TEAM; i++) slots += "<div class='slot' data-team='" + team + "' data-i='" + i + "'></div>";
  el(team + 'slots').innerHTML = slots;
  var cols = '';
  ['tank', 'damage', 'support'].forEach(function (role) {
    var icon = ROSTER.role_icons[role] ? "<img src='" + esc(ROSTER.role_icons[role]) + "' alt=''>" : '';
    cols += "<div class='rolecol'><h4>" + icon + role + "</h4><div class='grid'>";
    ROSTER.heroes.filter(function (h) { return h.role === role; }).forEach(function (h) {
      cols += "<div class='tile' data-team='" + team + "' data-h=\"" + esc(h.name) + "\" title=\"" + esc(h.name + ' - ' + h.subrole) + "\">" + portrait(h) + "<span class='nm'>" + esc(h.name) + '</span></div>';
    });
    cols += '</div></div>';
  });
  el(team + 'roster').innerHTML = cols;
}

function toggle(team, name) {
  if (st.bans.indexOf(name) >= 0) { flash(name + ' is banned this match'); return; }
  var arr = st[team], at = arr.indexOf(name);
  if (at >= 0) arr.splice(at, 1);
  else if (arr.length < TEAM) arr.push(name);
  else { flash((team === 'red' ? 'red' : 'blue') + ' already has ' + TEAM + ' - click a lit hero to free the slot'); return; }
  save(); paint(); refresh();
}

function toggleBan(name) {
  var at = st.bans.indexOf(name);
  if (at >= 0) st.bans.splice(at, 1);
  else if (st.bans.length < BANS) {
    st.bans.push(name);
    ['red', 'blue'].forEach(function (team) {          /* a banned hero cannot be picked */
      var i = st[team].indexOf(name); if (i >= 0) st[team].splice(i, 1);
    });
  } else { flash('five bans already - click a chip to free one'); return; }
  save(); paint(); refresh();
}

function paintBans() {
  var out = '';
  st.bans.forEach(function (name) {
    var h = hero(name);
    out += "<span class='banchip' data-ban=\"" + esc(name) + "\" title='click to unban'>" +
      (h && h.portrait ? "<img src='" + esc(h.portrait) + "' alt=''>" : '') + '<b>✕</b>' + esc(name) + '</span>';
  });
  for (var i = st.bans.length; i < BANS; i++) out += "<span class='banslot'>" + (i < 4 ? (i < 2 ? 'red' : 'blue') : 'lobby') + '</span>';
  el('banslots').innerHTML = out;
  var sel = el('bansel');
  sel.innerHTML = "<option value=''>add a ban…</option>" + ROSTER.heroes.filter(function (h) {
    return st.bans.indexOf(h.name) < 0; }).map(function (h) {
    return "<option value=\"" + esc(h.name) + "\">" + esc(h.name) + ' (' + h.role + ')</option>'; }).join('');
  sel.disabled = st.bans.length >= BANS;
}

function paint() {
  paintBans();
  ['red', 'blue'].forEach(function (team) {
    var other = team === 'red' ? 'blue' : 'red';
    var slots = el(team + 'slots').children;
    for (var i = 0; i < TEAM; i++) {
      var name = st[team][i], s = slots[i];
      if (name) { var h = hero(name); s.className = 'slot full'; s.setAttribute('data-h', name);
        s.innerHTML = portrait(h) + "<span class='nm'>" + esc(name) + '</span>'; }
      else { s.className = 'slot'; s.removeAttribute('data-h'); s.innerHTML = "<span class='idx'>" + (i + 1) + '</span>'; }
    }
    var tiles = el(team + 'roster').querySelectorAll('.tile');
    for (var t = 0; t < tiles.length; t++) {
      var n = tiles[t].getAttribute('data-h');
      tiles[t].className = 'tile' + (st[team].indexOf(n) >= 0 ? ' on' : '') + (st[other].indexOf(n) >= 0 ? ' other' : '') +
        (st.bans.indexOf(n) >= 0 ? ' banned' : '');
    }
    el(team + 'count').textContent = st[team].length + '/' + TEAM;
  });
  el('mapsel').value = st.map;
  var m = currentMap();
  var sided = !!(m && m.sided);
  if (!sided) st.side = '';
  el('mode').textContent = m ? m.mode + (m.style ? ' · rewards ' + m.style : '') +
    (sided ? (st.side ? ' · blue ' + (st.side === 'attack' ? 'attacks' : 'defends') : ' · pick a side') : ' · no sides') : 'map unknown';
  el('sideseg').className = 'sideseg' + (sided ? ' show' : '');
  var sb = el('sideseg').querySelectorAll('button');
  for (var s = 0; s < sb.length; s++) sb[s].className = sb[s].getAttribute('data-side') === st.side ? 'on' : '';
}

document.addEventListener('click', function (e) {
  var sideBtn = e.target.closest ? e.target.closest('[data-side]') : null;
  if (sideBtn) { var sd = sideBtn.getAttribute('data-side'); st.side = st.side === sd ? '' : sd; save(); paint(); refresh(); return; }
  var ban = e.target.closest ? e.target.closest('[data-ban]') : null;
  if (ban) { toggleBan(ban.getAttribute('data-ban')); return; }
  var hit = e.target.closest ? e.target.closest('[data-h][data-team]') : null;
  if (hit) toggle(hit.getAttribute('data-team'), hit.getAttribute('data-h'));
  var tab = e.target.closest ? e.target.closest('nav.tabs button') : null;
  if (tab) showTab(tab.getAttribute('data-tab'));
});

var flashTimer = null;
function flash(msg) { el('status').textContent = msg; clearTimeout(flashTimer);
  flashTimer = setTimeout(function () { el('status').textContent = ''; }, 3000); }

function qs() {
  var q = [];
  if (st.map) q.push('map=' + encodeURIComponent(st.map));
  st.red.forEach(function (h) { q.push('red=' + encodeURIComponent(h)); });
  st.blue.forEach(function (h) { q.push('blue=' + encodeURIComponent(h)); });
  st.bans.forEach(function (h) { q.push('ban=' + encodeURIComponent(h)); });
  if (st.side) q.push('side=' + st.side);
  return q.join('&');
}

var pending = null, seq = 0, FACTS = null, INF = null;
function refresh() {
  clearTimeout(pending);
  el('status').textContent = 'reading the database…';
  pending = setTimeout(function () {
    var mine = ++seq, q = qs();
    fetch('/api/facts?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      if (d.error) { flash(d.error); return; }
      FACTS = d; renderFacts(); el('factsn').textContent = d.count;
      el('status').textContent = d.count + ' facts + ' + (d.strategy_count || 0) + ' strategy notes · ' + new Date().toLocaleTimeString();
    }).catch(function () { flash('the database is not answering'); });
    el('inf-blue').innerHTML = "<p class='legend'>searching both seats…</p>"; el('inf-red').innerHTML = '';
    el('cur').innerHTML = "<p class='legend'>scoring the current comp…</p>";
    fetch('/api/infer?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      INF = d; renderInf();
    }).catch(function () { el('inf-blue').innerHTML = "<p class='legend'>inference is not answering</p>"; });
  }, 200);
}

var SCOPES = ['meta', 'bans', 'map', 'hero', 'team', 'matchup', 'strategy'];
var scopeOn = { meta: true, bans: true, map: true, hero: true, team: true, matchup: true, strategy: true };
function renderFacts() {
  if (!FACTS) return;
  var f = el('filter').value.toLowerCase(), out = '', last = null;
  FACTS.facts.forEach(function (x) {
    if (!scopeOn[x.scope]) return;
    if (f && (x.id + ' ' + x.key + ' ' + x.subject + ' ' + x.text).toLowerCase().indexOf(f) < 0) return;
    var head = x.scope === 'hero' ? (x.team + ' · ' + x.subject) : x.scope === 'team' ? (x.subject + ' team') : x.scope;
    if (x.scope === 'bans') head = 'bans';
    if (x.scope === 'strategy') head = 'strategies \u00b7 authored, recorded, tuned \u2014 not facts';
    if (head !== last) { out += "<tr class='h'><td colspan='3' class='head'>" + esc(head) + '</td></tr>'; last = head; }
    var cls = (x.team || '') + (/^(WARNING|CAUTION)/.test(x.text) ? ' warn' : '') + (x.source.indexOf('derived:') === 0 ? ' derived' : '');
    out += "<tr class='" + cls + "'><td class='tag'>[" + x.id + "]</td><td class='text'>" + esc(x.text) + "</td><td class='src'>" + esc(x.source) + '</td></tr>';
  });
  el('factbody').innerHTML = out || "<tr><td class='src'>nothing matches</td></tr>";
}

function bars(contribs) {
  var mx = 0.01;
  contribs.forEach(function (c) { mx = Math.max(mx, Math.abs(c.weighted || 0)); });
  var out = "<div class='bars'>";
  contribs.forEach(function (c) {
    var w = Math.abs(c.weighted || 0) / mx * 100;
    var detail = c.kind === 'goal' ? (c.applies ? c.metric + ' = ' + (typeof c.raw === 'number' ? +c.raw.toFixed(2) : c.raw) + ' · norm ' + (+c.norm).toFixed(2) : 'not applicable here')
               : c.kind === 'strategy' ? (c.applies ? 'bonus ' + c.bonus + ' − penalty ' + c.penalty : 'condition not met')
               : (c.ok ? 'satisfied' : 'VIOLATED');
    out += "<div class='bar" + ((c.weighted || 0) < 0 ? ' neg' : '') + (c.applies === false ? ' off' : '') + "' title=\"" + esc(detail + (c.text ? ' — ' + c.text : '')) + "\"><span class='lbl'>" + esc(c.id) + (c.fact ? " <span class='ev'>" + c.fact + '</span>' : '') + "</span><span class='trk'><span class='fill' style='width:" + w.toFixed(1) + "%'></span></span><span class='val'>" + ((c.weighted || 0) >= 0 ? '+' : '') + (+(c.weighted || 0)).toFixed(2) + '</span></div>';
  });
  return out + '</div>';
}

function renderInf() {
  var d = INF;
  if (!d || d.error) { el('inf-blue').innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; el('inf-red').innerHTML = ''; el('cur').innerHTML = ''; return; }
  renderResult(d.blue, el('inf-blue'), 'blue - optimal six' + (d.side ? ' on ' + d.side : ''), true);
  renderResult(d.red, el('inf-red'), 'red - their optimal six' + (d.side ? ' on ' + (d.side === 'attack' ? 'defense' : 'attack') : ''), false);
  var c = d.current;
  if (!c.blue || !c.blue.length) el('cur').innerHTML = "<p class='legend'>lock a blue pick to score the current comp; six picks are ranked against the whole field.</p>";
  else renderResult(c, el('cur'), c.kind === 'evaluate' ? 'current comp - your six, ranked' : 'current comp - ' + c.blue.length + ' of ' + TEAM + ' picked', false);
}

function renderResult(d, container, title, recordable) {
  if (!d || d.error) { container.innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; return; }
  var out = "<div class='inf-head'><h3>" + esc(title) + "</h3><span class='score'>score " + (+d.score).toFixed(2) + "</span><span class='legend'>" +
    (d.rank ? 'rank ' + d.rank + ' among the feasible field · ' : '') + (d.considered ? d.considered + ' candidates · ' : '') + d.seconds + 's · ' +
    d.heuristics.constraint + ' constraints, ' + d.heuristics.goal + ' goals, ' + d.heuristics.strategy + ' strategies' +
    (d.playstyle ? ' · leans ' + d.playstyle : '') + '</span>' +
    (recordable ? "<button class='primary' id='recbtn'>record this comp</button>" : '') + '</div>';
  if (d.partial) out += "<div class='partial'>partial: " + d.blue.length + ' of ' + TEAM + ' picked - sums (damage, healing, HP) read low until the team is full; the breakdown uses the optimal search\u2019s field</div>';
  if (d.violations && d.violations.length) out += "<div class='warnbox'>violates: " + esc(d.violations.join(', ')) + '</div>';
  out += "<div class='comp'>";
  d.picks.forEach(function (p) {
    var h = hero(p.hero) || { name: p.hero, portrait: p.portrait };
    out += "<div class='card'><div class='pic'>" + portrait(h) + "<span class='role'>" + esc(p.role) + '</span>' + (p.locked ? "<span class='lock'>LOCKED</span>" : '') +
      "</div><div class='body'><b>" + esc(p.hero) + "</b><div class='why'>" + esc(p.why) + '</div>' +
      p.evidence.map(function (id) { return "<span class='ev' title=\"" + esc(d.cited[id] || id) + "\">" + id + '</span>'; }).join('') + '</div></div>';
  });
  out += '</div>' + bars(d.contributions || []);
  if (d.alternatives && d.alternatives.length) {
    out += "<div class='alts'><b>" + (d.kind === 'infer' ? 'alternatives' : 'the field\u2019s best') + "</b><ol>" +
      d.alternatives.map(function (a) { return '<li>' + esc(a.blue.join(', ')) + " <span class='legend'>(" + (+a.score).toFixed(2) + ')</span></li>'; }).join('') + '</ol></div>';
  }
  if (recordable) out += "<div class='notice' id='recnote'></div>";
  container.innerHTML = out;
  var btn = recordable ? el('recbtn') : null;
  if (btn) btn.onclick = function () { recordComp(d); };
}

function recordComp(d) {
  var answer = { playstyle: d.playstyle || 'balanced', reasoning: 'solver optimum under the catalog: score ' + (+d.score).toFixed(2) + ' over ' + d.considered + ' candidates',
    picks: d.picks.map(function (p) { return { hero: p.hero, why: p.why, evidence: p.evidence }; }) };
  fetch('/api/record', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'board: ' + (st.map || 'any map') + (st.side ? ' (' + st.side + ')' : '') + ' vs ' + st.red.join(', ') + (st.bans.length ? ' (bans: ' + st.bans.join(', ') + ')' : ''), map: st.map || null, side: st.side, red: st.red, blue: st.blue, bans: st.bans, model: 'inference-engine', answer: answer }) })
    .then(function (r) { return r.json(); }).then(function (r) {
      var n = el('recnote'); n.style.display = 'block';
      n.innerHTML = r.error ? 'refused: ' + esc(r.error) : 'recorded as <a href="/rec/' + r.rec_id + '">recommendation #' + r.rec_id + '</a> - ' + esc(r.transcript);
    });
}

function renderPlaybook(d) {
  var out = "<div class='hcards'>";
  d.heuristics.forEach(function (h) {
    var meta = h.kind === 'goal' ? h.direction + ' ' + h.metric + ' · weight ' + h.weight
             : h.kind === 'constraint' ? 'require ' + h.require + (h.soft ? ' · soft, penalty ' + h.penalty : ' · hard') + (h.when ? ' · when ' + h.when : '')
             : (h.bonus || h.penalty) ? [h.when ? 'when ' + h.when : '', h.bonus ? 'bonus ' + h.bonus : '', h.penalty ? 'penalty ' + h.penalty : ''].filter(Boolean).join(' · ') + ' · weight ' + h.weight
             : 'prose - read by the session, shown here, not scored';
    var params = Object.keys(h.params || {}).map(function (k) { return k + '=' + h.params[k]; }).join(', ');
    var body = h.body.replace(/^#[^\n]*\n/, '').split(/\n\s*\n/).map(function (p) { return '<p>' + esc(p.replace(/\s+/g, ' ')) + '</p>'; }).join('');
    out += "<div class='hcard'><span class='kind " + h.kind + "'>" + h.kind + '</span><b>' + esc(h.name) + "</b><div class='meta'>" + esc(meta) + (params ? ' · params ' + esc(params) : '') + '</div>' + body +
      "<div class='legend'>inference/heuristics/" + esc(h.id) + '.md · ' + esc(h.category) + '</div></div>';
  });
  el('playbook').innerHTML = out + '</div>';
}

function showTab(name) {
  document.querySelectorAll('nav.tabs button').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-tab') === name); });
  document.querySelectorAll('.panel').forEach(function (p) { p.classList.toggle('active', p.id === 'tab-' + name); });
  try { localStorage.setItem('owdb-tab', name); } catch (e) {}
}

var lastRec = null;
function pollRecs() {
  fetch('/api/recs').then(function (r) { return r.json(); }).then(function (d) {
    if (lastRec !== null && d.latest > lastRec) { var n = el('newrec'); n.style.display = 'block';
      n.innerHTML = 'the session just recorded <a href="/rec/' + d.latest + '">recommendation #' + d.latest + '</a> - ' + esc(d.summary); }
    lastRec = d.latest;
  }).catch(function () {});
}

fetch('/api/roster').then(function (r) { return r.json(); }).then(function (d) {
  ROSTER = d; ROSTER.byName = {};
  d.heroes.forEach(function (h) { ROSTER.byName[h.name] = h; });
  el('mapsel').innerHTML = "<option value=''>MAP UNKNOWN / ANY</option>" + d.maps.map(function (m) { return "<option value=\"" + esc(m.name) + "\">" + esc(m.name) + '</option>'; }).join('');
  st.red = st.red.filter(function (h) { return ROSTER.byName[h]; });
  st.blue = st.blue.filter(function (h) { return ROSTER.byName[h]; });
  if (!d.maps.some(function (m) { return m.name === st.map; })) st.map = '';
  buildTeam('red'); buildTeam('blue'); paint();
  var blz = (d.snapshots || []).filter(function (s) { return s.source === 'blizzard'; })[0];
  if (blz) el('captured').textContent = 'rates captured ' + blz.captured + ' (' + (blz.patch || 'unknown patch') + ')';
  if (d.newer_patches && d.newer_patches.length) { var w = el('vintage'); w.style.display = 'block';
    w.textContent = d.newer_patches.length + ' patch(es) shipped since the rates were captured (newest ' + d.newer_patches[0][0] + ') - rates are pre-patch; run pull_rates'; }
  el('mapsel').onchange = function () { st.map = this.value; save(); paint(); refresh(); };
  el('bansel').onchange = function () { if (this.value) toggleBan(this.value); };
  el('filter').oninput = renderFacts;
  el('clearbtn').onclick = function () { st = { map: '', red: [], blue: [], bans: [], side: '' }; save(); paint(); refresh(); };
  el('swapbtn').onclick = function () { var r = st.red; st.red = st.blue; st.blue = r; st.side = st.side === 'attack' ? 'defense' : st.side === 'defense' ? 'attack' : ''; save(); paint(); refresh(); };
  var chips = el('chips'); chips.innerHTML = SCOPES.map(function (s) { return "<button class='chip on' data-scope='" + s + "'>" + s + '</button>'; }).join('');
  chips.onclick = function (e) { var c = e.target.closest('.chip'); if (!c) return; var s = c.getAttribute('data-scope');
    scopeOn[s] = !scopeOn[s]; c.classList.toggle('on', scopeOn[s]); renderFacts(); };
  fetch('/api/heuristics').then(function (r) { return r.json(); }).then(renderPlaybook);
  showTab((function () { try { return localStorage.getItem('owdb-tab') || 'facts'; } catch (e) { return 'facts'; } })());
  refresh(); pollRecs(); setInterval(pollRecs, 8000);
});
