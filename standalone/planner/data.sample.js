/* data.sample.js — an invented seed, so a fresh clone can build a planner.
 *
 * Everything here is made up. The real one is not in this repository and
 * should not be put in one: a term timetable says where somebody is at every
 * hour of every weekday, which is not a thing to publish. Keep yours outside
 * the repo and point the builder at it:
 *
 *     python tools/build_planner.py --data ../planner-data.js --out ../september-planner.html
 *
 * With no --data the builder uses this file, and the result is a working
 * planner about a fictional term.
 *
 * The shape is the contract between this file and standalone/planner/app.js.
 * Every key has a fallback there, so leaving one out gives you an empty
 * section rather than a broken page -- but a seed missing WEEK_A while
 * TERM_FIRST is set will generate a term of empty weeks, which looks like a
 * bug and is not.
 */

window.PLANNER_DATA = (function () {

  /* ---- settings ---- */
  /* The countdown reads CD_START on CD_ANCHOR and drops by one a day. Pick
   * the anchor as the day you started counting, not today. */
  var CD_ANCHOR  = "2026-01-05";
  var CD_START   = 120;
  var PLAN_START = 7;              // first hour row in the day view (7 = 7 AM)
  var PLAN_END   = 21;             // last hour row, inclusive (21 = 9 PM)

  /* ---- countdowns ---- */
  /* Fixed targets only. Anything derivable from the calendar is worked out
   * at render time and does not belong here. */
  var COUNTDOWN_DATES = [
    { date: "2026-12-25", label: "Christmas Day" },
    { date: "2026-06-15", label: "Results day" }
  ];

  /* ---- fixtures ---- */
  /* A season of a team you follow. t/tz present means the kick-off is
   * confirmed; absent means a provisional 3pm slot, which the planner marks
   * TBC rather than pretending to know. */
  var SEED_KEY = "sept-planner.seed.sample-fixtures.v1";
  var COMPS = {
    pl: "Premier League", efl: "EFL Cup",
    fa: "FA Cup", ucl: "Champions League"
  };
  var FIXTURES = [
    { d: "2026-09-12", o: "Rovers United",  ha: "H", c: "pl" },
    { d: "2026-09-19", o: "Northgate",      ha: "A", c: "pl", t: "12:30" },
    { d: "2026-09-23", o: "Kingsbridge",    ha: "H", c: "efl", t: "19:45" },
    { d: "2026-10-03", o: "Ashford Town",   ha: "A", c: "pl" },
    { d: "2026-10-21", o: "Real Vallecano", ha: "H", c: "ucl", t: "20:00" },
    { d: "2026-11-07", o: "Westbury",       ha: "H", c: "pl", t: "15:00" }
  ];

  /* ---- term ---- */
  /* Three patterns, because a university timetable rarely repeats weekly.
   * WEEK_ONE is the first week as printed; WEEK_A and WEEK_B then alternate.
   * Each row is [weekday 0=Mon, start, end, module, kind, room]. */
  var TERM_KEY   = "sept-planner.seed.sample-term.v1";
  var TERM_FIRST = "2026-09-21";   // the Monday of week 1
  var TERM_SKIP  = ["2026-10-26"]; // reading week: generated, then skipped
  var TERM_END   = "2026-12-18";   // generate up to, not including

  var MODULE_COLOUR = {
    "MAT 1001": "green", "CMP 1002": "cyan",
    "CMP 1003": "violet", "PHY 1004": "amber"
  };

  var WEEK_ONE = [
    [0, "10:00", "11:00", "MAT 1001", "Lecture",   "Maths LT1"],
    [1, "13:00", "14:00", "CMP 1002", "Lecture",   "Computing 2.01"],
    [3, "09:00", "11:00", "CMP 1003", "Practical", "Lab A"]
  ];

  var WEEK_A = [
    [0, "10:00", "11:00", "MAT 1001", "Lecture",   "Maths LT1"],
    [1, "13:00", "14:00", "CMP 1002", "Lecture",   "Computing 2.01"],
    [2, "15:00", "16:00", "PHY 1004", "Seminar",   "Physics 1.12"],
    [3, "09:00", "11:00", "CMP 1003", "Practical", "Lab A"],
    [4, "11:00", "12:00", "MAT 1001", "Tutorial",  "Maths 2.04"]
  ];

  /* B is A without the Wednesday seminar, and the practical moves rooms --
   * the two things a fortnightly pattern is usually for. */
  var WEEK_B = [
    [0, "10:00", "11:00", "MAT 1001", "Lecture",   "Maths LT1"],
    [1, "13:00", "14:00", "CMP 1002", "Lecture",   "Computing 2.01"],
    [3, "09:00", "11:00", "CMP 1003", "Practical", "Lab B"],
    [4, "11:00", "12:00", "MAT 1001", "Tutorial",  "Maths 2.04"]
  ];

  /* ---- diary ---- */
  /* One-off events. Ids are fixed so re-seeding, or importing a backup that
   * already holds them, cannot produce two of anything. */
  var DIARY_KEY = "sept-planner.seed.sample-diary.v1";
  var DIARY = [
    { d: "2026-09-14", id: "sample-diary-1", t: "09:00", e: "17:00",
      x: "Registration", ty: "event" },
    { d: "2026-10-09", id: "sample-diary-2", t: "18:30", e: "22:00",
      x: "Society social — Students' Union", ty: "event" },
    { d: "2026-12-11", id: "sample-diary-3", t: "14:00", e: "16:00",
      x: "Coursework deadline", ty: "event" }
  ];

  /* Fixtures already played when this seed was written. The fixture list
   * cannot know that, so it is restored here. */
  var DONE_MATCHES = ["2026-09-12"];

  var SEED_TODOS = [
    { id: "sample-todo-1", text: "Register for modules", done: true },
    { id: "sample-todo-2", text: "Buy a rail card", done: false },
    { id: "sample-todo-3", text: "Set up the library account", done: false }
  ];

  var SEED_DAY_TODOS = [
    { d: "2026-09-21", id: "sample-daytodo-1",
      text: "Find Maths LT1 before the 10am", done: false }
  ];

  return {
    CD_ANCHOR: CD_ANCHOR, CD_START: CD_START,
    PLAN_START: PLAN_START, PLAN_END: PLAN_END,
    COUNTDOWN_DATES: COUNTDOWN_DATES,
    SEED_KEY: SEED_KEY, COMPS: COMPS, FIXTURES: FIXTURES,
    TERM_KEY: TERM_KEY, TERM_FIRST: TERM_FIRST, TERM_SKIP: TERM_SKIP,
    TERM_END: TERM_END, MODULE_COLOUR: MODULE_COLOUR,
    WEEK_ONE: WEEK_ONE, WEEK_A: WEEK_A, WEEK_B: WEEK_B,
    DIARY_KEY: DIARY_KEY, DIARY: DIARY, DONE_MATCHES: DONE_MATCHES,
    SEED_TODOS: SEED_TODOS, SEED_DAY_TODOS: SEED_DAY_TODOS
  };
}());
