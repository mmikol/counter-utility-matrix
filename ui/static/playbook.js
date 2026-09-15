/* the playbook tab: the groups, the cards, the weight sliders and their store;
   loaded before board.js, which calls into it */
/* a heuristic's weight is the user's to set: a slider under its card, 1 to 10
   to the hundredth (1.02, 9.99), with a number box for the exact figure,
   starting at the weight the file infers; a setting rides with every board
   request (weight=id:value) and never touches the file. Only heuristics have
   weights to set - a scored constraint's stays its own. */
function weightRow(h) {
  var set = st.weights && st.weights.hasOwnProperty(h.id), v = set ? st.weights[h.id] : h.weight;
  return "<div class='wrow' data-id='" + esc(h.id) + "' data-inferred='" + h.weight + "'>" +
    "<span class='wlbl'>weight</span><input type='range' min='1' max='10' step='0.01' value='" + v + "' aria-label='weight of " + esc(h.name) + "'>" +
    "<input type='number' class='wval' min='1' max='10' step='0.01' value='" + v + "' aria-label='exact weight of " + esc(h.name) + "'>" +
    "<span class='wbreak'></span>" +
    "<span class='winf'>inferred " + h.weight + "</span>" +
    "<button class='wreset' " + (set ? '' : 'disabled') + ">reset</button>" +
    "<button class='wstore' " + (set ? '' : 'disabled') + " title='write this weight into the heuristic&#39;s file, through the tune tool'>store</button></div>";
}
/* store: the weight goes into the heuristic's file through the data layer's
   tune tool (validated, logged, mirrored); the file's weight is then the
   inferred default, so the browser's setting is dropped and the cards re-read */
function storeWeight(id, value, button) {
  if (value === null) return;
  button.disabled = true; button.textContent = 'storing…';
  fetch('/api/weight', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id, weight: value }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { flash('not stored: ' + d.error); button.disabled = false; button.textContent = 'store'; return; }
      flash(d.line || ('stored ' + id + ' at ' + value));
      if (st.weights) delete st.weights[id];
      save();
      fetch('/api/strategies').then(function (r) { return r.json(); }).then(renderPlaybook);
      refresh();
    })
    .catch(function (e) { flash('not stored: ' + e); button.disabled = false; button.textContent = 'store'; });
}
function clampWeight(x) { x = Math.round(+x * 100) / 100; return isNaN(x) ? null : Math.min(10, Math.max(1, x)); }
function setWeight(id, value, inferred) {
  if (!st.weights) st.weights = {};
  if (value === null || value === inferred) delete st.weights[id]; else st.weights[id] = value;
  save(); refresh();
}
/* the playbook, one group per kind in the equation's order - constraints,
   heuristics, assumptions - each headed with its count, an empty group saying
   so; a card's left edge carries its kind's colour */
var KINDS = [['constraint', 'constraints'], ['heuristic', 'heuristics'], ['assumption', 'assumptions']];
function renderPlaybook(d) {
  if (!d || !d.strategies) { el('playbook').innerHTML = "<div class='warnbox'>" + esc(d && d.error ? d.error : 'the strategies are not answering') + '</div>'; return; }
  /* anchors first: one per group with its count, so a long playbook is a click
     from any kind; each scrolls its group into view */
  var out = "<nav class='pbnav'>" + KINDS.map(function (k) {
    var n = d.strategies.filter(function (h) { return h.kind === k[0]; }).length;
    return "<button class='" + k[0] + "' data-group='pb-" + k[0] + "'>" + k[1] + " <span class='n'>" + n + '</span></button>';
  }).join('') + '</nav>';
  KINDS.forEach(function (k) {
    var these = d.strategies.filter(function (h) { return h.kind === k[0]; });
    out += "<section class='pbgroup " + k[0] + "' id='pb-" + k[0] + "'><h3>" + k[1] + " <span class='n'>" + these.length + '</span></h3>';
    out += these.length ? "<div class='hcards'>" + these.map(card).join('') + '</div>' : "<p class='legend none'>none in the playbook in force</p>";
    out += '</section>';
  });
  el('playbook').innerHTML = out;
  el('playbook').querySelectorAll('.pbnav button').forEach(function (b) {
    b.onclick = function () { el(b.getAttribute('data-group')).scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  });
  el('playbook').querySelectorAll('.wrow').forEach(function (row) {
    var id = row.getAttribute('data-id'), inferred = +row.getAttribute('data-inferred');
    var range = row.querySelector('input[type=range]'), val = row.querySelector('.wval'), reset = row.querySelector('.wreset'), store = row.querySelector('.wstore');
    var commit = function (x) { x = clampWeight(x); if (x === null) return; range.value = x; val.value = x; reset.disabled = store.disabled = x === inferred; setWeight(id, x, inferred); };
    range.oninput = function () { val.value = range.value; };
    range.onchange = function () { commit(range.value); };
    val.onchange = function () { commit(val.value); };
    reset.onclick = function () { range.value = inferred; val.value = inferred; reset.disabled = store.disabled = true; setWeight(id, null, inferred); };
    store.onclick = function () { storeWeight(id, clampWeight(val.value), store); };
  });
  function card(h) {
    var meta = h.form === 'heuristic' ? h.direction + ' ' + h.metric + ' · weight ' + h.weight
             : h.form === 'limit' ? 'require ' + h.require + (h.soft ? ' · soft, penalty ' + h.penalty : ' · hard') + (h.when ? ' · when ' + h.when : '')
             : h.form === 'scored' ? [h.when ? 'when ' + h.when : '', h.bonus ? 'bonus ' + h.bonus : '', h.penalty ? 'penalty ' + h.penalty : ''].filter(Boolean).join(' · ') + ' · weight ' + h.weight
             : h.form === 'draft' ? 'draft - name, kind and prose only; /strategy infers the rest, not scored until then'
             : h.form === 'assumption' ? 'assumption - taken as given, read by the session, shown here, not scored'
             : h.form;
    var params = Object.keys(h.params || {}).map(function (k) { return k + '=' + h.params[k]; }).join(', ');
    var body = h.body.replace(/^#[^\n]*\n/, '').split(/\n\s*\n/).map(function (p) { return '<p>' + esc(p.replace(/\s+/g, ' ')) + '</p>'; }).join('');
    return "<div class='hcard " + h.kind + "'><span class='kind " + h.kind + "'>" + h.kind + '</span><b>' + esc(h.name) + "</b><div class='meta'>" + esc(meta) + (params ? ' · params ' + esc(params) : '') + '</div>' + body +
      (h.form === 'heuristic' ? weightRow(h) : '') +
      "<div class='legend'>" + esc((d.playbook || 'inference/strategies') + '/' + h.id + '.md') + ' · ' + esc(h.category) + '</div></div>';
  }
}
