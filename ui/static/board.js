/* the board: TEAM and BANS are set by the page before this loads */
var el = function (id) { return document.getElementById(id); };
var ROSTER = null, st = { map: '', red: [], blue: [], bans: [], side: '' };
try { var saved = JSON.parse(localStorage.getItem('owdb-board2'));
      if (saved && saved.red && saved.blue) st = saved; } catch (e) {}
if (!st.bans) st.bans = [];
if (!st.side) st.side = '';
var TABS = ['comps', 'facts', 'playbook'];   /* the panels; the first is the default */
var bansOpen = false;                        /* the ban picker starts collapsed */

/* An announced hero the database does not carry yet. It is drawn on both
   rosters and on the ban picker as a non-selectable card - no data-h, no
   data-team, so the click handler never sees it - and it never enters
   st.red, st.blue or st.bans, so it is never sent to the API. Delete this
   constant (and the 'announced' group rosterHTML renders from it) once the
   hero lands in the database and /api/roster carries it. */
var DOCTRINE = { name: 'Doctrine', role: 'announced', subrole: 'role not yet known', tag: 'coming soon' };

function currentMap() { return ROSTER ? ROSTER.maps.filter(function (x) { return x.name === st.map; })[0] : null; }

function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'); }
function save() { try { localStorage.setItem('owdb-board2', JSON.stringify(st)); } catch (e) {} }
function hero(name) { return ROSTER.byName[name]; }
function portrait(h) {
  var initials = h.name.split(/[\s:.]+/).map(function (w) { return w[0]; }).join('').slice(0, 2);
  return h.portrait
    ? "<img src='" + esc(h.portrait) + "' alt='' loading='lazy' onerror=\"this.style.display='none';this.nextSibling.style.display='flex'\"><span class='ph' style='display:none'>" + esc(initials) + '</span>'
    : "<span class='ph'>" + esc(initials) + '</span>';
}

/* --- the rosters: one tile renderer for red, blue and the ban picker ------ */
var SILHOUETTE = "<svg class='sil' viewBox='0 0 48 64' aria-hidden='true'><circle cx='24' cy='23' r='10'/>" +
  "<path d='M7 64c0-14 7.5-23 17-23s17 9 17 23z'/></svg>";

function tile(h, team) {
  return "<div class='tile' data-team='" + team + "' data-h=\"" + esc(h.name) + "\" title=\"" + esc(h.name + ' - ' + h.subrole) + "\">" +
    portrait(h) + "<span class='nm'>" + esc(h.name) + '</span></div>';
}
function announcedTile(h) {
  return "<div class='tile soon' title=\"" + esc(h.name + ' - announced, not in the database yet (' + h.subrole + ')') + "\">" +
    SILHOUETTE + "<span class='tag'>" + esc(h.tag) + "</span><span class='nm'>" + esc(h.name) + '</span></div>';
}
function rosterHTML(team) {
  var cols = '';
  ['tank', 'damage', 'support'].forEach(function (role) {
    var icon = ROSTER.role_icons[role] ? "<img src='" + esc(ROSTER.role_icons[role]) + "' alt=''>" : '';
    cols += "<div class='rolecol'><h4>" + icon + role + "</h4><div class='grid'>";
    ROSTER.heroes.filter(function (h) { return h.role === role; }).forEach(function (h) { cols += tile(h, team); });
    cols += '</div></div>';
  });
  cols += "<div class='rolecol announced'><h4>announced</h4><div class='grid'>" + announcedTile(DOCTRINE) + '</div></div>';
  return cols;
}

function buildTeam(team) {
  var slots = '';
  for (var i = 0; i < TEAM; i++) slots += "<div class='slot' data-team='" + team + "' data-i='" + i + "'></div>";
  el(team + 'slots').innerHTML = slots;
  el(team + 'roster').innerHTML = rosterHTML(team);
}
function buildBanPicker() { el('banroster').innerHTML = rosterHTML('ban'); }

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
  } else { flash(BANS + ' bans already - click a banned hero or its slot to free one'); return; }
  save(); paint(); refresh();
}

/* the bans bar: a header (count and small portraits, click to open), the five
   slots, and the same portrait grid the rosters use - a click bans, a click on
   a banned tile or its slot un-bans */
function paintBans() {
  var slots = '', mini = '';
  st.bans.forEach(function (name) {
    var h = hero(name) || { name: name, portrait: '' };
    slots += "<div class='slot full' data-ban=\"" + esc(name) + "\" title='click to unban'>" + portrait(h) + "<span class='nm'>" + esc(name) + '</span></div>';
    mini += "<span class='banchip' data-ban=\"" + esc(name) + "\" title='click to unban'>" +
      (h.portrait ? "<img src='" + esc(h.portrait) + "' alt=''>" : '') + '<b>✕</b>' + esc(name) + '</span>';
  });
  for (var i = st.bans.length; i < BANS; i++) slots += "<div class='slot'><span class='idx'>" + (i < 4 ? (i < 2 ? 'red' : 'blue') : 'lobby') + '</span></div>';
  el('banslots').innerHTML = slots;
  el('banmini').innerHTML = mini;
  el('bancount').textContent = st.bans.length + '/' + BANS;
  var tiles = el('banroster').querySelectorAll('.tile[data-h]');
  for (var t = 0; t < tiles.length; t++) {
    var n = tiles[t].getAttribute('data-h');
    tiles[t].className = 'tile' + (st.bans.indexOf(n) >= 0 ? ' banned' : '') +
      (st.red.indexOf(n) >= 0 ? ' inred' : '') + (st.blue.indexOf(n) >= 0 ? ' inblue' : '');
  }
  el('bans').className = 'bans' + (bansOpen ? ' open' : '') + (st.bans.length >= BANS ? ' maxed' : '');
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
    var tiles = el(team + 'roster').querySelectorAll('.tile[data-h]');   /* the announced card keeps its own class */
    for (var t = 0; t < tiles.length; t++) {
      var n = tiles[t].getAttribute('data-h');
      tiles[t].className = 'tile' + (st[team].indexOf(n) >= 0 ? ' on' : '') + (st[other].indexOf(n) >= 0 ? ' other' : '') +
        (st.bans.indexOf(n) >= 0 ? ' banned' : '');
    }
    el(team + 'count').textContent = st[team].length + '/' + TEAM;
  });
  paintSuggestions();
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
  var near = function (sel) { return e.target.closest ? e.target.closest(sel) : null; };
  var sideBtn = near('[data-side]');
  if (sideBtn) { var sd = sideBtn.getAttribute('data-side'); st.side = st.side === sd ? '' : sd; save(); paint(); refresh(); return; }
  var clear = near('[data-clear]');                   /* a team's clear button: that team's picks only */
  if (clear) { st[clear.getAttribute('data-clear')] = []; save(); paint(); refresh(); return; }
  var ban = near('[data-ban]');                       /* a ban slot or a header chip: un-ban */
  if (ban) { toggleBan(ban.getAttribute('data-ban')); return; }
  if (near('#banhead')) { bansOpen = !bansOpen; paintBans(); return; }
  var hit = near('[data-h][data-team]');              /* a roster tile, a team slot, or a picker tile */
  if (hit) {
    var team = hit.getAttribute('data-team'), name = hit.getAttribute('data-h');
    if (team === 'ban') toggleBan(name); else toggle(team, name);
    return;
  }
  var tab = near('nav.tabs button');
  if (tab) showTab(tab.getAttribute('data-tab'));
});

var flashTimer = null;
function flash(msg) { el('flash').textContent = msg; clearTimeout(flashTimer);
  flashTimer = setTimeout(function () { el('flash').textContent = ''; }, 3000); }

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
      el('status').textContent = d.count + ' facts + ' + (d.playbook_count || 0) + ' playbook notes · ' + new Date().toLocaleTimeString();
    }).catch(function () { flash('the database is not answering'); });
    el('inf-blue').innerHTML = "<p class='legend'>searching both seats…</p>"; el('inf-red').innerHTML = '';
    fetch('/api/infer?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      INF = d; renderInf();
    }).catch(function () { el('inf-blue').innerHTML = "<p class='legend'>inference is not answering</p>"; });
  }, 200);
}

var SCOPES = ['meta', 'bans', 'map', 'hero', 'team', 'matchup', 'playbook'];
var scopeOn = { meta: true, bans: true, map: true, hero: true, team: true, matchup: true, playbook: true };
function renderFacts() {
  if (!FACTS) return;
  var f = el('filter').value.toLowerCase(), out = '', last = null;
  FACTS.facts.forEach(function (x) {
    if (!scopeOn[x.scope]) return;
    if (f && (x.id + ' ' + x.key + ' ' + x.subject + ' ' + x.text).toLowerCase().indexOf(f) < 0) return;
    var head = x.scope === 'hero' ? (x.team + ' · ' + x.subject) : x.scope === 'team' ? (x.subject + ' team') : x.scope;
    if (x.scope === 'bans') head = 'bans';
    if (x.scope === 'playbook') head = 'the playbook’s record · what it holds — not facts';
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
    var detail = c.form === 'heuristic' ? (c.applies ? c.metric + ' = ' + (typeof c.raw === 'number' ? +c.raw.toFixed(2) : c.raw) + ' · norm ' + (+c.norm).toFixed(2) : 'not applicable here')
               : c.form === 'scored' ? (c.applies ? 'bonus ' + c.bonus + ' − penalty ' + c.penalty : 'condition not met')
               : (c.ok ? 'limit satisfied' : 'limit VIOLATED');
    out += "<div class='bar" + ((c.weighted || 0) < 0 ? ' neg' : '') + (c.applies === false ? ' off' : '') + "' title=\"" + esc(detail + (c.text ? ' — ' + c.text : '')) + "\"><span class='lbl'>" + esc(c.id) + (c.fact ? " <span class='ev'>" + c.fact + '</span>' : '') + "</span><span class='trk'><span class='fill' style='width:" + w.toFixed(1) + "%'></span></span><span class='val'>" + ((c.weighted || 0) >= 0 ? '+' : '') + (+(c.weighted || 0)).toFixed(2) + '</span></div>';
  });
  return out + '</div>';
}

/* the 0-100 figure (`normalized`: 100 for an optimal six, the current comp's
   share of blue's optimal) large, the raw score small beside it and as the
   tooltip; a response without `normalized` shows the raw score alone */
function scoreHTML(d) {
  var raw = 'score ' + (+d.score).toFixed(2);
  if (typeof d.normalized === 'number')
    return "<span class='score' title='" + raw + "'>" + Math.round(d.normalized) + "<small>/ 100</small></span><span class='raw'>" + raw + '</span>';
  return "<span class='score' title='the raw score under the catalog'>" + raw + '</span>';
}
function altScore(a) {
  return (typeof a.normalized === 'number' ? "<span class='altn'>" + Math.round(a.normalized) + ' / 100</span> ' : '') +
    "<span class='legend'>(score " + (+a.score).toFixed(2) + ')</span>';
}

/* the comps panel: blue's optimal six and red's side by side, the current comp below */
function renderInf() {
  var d = INF;
  if (!d || d.error) { el('inf-blue').innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; el('inf-red').innerHTML = ''; el('momentum').innerHTML = ''; el('plan').innerHTML = ''; el('bluescore').textContent = ''; el('redscore').textContent = ''; return; }
  var text = (d.plan || '').split('\n'), basis = text.length && text[text.length - 1].indexOf('Based on:') === 0 ? text.pop() : '';
  el('plan').innerHTML = "<span class='lbl'>game plan</span><div class='text'>" + text.map(esc).join('<br>') + '</div>' + (basis ? "<div class='basis'>" + esc(basis) + '</div>' : '');
  var mo = d.momentum || {};
  el('momentum').innerHTML = "<span class='lbl'>momentum</span> <b>" + esc(mo.verdict || '') + '</b>' +
    (typeof mo.blue === 'number' && typeof mo.red === 'number' ? "<span class='gauge'><span class='b' style='width:" + mo.blue + "%'></span><span class='r' style='width:" + mo.red + "%'></span></span>" : '');
  var rc = d.red_current;
  if (!rc || !rc.blue || !rc.blue.length) el('inf-red').innerHTML = "<div class='inf-head'><h3>red - their comp as revealed</h3></div>" +
    "<p class='legend'>click red picks as they reveal; their comp is scored against yours, on the scale of their best counter to you.</p>";
  else renderResult(rc, el('inf-red'), 'red - their comp as revealed' + (rc.kind === 'evaluate' ? ', ranked' : ' (' + rc.blue.length + ' of ' + TEAM + ')'));
  renderResult(d.blue, el('inf-blue'), 'blue - optimal six: the counter to their selection' + (d.side ? ', on ' + d.side : ''));
  var c = d.current;
  el('bluescore').textContent = (c && c.blue && c.blue.length && typeof c.normalized === 'number') ? c.normalized + ' / 100' : '';
  el('redscore').textContent = (rc && rc.blue && rc.blue.length && typeof rc.normalized === 'number') ? rc.normalized + ' / 100' : '';
  paintSuggestions();
}

/* the empty blue slots carry the solver's suggestions: the optimal six before
   any pick, then the best six that keeps the locked ones - a click locks one */
function paintSuggestions() {
  var slots = el('blueslots').children, d = INF;
  var src = !d || d.error ? null : (st.blue.length ? d.fill : d.blue);
  var open = src && src.picks ? src.picks.filter(function (p) { return !p.locked && st.blue.indexOf(p.hero) < 0; }) : [];
  for (var i = st.blue.length, k = 0; i < TEAM; i++) {
    var s = slots[i], p = open[k++];
    if (!p) continue;
    var h = hero(p.hero) || { name: p.hero, portrait: p.portrait };
    s.className = 'slot suggested'; s.setAttribute('data-h', p.hero); s.title = p.why;
    s.innerHTML = portrait(h) + "<span class='idx'>" + (i + 1) + "</span><span class='sug'>suggested</span><span class='nm'>" + esc(p.hero) + '</span>';
  }
}

function renderResult(d, container, title) {
  if (!d || d.error) { container.innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; return; }
  var out = "<div class='inf-head'><h3>" + esc(title) + '</h3>' + scoreHTML(d) + "<span class='legend'>" +
    (d.rank ? 'rank ' + d.rank + ' among the feasible field · ' : '') + (d.considered ? d.considered + ' candidates · ' : '') + d.seconds + 's · ' +
    d.strategies.constraint + ' constraints, ' + d.strategies.heuristic + ' heuristics' +
    (d.playstyle ? ' · leans ' + d.playstyle : '') + '</span>' +
    '</div>';
  if (d.partial) out += "<div class='partial'>partial: " + d.blue.length + ' of ' + TEAM + ' picked - sums (damage, healing, HP) read low until the team is full; the breakdown uses the optimal search’s field</div>';
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
    out += "<div class='alts'><b>" + (d.kind === 'infer' ? 'alternatives' : 'the field’s best') + "</b><ol>" +
      d.alternatives.map(function (a) { return '<li>' + esc(a.blue.join(', ')) + ' ' + altScore(a) + '</li>'; }).join('') + '</ol></div>';
  }
  container.innerHTML = out;
}

function renderPlaybook(d) {
  if (!d || !d.strategies) { el('playbook').innerHTML = "<div class='warnbox'>" + esc(d && d.error ? d.error : 'the strategies are not answering') + '</div>'; return; }
  var out = "<div class='hcards'>";
  d.strategies.forEach(function (h) {
    var meta = h.form === 'heuristic' ? h.direction + ' ' + h.metric + ' · weight ' + h.weight
             : h.form === 'limit' ? 'require ' + h.require + (h.soft ? ' · soft, penalty ' + h.penalty : ' · hard') + (h.when ? ' · when ' + h.when : '')
             : h.form === 'scored' ? [h.when ? 'when ' + h.when : '', h.bonus ? 'bonus ' + h.bonus : '', h.penalty ? 'penalty ' + h.penalty : ''].filter(Boolean).join(' · ') + ' · weight ' + h.weight
             : h.form === 'draft' ? 'draft - name, kind and prose only; /strategy infers the rest, not scored until then'
             : h.form === 'assumption' ? 'assumption - taken as given, read by the session, shown here, not scored'
             : h.form;
    var params = Object.keys(h.params || {}).map(function (k) { return k + '=' + h.params[k]; }).join(', ');
    var body = h.body.replace(/^#[^\n]*\n/, '').split(/\n\s*\n/).map(function (p) { return '<p>' + esc(p.replace(/\s+/g, ' ')) + '</p>'; }).join('');
    out += "<div class='hcard'><span class='kind " + h.kind + "'>" + h.kind + (h.form !== h.kind ? ' · ' + h.form : '') + '</span><b>' + esc(h.name) + "</b><div class='meta'>" + esc(meta) + (params ? ' · params ' + esc(params) : '') + '</div>' + body +
      "<div class='legend'>inference/strategies/" + esc(h.id) + '.md · ' + esc(h.category) + '</div></div>';
  });
  el('playbook').innerHTML = out + '</div>';
}

function showTab(name) {
  if (TABS.indexOf(name) < 0) name = TABS[0];   /* an unknown or stale tab (the old 'inf' / 'cur') lands on comps */
  document.querySelectorAll('nav.tabs button').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-tab') === name); });
  document.querySelectorAll('.panel').forEach(function (p) { p.classList.toggle('active', p.id === 'tab-' + name); });
  try { localStorage.setItem('owdb-tab', name); } catch (e) {}
}

fetch('/api/roster').then(function (r) { return r.json(); }).then(function (d) {
  ROSTER = d; ROSTER.byName = {};
  d.heroes.forEach(function (h) { ROSTER.byName[h.name] = h; });
  el('mapsel').innerHTML = "<option value=''>MAP UNKNOWN / ANY</option>" + d.maps.map(function (m) { return "<option value=\"" + esc(m.name) + "\">" + esc(m.name) + '</option>'; }).join('');
  var known = function (h) { return !!ROSTER.byName[h]; };   /* the roster is the only source of a name in state */
  st.red = st.red.filter(known); st.blue = st.blue.filter(known); st.bans = st.bans.filter(known);
  if (!d.maps.some(function (m) { return m.name === st.map; })) st.map = '';
  buildTeam('red'); buildTeam('blue'); buildBanPicker(); paint();
  var blz = (d.snapshots || []).filter(function (s) { return s.source === 'blizzard'; })[0];
  if (blz) el('captured').textContent = 'rates captured ' + blz.captured + ' (' + (blz.patch || 'unknown patch') + ')';
  if (d.newer_patches && d.newer_patches.length) { var w = el('vintage'); w.style.display = 'block';
    w.textContent = d.newer_patches.length + ' patch(es) shipped since the rates were captured (newest ' + d.newer_patches[0][0] + ') - rates are pre-patch; run pull_rates'; }
  el('mapsel').onchange = function () { st.map = this.value; save(); paint(); refresh(); };
  el('filter').oninput = renderFacts;
  el('clearbtn').onclick = function () { st = { map: '', red: [], blue: [], bans: [], side: '' }; save(); paint(); refresh(); };
  var chips = el('chips'); chips.innerHTML = SCOPES.map(function (s) { return "<button class='chip on' data-scope='" + s + "'>" + s + '</button>'; }).join('');
  chips.onclick = function (e) { var c = e.target.closest('.chip'); if (!c) return; var s = c.getAttribute('data-scope');
    scopeOn[s] = !scopeOn[s]; c.classList.toggle('on', scopeOn[s]); renderFacts(); };
  fetch('/api/strategies').then(function (r) { return r.json(); }).then(renderPlaybook);
  showTab((function () { try { return localStorage.getItem('owdb-tab'); } catch (e) { return null; } })());
  refresh();
});
