/* the comps tab: the game plan, the fight odds, the two seats and the badges above
   the pickers; loaded before board.js, which calls into it */
/* the list under a comp: every strategy the playbook holds, one bar each - lit
   when it applied to this comp, greyed when it did not (its guard unmet, or
   nothing to read). Split into met and unmet, each its own scrolling pane with
   a filter, because the playbook is 244 rules and a page that lists them all at
   once buries the board. Sorted by name inside a pane: a rule is looked up by
   the name it is known by, not by where the catalog happens to put it. */
var BARS_SEQ = 0;

/* three ways a rule can end a board: it never read, it read and charged, or it
   read and was satisfied. The middle one is what a comp is paying for and had
   nowhere to show before. */
function verdictOf(c) {
  if (c.applies === false) return 'unread';
  if (c.ok === false || (c.weighted || 0) < -1e-9) return 'costing';
  return 'met';
}

/* one sentence saying why a rule paid or did not: a rule that read nothing names
   the guard that stopped it, so an unlit bar is never mistaken for a rule the
   board quietly ignored */
function why(c) {
  var n = function (x) { return typeof x === 'number' ? +x.toFixed(2) : x; };
  if (c.form === 'limit') return c.ok ? 'A hard limit. This six keeps it.'
                                      : 'A hard limit. This six breaks it.';
  if (!c.applies) {
    return c.when ? 'Never read. Its guard (' + c.when + ') does not hold here.'
                  : 'Never read. Nothing on this board gives it a number.';
  }
  if (c.form === 'scored') {
    var net = (c.bonus || 0) - (c.penalty || 0);
    return net > 0 ? 'Paid ' + n(c.weighted) + ': bonus ' + n(c.bonus) + ' over penalty ' + n(c.penalty) + '.'
         : net < 0 ? 'Charged ' + n(c.weighted) + ': penalty ' + n(c.penalty) + ' over bonus ' + n(c.bonus) + '.'
                   : 'Read. Bonus and penalty cancelled.';
  }
  var pos = Math.round((c.norm || 0) * 100);
  var where = c.spread === false ? 'the sample never moved this metric, so it reads as the middle'
            : pos >= 100 ? 'the top of the reference range, where more stops paying'
            : pos <= 0 ? 'the bottom of the reference range'
            : pos + '% up the reference range';
  if (c.need) {
    return (c.weighted || 0) < -1e-9
      ? 'A need this six meets only in part: ' + c.metric + ' = ' + n(c.raw) + ', ' + where + '. Costs ' + n(c.weighted) + '.'
      : 'A need this six meets in full: ' + c.metric + ' = ' + n(c.raw) + '. Costs nothing.';
  }
  return c.metric + ' = ' + n(c.raw) + ', ' + where + '. Worth ' + n(c.weighted) + '.';
}

function barRow(c, mx) {
  var w = Math.abs(c.weighted || 0) / mx * 100;
  var detail = why(c);
  if (c.confidence) detail += ' Scaled by ' + c.confidence + (typeof c.confidence_raw === 'number' ? ' = ' + (+c.confidence_raw).toFixed(2) : '') + '.';
  return "<div class='bar" + ((c.weighted || 0) < 0 ? ' neg' : '') + (c.applies === false ? ' off' : '') +
    "' data-id='" + esc(c.id) + "' title=\"" + esc(detail + (c.text ? '\n' + c.text : '')) + "\"><span class='lbl'>" +
    esc(c.id) + (c.fact ? " <span class='ev'>" + c.fact + '</span>' : '') +
    "</span><span class='trk'><span class='fill' style='width:" + w.toFixed(1) + "%'></span></span><span class='val'>" +
    ((c.weighted || 0) >= 0 ? '+' : '') + (+(c.weighted || 0)).toFixed(2) + '</span></div>';
}

function bars(contribs) {
  var mx = 0.01;
  contribs.forEach(function (c) { mx = Math.max(mx, Math.abs(c.weighted || 0)); });
  var byName = function (a, b) { return a.id < b.id ? -1 : a.id > b.id ? 1 : 0; };
  var group = { met: [], costing: [], unread: [] };
  contribs.forEach(function (c) { group[verdictOf(c)].push(c); });
  Object.keys(group).forEach(function (k) { group[k].sort(byName); });
  var cost = group.costing.reduce(function (s, c) { return s + (c.weighted || 0); }, 0);
  var id = 'bars' + (++BARS_SEQ);
  var pane = function (key) {
    return "<div class='barpane' data-pane='" + key + "'" + (key === 'met' ? '' : ' hidden') + '>' +
      (group[key].length ? group[key].map(function (c) { return barRow(c, mx); }).join('')
                         : "<p class='legend none'>none</p>") + '</div>';
  };
  var tab = function (key, label, extra) {
    return "<button" + (key === 'met' ? " class='on'" : '') + " data-pane='" + key + "'>" + label +
      " <span class='n'>" + group[key].length + '</span>' + (extra || '') + '</button>';
  };
  return "<div class='barsbox' id='" + id + "'>" +
    "<div class='barstabs'>" +
      tab('met', 'satisfied') +
      tab('costing', 'costing', cost ? " <span class='cost'>" + cost.toFixed(2) + '</span>' : '') +
      tab('unread', 'did not read') +
      "<input class='barfind' type='search' placeholder='filter " + contribs.length + " strategies'" +
      " aria-label='filter the strategies'>" +
    '</div>' +
    "<div class='bars'>" + pane('met') + pane('costing') + pane('unread') + '</div>' +
    "<p class='legend barcount'></p></div>";
}

/* the tabs and the filter, bound after the panel is written */
function wireBars(root) {
  (root || document).querySelectorAll('.barsbox').forEach(function (box) {
    if (box.dataset.wired) return;
    box.dataset.wired = '1';
    var find = box.querySelector('.barfind'), count = box.querySelector('.barcount');
    var show = function (key) {
      box.querySelectorAll('.barstabs button').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-pane') === key);
      });
      box.querySelectorAll('.barpane').forEach(function (p) {
        p.hidden = p.getAttribute('data-pane') !== key;
      });
      filter();
    };
    var filter = function () {
      var q = (find.value || '').trim().toLowerCase();
      var pane = box.querySelector('.barpane:not([hidden])');
      if (!pane) return;
      var shown = 0, rows = pane.querySelectorAll('.bar');
      rows.forEach(function (row) {
        var hit = !q || (row.getAttribute('data-id') || '').indexOf(q) >= 0
                     || (row.getAttribute('title') || '').toLowerCase().indexOf(q) >= 0;
        row.hidden = !hit;
        if (hit) shown++;
      });
      count.textContent = q ? shown + ' of ' + rows.length + ' match ' + q : '';
    };
    box.querySelectorAll('.barstabs button').forEach(function (b) {
      b.onclick = function () { show(b.getAttribute('data-pane')); };
    });
    find.oninput = filter;
  });
}

/* the comps panel: the game plan, the fight odds strip above the boxes, the two
   seats side by side and the badge above each picker */
function renderInf() {
  var d = INF;
  if (!d || d.error) {
    el('inf-blue').innerHTML = "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>';
    el('inf-red').innerHTML = ''; el('momentum').innerHTML = ''; el('plan').innerHTML = '';
    ['bluescore', 'redscore'].forEach(function (id) { el(id).textContent = ''; el(id).title = ''; });
    paint();                              /* the last board's suggestions go with it */
    return;
  }
  var text = (d.plan || '').split('\n'), basis = text.length && text[text.length - 1].indexOf('Based on:') === 0 ? text.pop() : '';
  el('plan').innerHTML = "<span class='lbl'>game plan</span><div class='text'>" + text.map(esc).join('<br>') + '</div>' + (basis ? "<div class='basis'>" + esc(basis) + '</div>' : '');
  var mo = d.momentum;                  /* every board carries it, the badges included */
  /* the strip is two bars, blue's and red's. With both seats scored the bars
     are the odds - each share over the two shares' sum, a split of 100 - and
     the tooltip keeps the share; with one seat scored its bar is its share
     alone; a seat that cannot be scored reads the word, picks or not, its
     reason in the tooltip. While neither bar has a figure the engine's
     verdict says why under them */
  var bar = function (side, value, res) {
    var odds = mo.odds ? mo.odds[side] : null, unscored = !!res && res.scoring === false;
    var word = unscored ? 'unscored'
             : odds !== null ? odds + '%'
             : typeof value === 'number' ? value + ' / 100' : '';
    var tip = unscored ? res.unscored || ''
            : typeof value === 'number' ? side + ' ' + value + ' / 100 of its optimal' : '';
    return "<span class='mbar " + side + "' title='" + esc(tip) + "'><span class='side'>" + side + "</span><span class='trk'><span class='fill' style='width:" +
      (odds !== null ? odds : typeof value === 'number' ? value : 0) + "%'></span></span><span class='val'>" + word + '</span></span>';
  };
  var figureless = typeof mo.blue !== 'number' && typeof mo.red !== 'number';
  el('momentum').innerHTML = "<span class='lbl' title='each side&#39;s comp as a share of the best six it could field here'>fight odds</span>" +
    "<span class='mbars'>" + bar('blue', mo.blue, d.current) + bar('red', mo.red, d.red_current) + '</span>' +
    (figureless && mo.verdict ? "<span class='verdict'>" + esc(mo.verdict) + '</span>' : '');
  /* neither seat carries a score. Red's is what they are likely to field, from
     the map and the meta alone. Blue's shows the six the plan describes - the
     fill around one to five picks, the picks themselves at six - above the
     optimal, which blue's own picks never constrain; before any pick, the
     optimal alone. The picks' scores are the badges above the pickers */
  renderResult(d.expected, el('inf-red'), 'red - most likely starting comp' + (d.map ? ' on ' + d.map : ''));
  var held = d.current && d.current.blue ? d.current.blue.length : 0;
  var revealed = d.red_current && d.red_current.blue ? d.red_current.blue.length : 0;
  var ours = d.fill ? resultHTML(d.fill, 'blue - your picks, the rest filled')
           : held >= TEAM ? resultHTML(d.current, 'blue - your six') : '';
  el('inf-blue').innerHTML = ours + resultHTML(d.blue, 'blue - optimal vs red\'s ' + (revealed ? 'picks' : 'likely six') + (d.side ? ', on ' + d.side : ''));
  wireBars(el('inf-blue'));
  /* the badge above each picker is the engine's (momentum.badges): its
     label, and on hover what the figure is a share of */
  el('bluescore').textContent = mo.badges.blue.label; el('bluescore').title = mo.badges.blue.tip;
  el('redscore').textContent = mo.badges.red.label; el('redscore').title = mo.badges.red.tip;
  if (d.shapes && d.shapes.length) SHAPES = d.shapes;   /* what the roster dims */
  paint();                    /* the dimmed tiles, the suggestions and each filled slot's reason */
}

/* a count with thousands separators: 14,101 candidates */
function commas(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
/* one seat's six in its container - a seat is a reference, so it carries no score */
function renderResult(d, container, title) {
  container.innerHTML = resultHTML(d, title);
  wireBars(container);          // the tabs and the filter live on the new nodes
}
/* a six: its title, the six as cards, the search's numbers, the strategies
   met and the alternatives */
function resultHTML(d, title) {
  if (!d || d.error) return "<div class='warnbox'>" + esc(d ? d.error : 'no result') + '</div>';
  var out = "<div class='inf-six'><div class='inf-head'><h3>" + esc(title) + '</h3></div>';
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
  return out + '</div>';
}
