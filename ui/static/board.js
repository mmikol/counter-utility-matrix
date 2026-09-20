/* the board: TEAM and BANS are set by the page before this loads */
var el = function (id) { return document.getElementById(id); };
var ROSTER = null, st = { map: '', red: [], blue: [], bans: [], side: '', weights: {} };
var SHAPES = null;   /* the (tank, damage, support) triples the playbook allows, from the board */
var ROLES = ['tank', 'damage', 'support'];
try { var saved = JSON.parse(localStorage.getItem('owdb-board2'));
      if (saved && saved.red && saved.blue) st = saved; } catch (e) {}
if (!st.bans) st.bans = [];
if (!st.side) st.side = '';
var TABS = ['comps', 'facts', 'playbook'];   /* the panels; the first is the default */
var bansOpen = false;                        /* the ban picker starts collapsed */

function currentMap() { return ROSTER ? ROSTER.maps.filter(function (x) { return x.name === st.map; })[0] : null; }

function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'); }
if (!st.weights || typeof st.weights !== 'object') st.weights = {};   /* a state saved before the sliders */
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
  if (h.status === 'announced') return soonTile(h);
  return "<div class='tile' data-team='" + team + "' data-h=\"" + esc(h.name) + "\" title=\"" + esc(h.name + ' - ' + h.subrole) + "\">" +
    portrait(h) + "<span class='nm'>" + esc(h.name) + '</span></div>';
}
/* an announced hero: the same tile in its role column, dimmed, tagged, with
   no data-h and no data-team - the click handler and the state never see it */
function soonTile(h) {
  return "<div class='tile soon' title=\"" + esc(h.name + ' - announced, not yet playable' + (h.release_date ? ' (releases ' + h.release_date + ')' : '') + ' - ' + h.subrole) + "\">" +
    (h.portrait ? portrait(h) : SILHOUETTE) + "<span class='tag'>coming soon</span><span class='nm'>" + esc(h.name) + '</span></div>';
}
function rosterHTML(team) {
  var cols = '';
  ROLES.forEach(function (role) {
    var icon = ROSTER.role_icons[role] ? "<img src='" + esc(ROSTER.role_icons[role]) + "' alt=''>" : '';
    cols += "<div class='rolecol'><h4>" + icon + role + "</h4><div class='grid'>";
    ROSTER.heroes.filter(function (h) { return h.role === role; }).forEach(function (h) { cols += tile(h, team); });
    cols += '</div></div>';
  });
  return cols;
}

function buildTeam(team) {
  var slots = '';
  for (var i = 0; i < TEAM; i++) slots += "<div class='slot' data-team='" + team + "' data-i='" + i + "'></div>";
  el(team + 'slots').innerHTML = slots;
  el(team + 'roster').innerHTML = rosterHTML(team);
}
function buildBanPicker() { el('banroster').innerHTML = rosterHTML('ban'); }

/* how many of a role a team may hold, given what it holds of the others: the
   most any legal shape seats. null when the board has not said what is legal */
function roleCap(team, role) {
  if (!SHAPES || !SHAPES.length) return null;
  var have = roleCounts(team), cap = -1;
  SHAPES.forEach(function (shape) {
    for (var i = 0; i < ROLES.length; i++) if (ROLES[i] !== role && shape[i] < have[ROLES[i]]) return;
    cap = Math.max(cap, shape[ROLES.indexOf(role)]);
  });
  return cap < 0 ? null : cap;
}
function roleCounts(team) {
  var have = { tank: 0, damage: 0, support: 0 };
  st[team].forEach(function (n) { var h = hero(n); if (h && have.hasOwnProperty(h.role)) have[h.role]++; });
  return have;
}
function toggle(team, name) {
  if (st.bans.indexOf(name) >= 0) { flash(name + ' is banned this match'); return; }
  var arr = st[team], at = arr.indexOf(name);
  if (at >= 0) arr.splice(at, 1);
  else if (arr.length >= TEAM) { flash(team + ' already has ' + TEAM); return; }
  else {
    var h = hero(name), cap = h ? roleCap(team, h.role) : null;
    if (cap !== null && roleCounts(team)[h.role] >= cap) {
      flash('the playbook allows at most ' + cap + ' ' + h.role + (cap === 1 ? '' : 's')); return;
    }
    arr.push(name);
  }
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
  } else { flash(BANS + ' bans already'); return; }
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
    var have = roleCounts(team), capped = {}, caps = {};
    ROLES.forEach(function (role) { caps[role] = roleCap(team, role); capped[role] = caps[role] !== null && have[role] >= caps[role]; });
    var tiles = el(team + 'roster').querySelectorAll('.tile[data-h]');   /* the announced card keeps its own class */
    for (var t = 0; t < tiles.length; t++) {
      var n = tiles[t].getAttribute('data-h'), hh = hero(n), on = st[team].indexOf(n) >= 0;
      tiles[t].className = 'tile' + (on ? ' on' : '') + (st[other].indexOf(n) >= 0 ? ' other' : '') +
        (st.bans.indexOf(n) >= 0 ? ' banned' : '') + (!on && hh && capped[hh.role] ? ' capped' : '');
    }
  });
  paintSuggestions();
  el('mapsel').value = st.map;
  var m = currentMap();
  var sided = !!(m && m.sided);
  if (!sided) st.side = '';
  el('mode').textContent = m ? m.mode + (m.style ? ' · rewards ' + m.style : '') +
    (sided ? (st.side ? ' · blue ' + (st.side === 'attack' ? 'attacks' : 'defends') : '') : ' · no sides') : 'map unknown';
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
  Object.keys(st.weights || {}).sort().forEach(function (id) { q.push('weight=' + encodeURIComponent(id + ':' + st.weights[id])); });
  return q.join('&');
}

var pending = null, seq = 0, FACTS = null, INF = null;
/* one switch for every figure the solver owns */
function solving(on) {
  document.body.classList.toggle('solving', !!on);
  ['bluescore', 'redscore'].forEach(function (id) {
    var node = el(id);
    if (!node) return;
    if (on) { node.dataset.was = node.textContent; node.textContent = '…'; }
    else if (node.textContent === '…' && node.dataset.was !== undefined) { node.textContent = node.dataset.was; }
  });
  if (on) {
    var mo = el('momentum');
    if (mo) mo.innerHTML = "<span class='lbl'>fight odds</span><span class='legend searching'>solving…</span>";
    var pl = el('plan');
    if (pl && !pl.dataset.held) { pl.dataset.held = '1'; pl.classList.add('waiting'); }
    ['blueslots', 'redslots'].forEach(function (id) {
      var s = el(id); if (s) s.classList.add('waiting');
    });
  } else {
    var pl2 = el('plan');
    if (pl2) { delete pl2.dataset.held; pl2.classList.remove('waiting'); }
    ['blueslots', 'redslots'].forEach(function (id) {
      var s = el(id); if (s) s.classList.remove('waiting');
    });
  }
}

function refresh() {
  clearTimeout(pending);
  pending = setTimeout(function () {
    var mine = ++seq, q = qs();
    fetch('/api/facts?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      if (d.error) { flash(d.error); return; }
      FACTS = d; renderFacts();
    }).catch(function () { flash('the database is not answering'); });
    /* the search is seconds of work, so everything it feeds says so until it
       lands: the two seats, the odds bar, the scores, the plan and the filled
       slots. Without this the board shows the last board's numbers while it
       thinks, which reads as an answer. */
    solving(true);
    el('inf-blue').innerHTML = "<p class='legend searching'>searching both seats…</p>";
    el('inf-red').innerHTML = "<p class='legend searching'>searching…</p>";
    fetch('/api/infer?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      solving(false);
      INF = d; renderInf();
    }).catch(function () {
      if (mine !== seq) return;
      solving(false);
      el('inf-blue').innerHTML = "<p class='legend'>inference is not answering</p>";
      el('inf-red').innerHTML = '';
    });
  }, 200);
}

var SCOPES = ['meta', 'bans', 'map', 'hero', 'team', 'matchup', 'playbook'];
var scopeOn = { meta: true, bans: true, map: true, hero: true, team: true, matchup: true, playbook: true };
function renderFacts() {
  if (!FACTS) return;
  var f = el('filter').value.toLowerCase(), out = '', last = null, shown = 0;
  FACTS.facts.forEach(function (x) {
    if (!scopeOn[x.scope]) return;
    if (f && (x.id + ' ' + x.key + ' ' + x.subject + ' ' + x.text).toLowerCase().indexOf(f) < 0) return;
    shown++;
    var head = x.scope === 'hero' ? (x.team + ' · ' + x.subject) : x.scope === 'team' ? (x.subject + ' team') : x.scope;
    if (x.scope === 'bans') head = 'bans';
    if (x.scope === 'playbook') head = 'the playbook\'s record · what it holds - not facts';
    if (head !== last) { out += "<tr class='h'><td colspan='3' class='head'>" + esc(head) + '</td></tr>'; last = head; }
    var cls = (x.team || '') + (/^(WARNING|CAUTION)/.test(x.text) ? ' warn' : '') + (x.source.indexOf('derived:') === 0 ? ' derived' : '');
    out += "<tr class='" + cls + "'><td class='tag'>[" + x.id + "]</td><td class='text'>" + esc(x.text) + "</td><td class='src'>" + esc(x.source) + '</td></tr>';
  });
  el('factbody').innerHTML = out || "<tr><td class='src'>nothing matches</td></tr>";
  var total = FACTS.facts.length;   /* the total lives in the panel, beside the filter */
  el('factsn').textContent = shown === total ? commas(total) + ' facts' : commas(shown) + ' of ' + commas(total) + ' facts';
}

/* the empty blue slots carry the solver's suggestions: the optimal six before
   any pick, then the best six that keeps the locked ones - a click locks one.
   The tile shows the hero alone; its reasons ride in the hover title and in
   the comps tab */
function paintSuggestions() {
  var slots = el('blueslots').children, d = INF;
  var src = !d || d.error ? null : (st.blue.length ? d.fill : d.blue);
  var open = src && src.picks ? src.picks.filter(function (p) { return !p.locked && st.blue.indexOf(p.hero) < 0; }) : [];
  for (var i = st.blue.length, k = 0; i < TEAM; i++) {
    var s = slots[i], p = open[k++];
    if (!p) continue;
    var h = hero(p.hero) || { name: p.hero, portrait: p.portrait };
    s.className = 'slot suggested'; s.setAttribute('data-h', p.hero); s.title = p.why;
    s.innerHTML = portrait(h) + "<span class='idx'>" + (i + 1) + "</span><span class='nm'>" + esc(p.hero) + '</span>';
  }
}

function showTab(name) {
  if (TABS.indexOf(name) < 0) name = TABS[0];   /* an unknown or stale saved tab lands on comps */
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
  if (d.newer_patches && d.newer_patches.length) { var w = el('vintage'); w.style.display = 'block';
    w.textContent = d.newer_patches.length + ' patch(es) since the rates were captured (newest ' + d.newer_patches[0][0] + ') - run pull_rates'; }
  el('mapsel').onchange = function () { st.map = this.value; save(); paint(); refresh(); };
  el('filter').oninput = renderFacts;
  var chips = el('chips'); chips.innerHTML = SCOPES.map(function (s) { return "<button class='chip on' data-scope='" + s + "'>" + s + '</button>'; }).join('');
  chips.onclick = function (e) { var c = e.target.closest('.chip'); if (!c) return; var s = c.getAttribute('data-scope');
    scopeOn[s] = !scopeOn[s]; c.classList.toggle('on', scopeOn[s]); renderFacts(); };
  fetch('/api/strategies').then(function (r) { return r.json(); }).then(renderPlaybook);
  showTab((function () { try { return localStorage.getItem('owdb-tab'); } catch (e) { return null; } })());
  el('clearall').onclick = function () {   /* back to nothing: map, side, bans, both teams - the weights stay */
    st = { map: '', red: [], blue: [], bans: [], side: '', weights: st.weights || {} }; save(); paint(); refresh();
  };
  refresh();
});
