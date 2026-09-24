/* data.blank.js — an empty seed: the calendar with nothing in it.
 *
 * data.sample.js builds a planner about a fictional term, which is useful for
 * seeing what the thing does and useless as a starting point: you would have
 * to delete somebody else's lectures before adding your own. This is the
 * other one. No term, no diary, no fixtures, no to-dos, no countdowns.
 * Nothing to clear out, and nothing about anybody.
 *
 *     python tools/build_planner.py --blank --out calendar.html
 *
 * Keeping it as a real seed file rather than passing nothing matters for two
 * reasons. The engine falls back per key, so an absent seed and an empty one
 * render the same today -- but only the file records that empty was the
 * intention, so a later key with a non-empty default cannot quietly seed this
 * build. And it gives the build something to assert against: a test reads
 * this file and fails if anything in it stops being empty.
 *
 * What is deliberately NOT empty is the pair of view bounds below. They are
 * how tall the day grid is drawn, not content -- zero them and the day view
 * collapses to nothing, which reads as a broken page rather than an empty
 * calendar. The shape is otherwise exactly data.sample.js's, because that is
 * the contract with app.js.
 */

window.PLANNER_DATA = (function () {

  /* The only non-empty values here: the first and last hour row of the day
   * view. A blank calendar still has to be a calendar. */
  var PLAN_START = 7;              // 7 AM
  var PLAN_END   = 21;             // 9 PM, inclusive

  /* Seed keys are versioned per seed so a blank build and a sample build do
   * not read each other's stored state out of localStorage. */
  var SEED_KEY  = "sept-planner.seed.blank.v1";
  var TERM_KEY  = "sept-planner.seed.blank-term.v1";
  var DIARY_KEY = "sept-planner.seed.blank-diary.v1";

  return {
    /* No countdown: CD_START of 0 on no anchor is not "zero days to go",
     * it is no countdown at all, which is what an empty calendar has. */
    CD_ANCHOR: "", CD_START: 0,
    COUNTDOWN_DATES: [],

    PLAN_START: PLAN_START, PLAN_END: PLAN_END,

    /* No fixtures, and no competition labels to name them with. */
    SEED_KEY: SEED_KEY, COMPS: {}, FIXTURES: [], DONE_MATCHES: [],

    /* No term. TERM_FIRST is empty on purpose: set it with no WEEK_A and the
     * planner generates a run of empty weeks, which looks like a bug. Empty
     * generates no term at all, which is the honest rendering of "nothing
     * scheduled yet". */
    TERM_KEY: TERM_KEY, TERM_FIRST: "", TERM_SKIP: [], TERM_END: "",
    MODULE_COLOUR: {}, WEEK_ONE: [], WEEK_A: [], WEEK_B: [],

    /* No diary entries, no to-dos, no per-day to-dos. */
    DIARY_KEY: DIARY_KEY, DIARY: [],
    SEED_TODOS: [], SEED_DAY_TODOS: []
  };
}());
