/* the comps tab: the game plan, the fight odds, the two seats and the badges above
   the pickers; loaded before board.js, which calls into it */
/* the list under a comp: every strategy the playbook holds, one bar each -
   lit when it applied to this comp, greyed when it did not (its guard unmet,
   or nothing to read); headed by the count satisfied */
function bars(contribs) {
  var mx = 0.01, met = contribs.filter(function (c) { return c.applies !== false && c.ok !== false; }).length;
  contribs.forEach(function (c) { mx = Math.max(mx, Math.abs(c.weighted || 0)); });
  var out = "<h4 class='barshead'>strategies satisfied <span class='n'>" + met + ' of ' + contribs.length + "</span></h4><div class='bars'>";
  contribs.forEach(function (c) {
    var w = Math.abs(c.weighted || 0) / mx * 100;
    var detail = c.form === 'heuristic' ? (c.applies ? c.metric + ' = ' + (typeof c.raw === 'number' ? +c.raw.toFixed(2) : c.raw) + ' · norm ' + (+c.norm).toFixed(2) : 'not applicable here')
               : c.form === 'scored' ? (c.applies ? 'bonus ' + c.bonus + ' − penalty ' + c.penalty : 'condition not met')
               : (c.ok ? 'limit satisfied' : 'limit VIOLATED');
    out += "<div class='bar" + ((c.weighted || 0) < 0 ? ' neg' : '') + (c.applies === false ? ' off' : '') + "' title=\"" + esc(detail + (c.text ? ' - ' + c.text : '')) + "\"><span class='lbl'>" + esc(c.id) + (c.fact ? " <span class='ev'>" + c.fact + '</span>' : '') + "</span><span class='trk'><span class='fill' style='width:" + w.toFixed(1) + "%'></span></span><span class='val'>" + ((c.weighted || 0) >= 0 ? '+' : '') + (+(c.weighted || 0)).toFixed(2) + '</span></div>';
  });
  return out + '</div>';
}

/* what a current comp's figure means - the badge's tooltip: the 0-100 share
   (`normalized`) of its own seat's optimal; the raw sum is never shown */
function meaning(d) {
  var n = typeof d.normalized === 'number' ? Math.round(d.normalized) : null;
  if (n === null) return '';
  if (d.seat === 'red') return 'their picks reach ' + n + '% of their best counter to yours';
  return 'your picks reach ' + n + '% of the best six for this board';
}

/* the comps panel: the game plan, the fight odds strip above the boxes, the two
   seats side by side and the badge above each picker */
function renderInf() {
  var d = INF;
  if (!d || d.error) { el('inf-blue').innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; el('inf-red').innerHTML = ''; el('momentum').innerHTML = ''; el('plan').innerHTML = ''; el('bluescore').textContent = ''; el('redscore').textContent = ''; return; }
  var text = (d.plan || '').split('\n'), basis = text.length && text[text.length - 1].indexOf('Based on:') === 0 ? text.pop() : '';
  el('plan').innerHTML = "<span class='lbl'>game plan</span><div class='text'>" + text.map(esc).join('<br>') + '</div>' + (basis ? "<div class='basis'>" + esc(basis) + '</div>' : '');
  var mo = d.momentum || {};
  /* the strip is two bars, blue's and red's, empty until a seat has a figure.
     With both seats scored the bars are the odds - each share over the two
     shares' sum, a split of 100 - and the tooltip keeps the share; with one
     seat scored its bar is its share alone; a seat that cannot be scored
     reads the word, its reason in the badge's tooltip */
  var bar = function (side, value, res) {
    var odds = mo.odds ? mo.odds[side] : null;
    var word = res && res.blue && res.blue.length && res.scoring === false ? 'unscored'
             : odds !== null ? odds + '%'
             : typeof value === 'number' ? value + ' / 100' : '';
    var tip = typeof value === 'number' ? side + ' ' + value + ' / 100 of its optimal' : '';
    return "<span class='mbar " + side + "' title='" + esc(tip) + "'><span class='side'>" + side + "</span><span class='trk'><span class='fill' style='width:" +
      (odds !== null ? odds : typeof value === 'number' ? value : 0) + "%'></span></span><span class='val'>" + word + '</span></span>';
  };
  el('momentum').innerHTML = "<span class='lbl' title='each side\'s comp as a share of the best six it could field here'>fight odds</span>" +
    "<span class='mbars'>" + bar('blue', mo.blue, d.current) + bar('red', mo.red, d.red_current) + '</span>';
  /* neither seat carries a score: red's is what they are likely to field, from
     the map and the meta alone, and blue's is the reference every comp is
     measured against; the picks' scores are the badges above the pickers */
  renderResult(d.expected, el('inf-red'), 'red - most likely starting comp' + (d.map ? ' on ' + d.map : ''));
  renderResult(d.blue, el('inf-blue'), 'blue - optimal counter to current picks' + (d.side ? ', on ' + d.side : ''));
  /* the badge above each seat's picks and picker always carries a figure: the
     current comp's share while the seat holds picks, else the suggested six's -
     this seat's optimal, 100 by definition - or "unscored" with the reason */
  var figure = function (r) { return r.scoring === false ? 'unscored' : typeof r.normalized === 'number' ? Math.round(r.normalized) + ' / 100' : ''; };
  var badge = function (cur, optimal, who) {
    var held = cur && cur.blue && cur.blue.length, r = held ? cur : optimal;
    if (!r) return ['', ''];
    var why = r.scoring === false ? (r.unscored || '')
            : held ? meaning(cur)
            : 'no ' + who + ' picks yet: the suggested six is this seat\'s optimal, 100';
    return [figure(r), why];
  };
  var b = badge(d.current, d.blue, 'blue'), r = badge(d.red_current, d.red, 'red');
  el('bluescore').textContent = b[0]; el('bluescore').title = b[1];
  el('redscore').textContent = r[0]; el('redscore').title = r[1];
  if (d.shapes && d.shapes.length && JSON.stringify(d.shapes) !== JSON.stringify(SHAPES)) { SHAPES = d.shapes; paint(); return; }
  paintSuggestions();
}

/* a count with thousands separators: 14,101 candidates */
function commas(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
/* one seat: its title, the six as cards, the search's numbers, the strategies
   met and the alternatives - a seat is a reference, so it carries no score */
function renderResult(d, container, title) {
  if (!d || d.error) { container.innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>'; return; }
  var out = "<div class='inf-head'><h3>" + esc(title) + '</h3></div>';
  out += "<div class='comp'>";
  d.picks.forEach(function (p) {
    var h = hero(p.hero) || { name: p.hero, portrait: p.portrait };
    out += "<div class='card'><div class='pic'>" + portrait(h) + "<span class='role'>" + esc(p.role) + '</span>' +
      "</div><div class='body'><b>" + esc(p.hero) + "</b><div class='why'>" + esc(p.why) + '</div>' +
      p.evidence.map(function (id) { return "<span class='ev' title=\"" + esc(d.cited[id] || id) + "\">" + id + '</span>'; }).join('') + '</div></div>';
  });
  out += '</div>';
  /* the search's numbers - candidates, seconds, the lean - under the cards, above the strategies met */
  var meta = [d.considered ? commas(d.considered) + ' candidates' : '', d.seconds ? d.seconds + 's' : '',
              d.playstyle ? 'leans ' + d.playstyle : ''].filter(Boolean).join(' · ');
  if (meta) out += "<div class='legend meta'>" + meta + '</div>';
  out += d.contributions && d.contributions.length ? bars(d.contributions) : '';
  if (d.alternatives && d.alternatives.length) {
    out += "<div class='alts'><b>alternatives</b><ol>" +
      d.alternatives.map(function (a) { return '<li>' + esc(a.blue.join(', ')) + '</li>'; }).join('') + '</ol></div>';
  }
  container.innerHTML = out;
}
