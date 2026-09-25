/* the record tab: the board as a played map - the map, blue's side, the bans
   and both sixes - over the day it was played, a note and a button per
   result, blue's. Blue is the owner's team. A result posts the board to
   /api/match, which records it through the door's record_match; the server
   holds every rule, and the page only says what the board still lacks.
   READ_ONLY comes from the page shell, which renders the buttons disabled and
   says how to turn recording on. Loaded before board.js, whose paint() calls
   renderRecord on every change. */
var recorded = null;       /* the board the last result recorded, so one map is sent once */
var recordedLine = '';     /* what the door said when it recorded it */

function isoDay(d) {
  var two = function (n) { return (n < 10 ? '0' : '') + n; };
  return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate());
}
function boardKey() { return JSON.stringify([st.map, st.side, st.bans, st.blue, st.red]); }

/* what the board lacks before it is a played map: the map, blue's side on a
   sided map, and six a team */
function recordLacks() {
  var m = currentMap(), lacks = [];
  if (!m) lacks.push('the map');
  else if (m.sided && !st.side) lacks.push("blue's side");
  ['blue', 'red'].forEach(function (team) {
    if (st[team].length < TEAM) lacks.push(team + "'s six (" + st[team].length + ' of ' + TEAM + ')');
  });
  return lacks;
}

/* one line of the summary: a team's six in its colour, or the bans */
function recordRow(label, names, team) {
  return "<tr class='" + team + "'><td class='tag'>" + label + "</td><td class='text'>" +
    (names.length ? names.map(esc).join(', ') : '-') + '</td></tr>';
}

function renderRecord() {
  if (!el('recday').value) el('recday').value = isoDay(new Date());   /* the browser's today */
  var m = currentMap();
  var head = !m ? 'no map' : m.name + ' · ' + m.mode +
    (m.sided ? (st.side ? ' · blue ' + (st.side === 'attack' ? 'attacks' : 'defends') : ' · no side set') : '');
  el('recsum').innerHTML = '<h3>' + esc(head) + "</h3><table class='facts'><tbody>" +
    recordRow('blue', st.blue, 'blue') + recordRow('red', st.red, 'red') +
    recordRow('bans', st.bans, '') + '</tbody></table>';
  var lacks = recordLacks(), same = recorded === boardKey();
  var buttons = el('results').querySelectorAll('button');
  for (var i = 0; i < buttons.length; i++) buttons[i].disabled = READ_ONLY || lacks.length > 0 || same;
  if (READ_ONLY) return;
  el('recstatus').textContent = lacks.length ? 'still to set: ' + lacks.join(', ')
    : same ? recordedLine + ' - change the board, or clear all, to record the next map'
    : "press blue's result to record this map";
}

/* a result pressed: the board, the day and the note to /api/match. A refusal
   is the door's own words; the board stays as it was, to be fixed and sent */
function recordMatch(result) {
  if (READ_ONLY) return;
  var key = boardKey(), buttons = el('results').querySelectorAll('button');
  for (var i = 0; i < buttons.length; i++) buttons[i].disabled = true;
  el('recstatus').textContent = 'recording…';
  var body = { map: st.map, side: st.side, result: result, blue: st.blue, red: st.red, bans: st.bans,
               played_on: el('recday').value, note: el('recnote').value };
  fetch('/api/match', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { flash('not recorded: ' + d.error); renderRecord(); el('recstatus').textContent = 'not recorded: ' + d.error; return; }
      recorded = key; recordedLine = d.line; el('recnote').value = '';
      flash(d.line);
      renderRecord();
    })
    .catch(function (e) { flash('not recorded: ' + e); renderRecord(); });
}
