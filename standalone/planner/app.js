(function(){
  "use strict";

  /* The seed: one person's countdown, fixtures, term timetable, diary and
   * to-do list. None of it is in this file, and that is the point -- a
   * timetable says where somebody is every weekday, so it lives in a seed
   * file kept outside the repository and is inlined at build time.
   *
   * Every lookup has a fallback, so the engine runs against no seed at all
   * and simply shows an empty planner rather than throwing. */
  var SEED = (typeof PLANNER_DATA === "object" && PLANNER_DATA) || {};
  function seed(name, fallback) {
    return Object.prototype.hasOwnProperty.call(SEED, name)
      ? SEED[name] : fallback;
  }


  /* ===== settings — change these to retarget ===== */
  var CD_ANCHOR  = seed("CD_ANCHOR",  "2026-01-01");
  var CD_START   = seed("CD_START",   100);
  var PLAN_START = seed("PLAN_START", 5);
  var PLAN_END   = seed("PLAN_END",   22);
  /* ============================================== */

  /* Countdown boxes. Each one is a target the overlay counts the days to.
   * Anything derived from what is actually in the calendar is worked out at
   * render time; only fixed dates belong here. */
  var COUNTDOWN_DATES = seed("COUNTDOWN_DATES", []);

  var MONTHS  = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  var MSHORT  = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var DAYS    = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  var EV_KEY  = "sept-planner.events.v1";
  var TD_KEY  = "sept-planner.todos.v1";
  var DT_KEY  = "sept-planner.daytodos.v1";

  /* ---- storage (may throw in private mode / blocked site data) ---- */
  function load(key, fallback){
    try{
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    }catch(e){ return fallback; }
  }
  function save(key, value){
    try{ localStorage.setItem(key, JSON.stringify(value)); }catch(e){}
  }
  function obj(v){ return (v && typeof v === "object" && !(v instanceof Array)) ? v : {}; }

  var events   = obj(load(EV_KEY, {}));   // { date: [{id,time,title,type,done}] }
  var dayTodos = obj(load(DT_KEY, {}));   // { date: [{id,text,done}] }
  var todos    = load(TD_KEY, []);        // [{id,text,done}] — the general side list
  if (Object.prototype.toString.call(todos) !== "[object Array]") todos = [];

  var $ = function(id){ return document.getElementById(id); };
  var grid = $("grid");

  function pad(n){ return n < 10 ? "0" + n : "" + n; }
  function iso(y, m, d){ return y + "-" + pad(m + 1) + "-" + pad(d); }
  function esc(s){
    return String(s).replace(/[&<>"']/g, function(c){
      return { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c];
    });
  }
  function uid(){ return Math.random().toString(36).slice(2) + Date.now().toString(36); }

  // UTC-based so DST shifts can never add or drop a day
  function utc(isoStr){
    var p = isoStr.split("-");
    return Date.UTC(+p[0], +p[1] - 1, +p[2]);
  }
  function daysBetween(aISO, bISO){ return Math.round((utc(bISO) - utc(aISO)) / 86400000); }
  function addDays(isoStr, n){
    var d = new Date(utc(isoStr) + n * 86400000);
    return iso(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  }
  function pretty(isoStr){
    var p = isoStr.split("-");
    return MSHORT[+p[1] - 1] + " " + (+p[2]) + ", " + p[0];
  }
  function currentISO(){
    var n = new Date();
    return iso(n.getFullYear(), n.getMonth(), n.getDate());
  }
  function fmtTime(hhmm, tz, tbc){
    var p = hhmm.split(":");
    var h = parseInt(p[0], 10), mn = p[1];
    var ampm = h >= 12 ? "PM" : "AM";
    var h12 = h % 12; if (h12 === 0) h12 = 12;
    return h12 + ":" + mn + " " + ampm + (tz ? " " + tz : "") + (tbc ? "?" : "");
  }

  /* an event shows the colour you picked; anything older falls back to its type */
  function colorKey(e){
    return e.color ? "c-" + e.color : "m-" + e.type;
  }
  function fmtHour(h){
    var ampm = h >= 12 ? "PM" : "AM";
    var h12 = h % 12; if (h12 === 0) h12 = 12;
    return h12 + " " + ampm;
  }

  /* ---- clock arithmetic on "HH:MM" strings ---- */
  var HOUR_PX = 42;             // one hour of the day = 42px of timeline
  var MATCH_MINUTES = 120;      // every football match blocks out two hours
  var DEFAULT_MINUTES = 60;     // anything else defaults to one
  function toMin(hhmm){ var p = hhmm.split(":"); return (+p[0]) * 60 + (+p[1]); }
  function fromMin(m){
    if (m < 0) m = 0;
    if (m > 24 * 60 - 1) m = 24 * 60 - 1;
    return pad(Math.floor(m / 60)) + ":" + pad(m % 60);
  }
  function addMinutes(hhmm, n){ return fromMin(toMin(hhmm) + n); }
  function durationFor(type){ return type === "match" ? MATCH_MINUTES : DEFAULT_MINUTES; }

  /* "3:00 PM – 5:00 PM BST", or just the start if no end is recorded */
  function fmtSpan(e){
    if (!e.end) return fmtTime(e.time, e.tz, e.tbc);
    return fmtTime(e.time) + " – " + fmtTime(e.end, e.tz, e.tbc);
  }

  var todayISO = currentISO();

  /* ================= a season of fixtures, seeded once =================
     Each fixture is { d: date, o: opponent, ha: "H"|"A", c: competition },
     and COMPS maps the competition key to its full name.

     t/tz given  -> kick-off confirmed by the broadcaster.
     t/tz absent -> provisional 3pm slot, flagged TBC; the UK zone is derived
                    from the clock change rather than stored per fixture.

     Everything is editable once seeded, and the seed flag stops any of it
     coming back after you have changed or deleted it. Which fixtures these
     are is in the seed file, not here. */
  var SEED_KEY = seed("SEED_KEY", "sept-planner.seed.fixtures.v1");
  var COMPS    = seed("COMPS", {});
  var FIXTURES = seed("FIXTURES", []);

  // British Summer Time ran to 25 Oct 2026 and resumes 28 Mar 2027.
  function ukZone(dateISO){
    return (dateISO >= "2026-10-25" && dateISO < "2027-03-28") ? "GMT" : "BST";
  }

  function seedFixtures(){
    if (load(SEED_KEY, false)) return;          // already seeded once — never re-add
    FIXTURES.forEach(function(f){
      if (!events[f.d]) events[f.d] = [];
      // A fixture already on this date (e.g. from the earlier September-only seed)
      // is left alone — but gets the competition / home-away tags backfilled so the
      // colour modes work on it too.
      var existing = events[f.d].filter(function(x){ return x.type === "match"; });
      if (existing.length){
        existing.forEach(function(x){
          if (!x.comp) x.comp = f.c;
          if (!x.ha)   x.ha   = f.ha;
          if (!x.src)  x.src  = "cfc";
        });
        return;
      }
      var start = f.t || "15:00";
      events[f.d].push({
        id: uid(),
        time:  start,
        end:   addMinutes(start, MATCH_MINUTES),   // every match is a two-hour block
        title: f.o + " (" + f.ha + ") · " + (f.n || COMPS[f.c]),
        type:  "match",
        tz:    f.tz || ukZone(f.d),
        tbc:   !f.t,                            // provisional slot, not yet TV-selected
        comp:  f.c,
        ha:    f.ha,
        src:   "cfc",
        done:  false
      });
    });
    Object.keys(events).forEach(function(k){ if (!events[k].length) delete events[k]; });
    save(EV_KEY, events);
    save(SEED_KEY, true);
  }
  seedFixtures();

  /* ================= the term timetable, seeded once =================
     Three week patterns, because a university timetable rarely repeats
     weekly. WEEK_ONE is the first week as printed; after that WEEK_A and
     WEEK_B alternate, which is how a fortnightly class or a room that swaps
     between weeks is expressed.

     Where two classes overlap, both are kept. The timetable itself flags
     the clash, and resolving somebody's enrolment is not this file's
     business.

     TERM_SKIP lists weeks with no classes -- a reading week -- and TERM_END
     is the date generation stops at, exclusive. All four are in the seed.

     Ids are deterministic rather than random, so seeding twice, or importing
     a backup that already holds these, cannot produce two of anything. The
     seed flag is what makes a deletion stick -- the same bargain the fixture
     list above strikes. */
  var TERM_KEY      = seed("TERM_KEY", "sept-planner.seed.term.v1");
  var TERM_FIRST    = seed("TERM_FIRST", "");
  var TERM_SKIP     = seed("TERM_SKIP", []);
  var TERM_END      = seed("TERM_END", "");
  var MODULE_COLOUR = seed("MODULE_COLOUR", {});
  var WEEK_ONE      = seed("WEEK_ONE", []);
  var WEEK_A        = seed("WEEK_A", []);
  var WEEK_B        = seed("WEEK_B", []);

  function termId(date, row){
    return "term-" + date + "-" + row[1].replace(":", "") + "-" +
           (row[3] + "-" + row[5]).replace(/[^A-Za-z0-9]+/g, "");
  }

  function termWeeks(){
    var weeks = [], monday = TERM_FIRST, turn = 0;
    while (monday < TERM_END){
      if (TERM_SKIP.indexOf(monday) >= 0){ monday = addDays(monday, 7); continue; }
      if (monday === TERM_FIRST){
        weeks.push({ monday: monday, rows: WEEK_ONE });
      } else {
        weeks.push({ monday: monday, rows: (turn % 2 === 0) ? WEEK_A : WEEK_B });
        turn++;
      }
      monday = addDays(monday, 7);
    }
    return weeks;
  }

  function seedTimetable(){
    if (load(TERM_KEY, false)) return;

    termWeeks().forEach(function(week){
      week.rows.forEach(function(row){
        var date = addDays(week.monday, row[0]);
        if (date >= TERM_END) return;              // nothing on Christmas Day

        var id = termId(date, row);
        if (!events[date]) events[date] = [];
        for (var i = 0; i < events[date].length; i++){
          if (events[date][i].id === id) return;   // already there
        }
        events[date].push({
          id:    id,
          time:  row[1],
          end:   row[2],
          title: row[3] + " · " + row[4] + " — " + row[5],
          type:  "class",
          tz:    ukZone(date),
          color: MODULE_COLOUR[row[3]] || "cyan",
          module: row[3],
          room:  row[5],
          src:   "term",
          tbc:   false,
          done:  false
        });
      });
    });

    Object.keys(events).forEach(function(k){ if (!events[k].length) delete events[k]; });
    save(EV_KEY, events);
    save(TERM_KEY, true);
  }
  seedTimetable();

  /* ============ the diary and both to-do lists, seeded once ============
     Everything that was in the planner before this file learned to seed
     itself: orientation week, tutoring, the flights, the esports finals, the
     side list and the one day-task. The matches come from the fixture list
     above and the classes from the timetable, so neither appears here.

     The ids are the ones these events already had, not new ones. That is
     what makes importing a backup on top of a seeded planner a no-op rather
     than a way to end up with two of everything. */
  var DIARY_KEY      = seed("DIARY_KEY", "sept-planner.seed.diary.v1");
  var DIARY          = seed("DIARY", []);
  var DONE_MATCHES   = seed("DONE_MATCHES", []);
  var SEED_TODOS     = seed("SEED_TODOS", []);
  var SEED_DAY_TODOS = seed("SEED_DAY_TODOS", []);

  function seedDiary(){
    if (load(DIARY_KEY, false)) return;

    DIARY.forEach(function(f){
      if (!events[f.d]) events[f.d] = [];
      for (var i = 0; i < events[f.d].length; i++){
        if (events[f.d][i].id === f.id) return;      // already there
      }
      var row = { id: f.id, time: f.t, title: f.x, type: f.ty,
                  tz: f.tz, done: !!f.done, tbc: false, src: "diary" };
      if (f.e) row.end = f.e;
      if (f.c) row.color = f.c;
      events[f.d].push(row);
    });

    /* Two fixtures had already been played when this was last exported. The
       fixture list cannot know that, so it is restored here. */
    DONE_MATCHES.forEach(function(d){
      (events[d] || []).forEach(function(x){
        if (x.type === "match") x.done = true;
      });
    });

    /* The side list and the day tasks. Both are appended rather than
       replacing what is there, and both skip anything already present by
       id, so nothing anybody has added since is disturbed. */
    SEED_TODOS.forEach(function(t){
      for (var i = 0; i < todos.length; i++){ if (todos[i].id === t.id) return; }
      todos.push({ id: t.id, text: t.text, done: t.done });
    });

    SEED_DAY_TODOS.forEach(function(t){
      var list = dayTodos[t.d] || (dayTodos[t.d] = []);
      for (var i = 0; i < list.length; i++){ if (list[i].id === t.id) return; }
      list.push({ id: t.id, text: t.text, done: t.done });
    });

    Object.keys(events).forEach(function(k){ if (!events[k].length) delete events[k]; });
    save(EV_KEY, events);
    save(TD_KEY, todos);
    save(DT_KEY, dayTodos);
    save(DIARY_KEY, true);
  }
  seedDiary();


  /* Give any match already in storage its two-hour block. Idempotent, so it is
     safe to run on every load. */
  function migrateDurations(){
    var changed = false;
    Object.keys(events).forEach(function(d){
      events[d].forEach(function(x){
        if (!x.end && x.type === "match"){
          x.end = addMinutes(x.time, MATCH_MINUTES);
          changed = true;
        }
      });
    });
    if (changed) save(EV_KEY, events);
  }
  migrateDurations();

  // Open on September 2026 with nothing expanded.
  var view = { y: 2026, m: 8 };
  var selected = null;
  var editingId = null;   // id of the event currently loaded into the form
  var PALETTE = ["cyan","blue","violet","green","amber","orange","pink","red","slate"];
  var formColor = "cyan";  // colour the form will apply on Add / Save

  function dayEvents(date){
    var list = events[date] || [];
    return list.slice().sort(function(a, b){ return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
  }
  function dayTasks(date){
    var l = dayTodos[date];
    return (Object.prototype.toString.call(l) === "[object Array]") ? l : [];
  }

  /* ---------------- countdown ---------------- */
  function renderCountdown(){
    var elapsed   = daysBetween(CD_ANCHOR, todayISO);
    var remaining = CD_START - elapsed;
    if (remaining > CD_START) remaining = CD_START;   // before the anchor day
    if (remaining < 0) remaining = 0;                 // after it runs out

    var pct = ((CD_START - remaining) / CD_START) * 100;
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;

    $("cdNum").textContent = remaining;
    $("cdLabel").textContent = remaining === 0 ? "target reached" :
                               remaining === 1 ? "day remaining" : "days remaining";
    $("cdBar").style.width = pct.toFixed(1) + "%";
    $("cdSub").textContent = Math.max(0, Math.min(CD_START, elapsed)) + " of " + CD_START +
                             " elapsed · ends " + pretty(addDays(CD_ANCHOR, CD_START));
  }

  /* ---------------- the countdown overlay ---------------- */

  /* One box per day of the countdown — CD_START of them, from the anchor
   * onwards, so the overlay is the whole run laid out rather than a handful
   * of highlights. Each box carries the number the sidebar would have read on
   * that day, the date, and what is actually scheduled on it.
   *
   * Nothing here is configured. The contents of every box come from the
   * calendar, so seeding the timetable or adding one event changes the boxes
   * without touching this function. */
  function countdownDays(){
    /* CD_START + 1 boxes, not CD_START: the sidebar reads 121 on the anchor
     * and 0 on the last day, so both ends are days of the run and stopping at
     * 121 left the final one off. */
    var boxes = [], i;
    for (i = 0; i <= CD_START; i++){
      var date = addDays(CD_ANCHOR, i);
      var items = (events[date] || []).slice().sort(function(a, b){
        return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
      });
      boxes.push({
        date: date,
        remaining: CD_START - i,          // what the sidebar reads that day
        away: daysBetween(todayISO, date),
        items: items,
        tasks: dayTasks(date).length
      });
    }
    return boxes;
  }

  function renderCountdownBoxes(){
    var boxes = countdownDays(), withSomething = 0;

    $("cdBoxes").innerHTML = boxes.map(function(b){
      var state = b.away === 0 ? " now" : b.away < 0 ? " gone" : "";
      if (b.items.length || b.tasks) withSomething++;

      /* One dot per event, in its own colour: the fill that makes a busy day
       * legible at this size, where no title would fit. */
      var dots = b.items.map(function(e){
        return '<i class="cddot ' + colorKey(e) + '" title="' +
               esc(fmtSpan(e) + " — " + e.title) + '"></i>';
      }).join("");

      var first = b.items.length ? b.items[0].title
                : b.tasks ? b.tasks + (b.tasks === 1 ? " task" : " tasks")
                : "—";

      return '<div class="cdbox' + state + '">' +
               '<span class="n">' + b.remaining + '</span>' +
               '<span class="d">' + esc(shortDay(b.date)) + '</span>' +
               '<span class="dots">' + (dots || '<i class="cddot none"></i>') +
               '</span>' +
               '<span class="k" title="' + esc(summarise(b)) + '">' +
                 esc(first) + '</span>' +
             '</div>';
    }).join("");

    $("cdOverlayNote").textContent =
      boxes.length + " boxes, one for each day of the countdown — " +
      pretty(CD_ANCHOR) + " to " + pretty(addDays(CD_ANCHOR, CD_START)) +
      ". The big number is what the sidebar reads that day, and each bar is " +
      "one event in its own colour. " + withSomething + " of the " +
      boxes.length + " have something in the diary; today is outlined.";
  }

  /* "Mon Sep 21" — the label a box that small can carry. */
  function shortDay(isoStr){
    var d = new Date(utc(isoStr));
    return DAYS[d.getUTCDay()].slice(0, 3) + " " +
           MSHORT[d.getUTCMonth()] + " " + d.getUTCDate();
  }

  /* The whole day, for the box's tooltip — the detail that does not fit. */
  function summarise(b){
    if (!b.items.length && !b.tasks) return pretty(b.date) + " — nothing on";
    var lines = b.items.map(function(e){ return fmtSpan(e) + "  " + e.title; });
    if (b.tasks) lines.push(b.tasks + (b.tasks === 1 ? " task" : " tasks"));
    return pretty(b.date) + "\n" + lines.join("\n");
  }

  function openCountdowns(){
    renderCountdownBoxes();
    $("cdOverlay").hidden = false;
    $("cdClose").focus();
  }
  function closeCountdowns(){
    $("cdOverlay").hidden = true;
    $("cdOpen").focus();
  }

  /* ---------------- calendar ---------------- */
  function renderCalendar(){
    var first = new Date(view.y, view.m, 1);
    var lead = first.getDay();                              // blanks before the 1st
    var len  = new Date(view.y, view.m + 1, 0).getDate();    // days in month
    var cells = Math.ceil((lead + len) / 7) * 7;
    var html = "", i;

    for (i = 0; i < cells; i++){
      var dayNum = i - lead + 1;
      if (dayNum < 1 || dayNum > len){
        html += '<div class="day outside" aria-hidden="true"></div>';
        continue;
      }
      var date  = iso(view.y, view.m, dayNum);
      var evs   = dayEvents(date);
      var tasks = dayTasks(date);
      var open  = tasks.filter(function(t){ return !t.done; }).length;

      var cls = "day";
      if (date < todayISO) cls += " past";
      if (date === todayISO) cls += " today";
      if (date === selected) cls += " selected";

      var chips = "";
      for (var j = 0; j < Math.min(evs.length, 2); j++){
        var e = evs[j];
        chips += '<span class="chip' + (e.done ? " done" : "") + '">' +
                 '<span class="dot ' + colorKey(e) + '"></span>' +
                 '<span class="t">' + esc(fmtTime(e.time, e.tz, e.tbc)) + '</span>' +
                 '<span class="x">' + esc(e.title) + '</span></span>';
      }
      if (evs.length > 2) chips += '<span class="more">+' + (evs.length - 2) + ' more</span>';

      var marks = open ? '<span class="marks">' + open + " task" + (open === 1 ? "" : "s") + "</span>" : "";

      html += '<button type="button" class="' + cls + '" data-date="' + date + '"' +
              ' aria-expanded="' + (date === selected) + '"' +
              ' aria-label="' + DAYS[(lead + dayNum - 1) % 7] + ", " + MONTHS[view.m] + " " + dayNum +
              (date < todayISO ? ", past" : "") +
              ", " + evs.length + " event" + (evs.length === 1 ? "" : "s") +
              ", " + open + ' open task' + (open === 1 ? "" : "s") + '">' +
              '<span class="dnum"><span class="n">' + dayNum + "</span></span>" +
              '<span class="chips">' + chips + "</span>" + marks +
              "</button>";
    }

    grid.innerHTML = html;
    $("monthLabel").textContent = MONTHS[view.m] + " " + view.y;
  }

  /* colour swatches on the event form */
  function renderSwatches(){
    $("evColors").innerHTML = PALETTE.map(function(c){
      return '<button type="button" class="sw c-' + c + '" data-color="' + c + '"' +
             ' aria-pressed="' + (c === formColor) + '" aria-label="' + c + '" title="' + c + '"></button>';
    }).join("");
  }
  function setFormColor(c){ formColor = c; renderSwatches(); }

  /* ---------------- expanded day view ---------------- */
  function renderHours(){
    var winStart = PLAN_START * 60, winEnd = (PLAN_END + 1) * 60;
    var items = [], outside = 0, provisional = 0;

    // Provisional kick-offs (TBC) are left unmarked — only confirmed times take space.
    dayEvents(selected).forEach(function(e){
      if (e.tbc){ provisional++; return; }

      var s  = toMin(e.time);
      var en = e.end ? toMin(e.end) : s + durationFor(e.type);
      if (en <= s) en = s + durationFor(e.type);
      if (en <= winStart || s >= winEnd){ outside++; return; }

      items.push({ e: e, s: Math.max(s, winStart), en: Math.min(en, winEnd) });
    });

    items.sort(function(a, b){ return (a.s - b.s) || (b.en - a.en); });

    // Group anything that overlaps, then share the width between columns so
    // two things at the same time sit side by side instead of on top of each other.
    var clusters = [], cur = [], curEnd = -1;
    items.forEach(function(it){
      if (cur.length && it.s >= curEnd){ clusters.push(cur); cur = []; curEnd = -1; }
      cur.push(it);
      if (it.en > curEnd) curEnd = it.en;
    });
    if (cur.length) clusters.push(cur);

    clusters.forEach(function(cl){
      var colEnd = [];
      cl.forEach(function(it){
        var placed = false;
        for (var i = 0; i < colEnd.length; i++){
          if (colEnd[i] <= it.s){ it.col = i; colEnd[i] = it.en; placed = true; break; }
        }
        if (!placed){ it.col = colEnd.length; colEnd.push(it.en); }
      });
      cl.forEach(function(it){ it.cols = colEnd.length; });
    });

    var rows = "";
    for (var h = PLAN_START; h <= PLAN_END; h++){
      rows += '<div class="tlh" style="top:' + ((h - PLAN_START) * HOUR_PX) + "px;height:" + HOUR_PX + 'px">' +
              '<span class="tll">' + fmtHour(h) + "</span></div>";
    }

    var blocks = items.map(function(it){
      var e   = it.e;
      var top = (it.s - winStart) / 60 * HOUR_PX;      // exact minute offset
      var hgt = (it.en - it.s)   / 60 * HOUR_PX;       // exact duration
      var w   = 100 / it.cols;
      return '<button type="button" class="blk' + (e.done ? " done" : "") +
             (hgt < 30 ? " tight" : "") + '" data-hev="' + esc(e.id) + '"' +
             ' title="' + esc(fmtSpan(e) + " — " + e.title) + '"' +
             ' style="top:' + top.toFixed(1) + "px;height:" + Math.max(hgt, 14).toFixed(1) + "px;" +
             "left:" + (it.col * w).toFixed(3) + "%;width:" + w.toFixed(3) + '%">' +
             '<span class="strip ' + colorKey(e) + '"></span>' +
             '<span class="blkt">' + esc(fmtSpan(e)) + "</span>" +
             '<span class="blkx">' + esc(e.title) + "</span></button>";
    }).join("");

    $("hours").style.height = ((PLAN_END - PLAN_START + 1) * HOUR_PX) + "px";
    $("hours").innerHTML = rows + '<div class="tlarea" id="tlarea">' + blocks + "</div>";
    $("planHead").textContent = "Plan · " + fmtHour(PLAN_START) + " to " + fmtHour(PLAN_END);
    var notes = [];
    if (outside)     notes.push(outside + " event" + (outside === 1 ? "" : "s") + " outside these hours");
    if (provisional) notes.push(provisional + " fixture" + (provisional === 1 ? "" : "s") +
                                " not blocked out — kick-off still to be confirmed");
    $("planNote").textContent = notes.join(" · ");
    $("planNote").hidden = !notes.length;
  }

  function renderEvents(){
    var evs = dayEvents(selected);
    $("evList").innerHTML = evs.map(function(e){
      return '<li class="ev' + (e.done ? " done" : "") + (e.id === editingId ? " editing" : "") + '">' +
             '<input type="checkbox" data-evtoggle="' + esc(e.id) + '"' + (e.done ? " checked" : "") +
             ' title="Cross out once established" aria-label="Mark ' + esc(e.title) + ' as established">' +
             '<span class="dot ' + colorKey(e) + '"></span>' +
             '<span class="time">' + esc(fmtSpan(e)) + "</span>" +
             '<span class="name">' + esc(e.title) + "</span>" +
             '<button class="edit" data-edit="' + esc(e.id) + '" aria-label="Edit ' + esc(e.title) + '">edit</button>' +
             '<button class="del" data-del="' + esc(e.id) + '" aria-label="Delete ' + esc(e.title) + '">&times;</button></li>';
    }).join("");
    $("evEmpty").hidden = evs.length > 0;
  }

  /* load an existing event into the form so it can be rewritten in place */
  function startEdit(id){
    var match = (events[selected] || []).filter(function(x){ return x.id === id; })[0];
    if (!match) return;
    editingId = id;
    $("evTime").value  = match.time;
    $("evEnd").value   = match.end || addMinutes(match.time, durationFor(match.type));
    $("evTz").value    = match.tz || "";
    $("evType").value  = match.type;
    $("evTitle").value = match.title;
    setFormColor(match.color || "cyan");
    $("evSubmit").textContent = "Save";
    $("evCancel").hidden = false;
    renderEvents();
    $("evTitle").focus();
  }
  function cancelEdit(){
    editingId = null;
    $("evTitle").value = "";
    $("evSubmit").textContent = "Add";
    $("evCancel").hidden = true;
    evNote("");
  }

  function renderDayTasks(){
    var list = dayTasks(selected);
    $("dtList").innerHTML = list.map(function(t){
      return '<li class="todo' + (t.done ? " done" : "") + '">' +
             '<input type="checkbox" data-dttoggle="' + esc(t.id) + '"' + (t.done ? " checked" : "") +
             ' aria-label="' + esc(t.text) + '">' +
             '<span class="txt">' + esc(t.text) + "</span>" +
             '<button class="del" data-dtdrop="' + esc(t.id) + '" aria-label="Delete task">&times;</button></li>';
    }).join("");
    $("dtEmpty").hidden = list.length > 0;
  }

  function renderDayView(){
    cancelEdit();                 // a change of day always drops out of edit mode
    // Nothing clicked yet → the day view stays collapsed.
    if (!selected){ $("dayView").hidden = true; return; }
    $("dayView").hidden = false;

    var p = selected.split("-");
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    var tag = selected === todayISO ? "today" : selected < todayISO ? "past" : "";
    $("dvTitle").innerHTML = esc(DAYS[d.getDay()] + ", " + MONTHS[d.getMonth()] + " " + d.getDate()) +
                             (tag ? '<span>' + tag + "</span>" : "");
    renderHours();
    renderEvents();
    renderDayTasks();
  }

  /* ---------------- general side to-dos ---------------- */
  function renderTodos(){
    $("todoList").innerHTML = todos.map(function(t){
      return '<li class="todo' + (t.done ? " done" : "") + '">' +
             '<input type="checkbox" data-toggle="' + esc(t.id) + '"' + (t.done ? " checked" : "") +
             ' aria-label="' + esc(t.text) + '">' +
             '<span class="txt">' + esc(t.text) + "</span>" +
             '<button class="del" data-drop="' + esc(t.id) + '" aria-label="Delete task">&times;</button></li>';
    }).join("");

    var left = todos.filter(function(t){ return !t.done; }).length;
    $("todoCount").textContent = left + " left";
    $("todoEmpty").hidden = todos.length > 0;
    $("clearDone").hidden = todos.length === left;
  }

  function renderAll(){ renderCalendar(); renderDayView(); renderCountdown(); }

  /* ---------------- interactions ---------------- */
  grid.addEventListener("click", function(e){
    var cell = e.target.closest ? e.target.closest(".day[data-date]") : null;
    if (!cell) return;
    var date = cell.getAttribute("data-date");
    selected = (selected === date) ? null : date;   // clicking the same day collapses it again
    renderCalendar();
    renderDayView();
    if (selected && $("dayView").scrollIntoView){
      $("dayView").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });

  $("prevBtn").addEventListener("click", function(){ shift(-1); });
  $("nextBtn").addEventListener("click", function(){ shift(1); });
  function shift(n){
    var d = new Date(view.y, view.m + n, 1);
    view = { y: d.getFullYear(), m: d.getMonth() };
    selected = null;               // changing month collapses the day view
    renderCalendar();
    renderDayView();
  }
  $("todayBtn").addEventListener("click", function(){
    var p = todayISO.split("-");
    view = { y: +p[0], m: +p[1] - 1 };
    selected = todayISO;
    renderCalendar();
    renderDayView();
  });
  function evNote(text, bad){
    var el = $("evMsg");
    el.textContent = text;
    el.style.color = bad ? "var(--danger)" : "var(--text-faint)";
    el.hidden = !text;
  }

  /* keep the end time sensible: matches are always two hours, everything else one */
  function syncEnd(force){
    var start = $("evTime").value;
    if (!start) return;
    var end = $("evEnd").value;
    if (force || !end || toMin(end) <= toMin(start)){
      $("evEnd").value = addMinutes(start, durationFor($("evType").value));
    }
  }
  $("evTime").addEventListener("change", function(){ syncEnd(false); });
  $("evType").addEventListener("change", function(){ syncEnd($("evType").value === "match"); });

  $("evColors").addEventListener("click", function(e){
    var c = e.target.getAttribute && e.target.getAttribute("data-color");
    if (c) setFormColor(c);
  });

  $("dvClose").addEventListener("click", function(){
    selected = null;
    renderCalendar();
    renderDayView();
  });

  /* ---- the countdown overlay ---- */
  $("cdOpen").addEventListener("click", openCountdowns);
  $("cdClose").addEventListener("click", closeCountdowns);
  $("cdOverlay").addEventListener("click", function(e){
    if (e.target === this) closeCountdowns();   // a click on the backdrop only
  });
  document.addEventListener("keydown", function(e){
    if (e.key === "Escape" && !$("cdOverlay").hidden){ closeCountdowns(); return; }
    /* C opens it -- but not while something is being typed into, and not when
     * it is a browser shortcut being held down. */
    if ((e.key === "c" || e.key === "C") && !e.ctrlKey && !e.metaKey && !e.altKey){
      var tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if ($("cdOverlay").hidden) openCountdowns(); else closeCountdowns();
    }
  });

  $("hours").addEventListener("click", function(e){
    if (!e.target.closest) return;

    // an existing block opens in the form
    var btn = e.target.closest("[data-hev]");
    if (btn){ startEdit(btn.getAttribute("data-hev")); return; }

    // empty space pre-fills the form at the time you clicked, to the nearest 15 min
    var area = $("tlarea");
    if (!area || e.target !== area) return;
    var y = e.clientY - area.getBoundingClientRect().top;
    var mins = PLAN_START * 60 + Math.floor(y / HOUR_PX * 4) * 15;
    if (mins < PLAN_START * 60) mins = PLAN_START * 60;
    if (mins > (PLAN_END + 1) * 60 - 15) mins = (PLAN_END + 1) * 60 - 15;
    cancelEdit();
    $("evTime").value = fromMin(mins);
    syncEnd(true);
    $("evTitle").focus();
  });

  /* meetings & events */
  $("evForm").addEventListener("submit", function(e){
    e.preventDefault();
    if (!selected) return;
    var title = $("evTitle").value.trim();
    var time  = $("evTime").value;
    var end   = $("evEnd").value;
    if (!title || !time || !end) return;
    var type = $("evType").value, tz = $("evTz").value;

    if (toMin(end) <= toMin(time)){
      evNote("The end time has to be after the start time — nothing was saved.", true);
      return;
    }
    evNote("");

    if (editingId){                                   // replace the event in place
      (events[selected] || []).forEach(function(x){
        if (x.id === editingId){
          x.time = time; x.end = end; x.title = title; x.type = type; x.tz = tz;
          x.color = formColor;
          x.tbc = false;                        // you've set it, so it's no longer provisional
        }
      });
      cancelEdit();
    } else {                                          // add a new one
      if (!events[selected]) events[selected] = [];
      events[selected].push({ id: uid(), time: time, end: end, title: title, type: type,
                              tz: tz, color: formColor, done: false });
      $("evTitle").value = "";
    }
    save(EV_KEY, events);
    renderEvents();
    renderHours();          // keep the daily schedule in step
    renderCalendar();
    $("evTitle").focus();
  });

  $("evCancel").addEventListener("click", function(){ cancelEdit(); renderEvents(); });

  // cross out / un-cross a meeting once it has actually been established
  $("evList").addEventListener("change", function(e){
    var id = e.target.getAttribute && e.target.getAttribute("data-evtoggle");
    if (!id || !selected) return;
    (events[selected] || []).forEach(function(x){ if (x.id === id) x.done = e.target.checked; });
    save(EV_KEY, events);
    renderEvents();
    renderHours();
    renderCalendar();
  });

  $("evList").addEventListener("click", function(e){
    if (!selected || !e.target.getAttribute) return;

    var editId = e.target.getAttribute("data-edit");
    if (editId){ startEdit(editId); return; }

    var id = e.target.getAttribute("data-del");
    if (!id) return;
    if (id === editingId) cancelEdit();               // don't leave the form editing a deleted event
    events[selected] = (events[selected] || []).filter(function(x){ return x.id !== id; });
    if (!events[selected].length) delete events[selected];
    save(EV_KEY, events);
    renderEvents();
    renderHours();
    renderCalendar();
  });

  /* per-day to-dos */
  $("dtForm").addEventListener("submit", function(e){
    e.preventDefault();
    if (!selected) return;
    var text = $("dtText").value.trim();
    if (!text) return;
    if (!dayTodos[selected]) dayTodos[selected] = [];
    dayTodos[selected].push({ id: uid(), text: text, done: false });
    save(DT_KEY, dayTodos);
    $("dtText").value = "";
    renderDayTasks();
    renderCalendar();
    $("dtText").focus();
  });

  $("dtList").addEventListener("change", function(e){
    var id = e.target.getAttribute && e.target.getAttribute("data-dttoggle");
    if (!id || !selected) return;
    dayTasks(selected).forEach(function(t){ if (t.id === id) t.done = e.target.checked; });
    save(DT_KEY, dayTodos);
    renderDayTasks();
    renderCalendar();
  });

  $("dtList").addEventListener("click", function(e){
    var id = e.target.getAttribute && e.target.getAttribute("data-dtdrop");
    if (!id || !selected) return;
    dayTodos[selected] = dayTasks(selected).filter(function(t){ return t.id !== id; });
    if (!dayTodos[selected].length) delete dayTodos[selected];
    save(DT_KEY, dayTodos);
    renderDayTasks();
    renderCalendar();
  });

  /* general side to-dos */
  $("todoForm").addEventListener("submit", function(e){
    e.preventDefault();
    var text = $("todoText").value.trim();
    if (!text) return;
    todos.push({ id: uid(), text: text, done: false });
    save(TD_KEY, todos);
    $("todoText").value = "";
    renderTodos();
  });

  $("todoList").addEventListener("change", function(e){
    var id = e.target.getAttribute && e.target.getAttribute("data-toggle");
    if (!id) return;
    todos.forEach(function(t){ if (t.id === id) t.done = e.target.checked; });
    save(TD_KEY, todos);
    renderTodos();
  });

  $("todoList").addEventListener("click", function(e){
    var id = e.target.getAttribute && e.target.getAttribute("data-drop");
    if (!id) return;
    todos = todos.filter(function(t){ return t.id !== id; });
    save(TD_KEY, todos);
    renderTodos();
  });

  $("clearDone").addEventListener("click", function(){
    todos = todos.filter(function(t){ return !t.done; });
    save(TD_KEY, todos);
    renderTodos();
  });

  /* ---------------- export / import ---------------- */
  function countAll(){
    var n = 0, k;
    for (k in events)   if (events.hasOwnProperty(k))   n += events[k].length;
    for (k in dayTodos) if (dayTodos.hasOwnProperty(k)) n += dayTodos[k].length;
    return n + todos.length;
  }
  function msg(text, bad){
    var el = $("dataMsg");
    el.textContent = text;
    el.style.color = bad ? "var(--danger)" : "var(--text-faint)";
    el.hidden = false;
  }

  $("exportBtn").addEventListener("click", function(){
    var payload = {
      app: "september-planner",
      version: 1,
      exportedAt: new Date().toISOString(),
      events: events, dayTodos: dayTodos, todos: todos
    };
    try{
      var blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      var url  = URL.createObjectURL(blob);
      var a    = document.createElement("a");
      a.href = url;
      a.download = "planner-backup-" + currentISO() + ".json";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
      msg("Exported " + countAll() + " items to planner-backup-" + currentISO() + ".json");
    }catch(err){
      msg("Export failed: " + err.message, true);
    }
  });

  $("importBtn").addEventListener("click", function(){ $("importFile").click(); });

  $("importFile").addEventListener("change", function(){
    var file = this.files && this.files[0];
    this.value = "";                       // so the same file can be picked again
    if (!file) return;

    var reader = new FileReader();
    reader.onerror = function(){ msg("Couldn't read that file — nothing was changed.", true); };
    reader.onload = function(){
      var data;
      try{ data = JSON.parse(reader.result); }
      catch(err){ msg("That isn't valid JSON — nothing was changed.", true); return; }

      if (!data || typeof data !== "object" ||
          (!data.events && !data.dayTodos && !data.todos)){
        msg("That doesn't look like a planner backup — nothing was changed.", true);
        return;
      }
      if (!window.confirm("Replace everything in the planner with this backup?\n\n" +
                          "Your current events and both to-do lists will be " +
                          "overwritten. This cannot be undone.")){
        msg("Import cancelled — nothing was changed.");
        return;
      }

      events   = obj(data.events);
      dayTodos = obj(data.dayTodos);
      todos    = (Object.prototype.toString.call(data.todos) === "[object Array]") ? data.todos : [];
      save(EV_KEY, events); save(DT_KEY, dayTodos); save(TD_KEY, todos);

      selected = null;
      renderAll();
      renderTodos();
      msg("Imported " + countAll() + " items" + (data.exportedAt ? " from " + data.exportedAt.slice(0, 10) : "") + ".");
    };
    reader.readAsText(file);
  });

  // If the page is left open across midnight, roll the greying and the counter over.
  setInterval(function(){
    var now = currentISO();
    if (now !== todayISO){ todayISO = now; renderAll(); }
  }, 60000);

  renderSwatches();
  renderAll();
  renderTodos();
})();
