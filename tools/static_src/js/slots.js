/* domain/calendar_logic.py, ported to the browser.
 *
 * Generated builds copy this file into docs/app/js/ unchanged. It is the
 * only part of Almanac that runs without a server, because it is the only
 * part that is pure computation: recurring weekly hours, minus one-off
 * blocks, minus confirmed bookings, tiled into bookable slots. No account,
 * no database, no email, no background thread.
 *
 * tools/build_static.py runs this file and domain/calendar_logic.py against
 * the same scenarios in a real browser before it publishes anything, and
 * refuses to write on a single disagreement. So the structure below is
 * deliberately a transcription rather than an improvement: same functions,
 * same order, same names, same defensive branches. Where the two languages
 * genuinely cannot agree it is written down here rather than smoothed over.
 *
 * ---------------------------------------------------------------------
 * The rows
 * ---------------------------------------------------------------------
 * The Python reads three tables through db.query(). This takes the same
 * rows as arrays, in snake_case, exactly as the tables hold them:
 *
 *   data.availability   { provider_id, day_of_week, start_time, end_time,
 *                         slot_minutes }   day_of_week is Sunday = 0
 *   data.blocked_slots  { provider_id, date, start_time, end_time }
 *                         both times null = the whole day off
 *   data.appointments   { provider_id, date, start_time, end_time, status }
 *
 * The three little query functions below are the WHERE clauses, restated.
 * A filter in the wrong place here is exactly the kind of thing the build
 * check exists to catch, so they are kept one-to-one with the SQL.
 *
 * ---------------------------------------------------------------------
 * Where the port cannot follow the original
 * ---------------------------------------------------------------------
 * Three, all of them about parsing, all of them excluded from the compared
 * matrix in tools/build_static.py rather than quietly claimed:
 *
 *   * **non-ASCII digits.** Python's int() accepts every Unicode decimal, so
 *     int('٩') is 9. A JavaScript port of that is a different program.
 *   * **non-ASCII whitespace around a number.** int(' 9 ') is 9 in Python
 *     and int(' 9') is too. This trims ASCII whitespace only.
 *   * **the wording of an error.** Both sides refuse '25:ab' and an
 *     unparseable date, but one raises Python's ValueError with Python's
 *     sentence in it and the other throws from here. The build compares
 *     *that* both refused, and says so; it does not compare the text,
 *     because no wording would ever make those the same string.
 *
 * Everything else -- every slot, every boundary, every defensive branch --
 * is compared exactly.
 */
var AlmanacSlots = (function () {
  'use strict';

  var MINUTES_IN_A_DAY = 24 * 60;

  /* The two things _to_minutes can raise in Python are AttributeError (it
   * was not a string) and ValueError (it was not a time). Both are caught
   * at the same two places and nowhere else, so one class here stands for
   * both and is caught at the same two places. */
  function TimeError(message) {
    this.name = 'TimeError';
    this.message = message;
  }
  TimeError.prototype = Object.create(Error.prototype);
  TimeError.prototype.constructor = TimeError;

  function DateError(message) {
    this.name = 'DateError';
    this.message = message;
  }
  DateError.prototype = Object.create(Error.prototype);
  DateError.prototype.constructor = DateError;

  /* int(), for the subset both languages agree on: optional ASCII
   * whitespace, an optional sign, ASCII digits. See the header for the two
   * things this deliberately does not accept. */
  function toInt(text, whole) {
    if (typeof text !== 'string') {
      throw new TimeError(whole + ' is not a time');
    }
    if (!/^[ \t\n\r\f\v]*[+-]?[0-9]+[ \t\n\r\f\v]*$/.test(text)) {
      throw new TimeError(whole + ' is not a time');
    }
    return parseInt(text, 10);
  }

  function toMinutes(hhmm) {
    /* h, m = hhmm.split(":") -- which is an AttributeError on a non-string
     * and a ValueError on anything that is not exactly two pieces. */
    if (typeof hhmm !== 'string') {
      throw new TimeError(String(hhmm) + ' is not a time');
    }
    var parts = hhmm.split(':');
    if (parts.length !== 2) {
      throw new TimeError(hhmm + ' is not a time');
    }
    return toInt(parts[0], hhmm) * 60 + toInt(parts[1], hhmm);
  }

  /* f"{m // 60:02d}:{m % 60:02d}", including for negative totals, where
   * Python floors the division and takes a non-negative remainder, and
   * where the 02 pads the sign as part of the width: -1 formats as "-1",
   * not "-01". slot_starts_for can reach this with a negative duration. */
  function toHhmm(total) {
    var hours = Math.floor(total / 60);
    var minutes = ((total % 60) + 60) % 60;
    return pad2(hours) + ':' + pad2(minutes);
  }

  function pad2(value) {
    var digits = String(Math.abs(value));
    var width = value < 0 ? 1 : 2;
    while (digits.length < width) {
      digits = '0' + digits;
    }
    return (value < 0 ? '-' : '') + digits;
  }

  /* datetime.strptime(date_str, "%Y-%m-%d").date(), as far as a calendar
   * date goes: four-digit year, month and day that may or may not be padded,
   * and a real day of a real month -- 2026-02-30 is a ValueError there and a
   * DateError here.
   *
   * Returns the string back, not a Date. Nothing below needs a Date, and
   * building one would import a timezone into a module that has none: the
   * Python side compares datetime.date objects, which have no offset, no
   * clock and therefore no DST. The whole reason 29 March and 1 November
   * are in the build's scenario matrix is to hold this honest. */
  function parseDate(text) {
    if (typeof text !== 'string') {
      throw new DateError(String(text) + ' is not a date');
    }
    var found = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text);
    if (!found) {
      throw new DateError(text + ' does not match format "%Y-%m-%d"');
    }
    var year = parseInt(found[1], 10);
    var month = parseInt(found[2], 10);
    var day = parseInt(found[3], 10);
    if (month < 1 || month > 12) {
      throw new DateError('month must be in 1..12');
    }
    if (day < 1 || day > daysInMonth(year, month)) {
      throw new DateError('day is out of range for month');
    }
    return { year: year, month: month, day: day, iso: isoOf(year, month, day) };
  }

  function daysInMonth(year, month) {
    var lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (month === 2 && isLeap(year)) {
      return 29;
    }
    return lengths[month - 1];
  }

  function isLeap(year) {
    return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  }

  function isoOf(year, month, day) {
    return String(year).padStart(4, '0') + '-' +
           String(month).padStart(2, '0') + '-' +
           String(day).padStart(2, '0');
  }

  /* Python: (target_date.weekday() + 1) % 7, Monday = 0 -> Sunday = 0.
   *
   * Computed arithmetically rather than through new Date(y, m - 1, d),
   * because a local Date at midnight is not a safe thing to build: in a
   * timezone whose DST transition happens at midnight the constructor
   * silently lands on the previous or the next day, and the weekday it
   * reports is the wrong one. A date has no timezone in the Python; it must
   * not acquire one here. This is Sakamoto's method. */
  function dayOfWeek(date) {
    var offsets = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4];
    var year = date.year;
    if (date.month < 3) {
      year -= 1;
    }
    return (year + Math.floor(year / 4) - Math.floor(year / 100) +
            Math.floor(year / 400) + offsets[date.month - 1] + date.day) % 7;
  }

  /* "now", the way datetime.now() is used in get_free_slots: a local date
   * and a local wall-clock minute, and nothing else. Accepts a Date (what
   * the page passes) or a "YYYY-MM-DDTHH:MM" string (what the build's
   * scenarios pin it to, so neither side has to ask a clock). */
  function asNow(value) {
    if (value === null || value === undefined) {
      value = new Date();
    }
    if (typeof value === 'string') {
      var halves = value.split('T');
      var clock = (halves[1] || '00:00').split(':');
      return {
        date: parseDate(halves[0]).iso,
        minutes: parseInt(clock[0], 10) * 60 + parseInt(clock[1], 10)
      };
    }
    return {
      date: isoOf(value.getFullYear(), value.getMonth() + 1, value.getDate()),
      minutes: value.getHours() * 60 + value.getMinutes()
    };
  }

  // -------------------------------------------------------- the queries

  /* SELECT start_time, end_time, slot_minutes FROM availability
       WHERE provider_id = ? AND day_of_week = ?                        */
  function windowsFor(data, providerId, date) {
    var wanted = dayOfWeek(date);
    return (data.availability || []).filter(function (row) {
      return row.provider_id === providerId && row.day_of_week === wanted;
    });
  }

  /* The blocks and the confirmed appointments, as minute ranges. Every
   * unclear case resolves towards being busy: losing an hour of
   * availability is an inconvenience, double-booking somebody is the thing
   * this function exists to prevent. */
  function busyRanges(data, providerId, dateStr) {
    var blocks = (data.blocked_slots || []).filter(function (row) {
      return row.provider_id === providerId && row.date === dateStr;
    });
    var ranges = blocks.map(blockRange);

    /* AND status = 'confirmed', which is narrower than "not cancelled":
     * a cancelled appointment frees its slot, which is the whole point of
     * cancelling one, and so does a completed one -- almost always moot,
     * since a completed appointment is in the past, and not the port's
     * decision to make either way. */
    var booked = (data.appointments || []).filter(function (row) {
      return row.provider_id === providerId && row.date === dateStr &&
             row.status === 'confirmed';
    });
    /* No try/except round this one, in the Python either: appointments.
     * start_time and end_time are NOT NULL and are only ever written by the
     * booking route, so an unreadable one is a corrupted row rather than a
     * user's mistake, and it raises rather than being silently swallowed
     * into a whole-day block. Faithfully not caught here. */
    return ranges.concat(booked.map(function (row) {
      return [toMinutes(row.start_time), toMinutes(row.end_time)];
    }));
  }

  /* One blocked_slots row as a minute range.
   *
   * Both times null means the whole day, which is the documented way to
   * take a day off. A start with no end reads as "blocked from 14:00", the
   * only reading that cannot double-book. A time that is not a time blocks
   * the day, because a block nobody can interpret should not quietly
   * disappear. */
  function blockRange(block) {
    var start = block.start_time;
    var end = block.end_time;
    if (start === null || start === undefined) {
      return [0, MINUTES_IN_A_DAY];
    }
    try {
      var first = toMinutes(start);
      var last = (end === null || end === undefined)
        ? MINUTES_IN_A_DAY : toMinutes(end);
      return [first, last];
    } catch (bad) {
      if (!(bad instanceof TimeError)) {
        throw bad;
      }
      return [0, MINUTES_IN_A_DAY];
    }
  }

  // ------------------------------------------------------------ tiling

  /* One availability window cut into free slot-sized pieces. */
  function tile(window, busy, earliest) {
    var start;
    var end;
    try {
      start = toMinutes(window.start_time);
      end = toMinutes(window.end_time);
    } catch (bad) {
      if (!(bad instanceof TimeError)) {
        throw bad;
      }
      return [];                        // unreadable window, skipped
    }

    var step = window.slot_minutes;
    /* The loop advances the cursor by step. A zero or negative one never
     * terminates: it appends slots until the tab runs out of memory. The
     * route refuses these now; a row already stored still has to not hang
     * anything. */
    if (!step || step <= 0) {
      return [];
    }

    var out = [];
    var cursor = start;
    while (cursor + step <= end) {
      var slotStart = cursor;
      var slotEnd = cursor + step;
      cursor += step;
      /* <= rather than <: a slot starting this very minute is not
       * bookable, because by the time anyone confirms it, it has begun. */
      if (slotStart <= earliest) {
        continue;
      }
      var clash = busy.some(function (range) {
        return slotStart < range[1] && slotEnd > range[0];
      });
      if (clash) {
        continue;
      }
      out.push({ start: toHhmm(slotStart), end: toHhmm(slotEnd) });
    }
    return out;
  }

  // ----------------------------------------------------------- the API

  /* A sorted list of { start, end } for one provider on one date. */
  function getFreeSlots(data, providerId, dateStr, now) {
    var target = parseDate(dateStr);
    var windows = windowsFor(data, providerId, target);
    if (!windows.length) {
      return [];
    }

    var clock = asNow(now);
    /* A date strictly before today is entirely in the past -- every slot on
     * it, not just the early ones -- so there is nothing left to tile.
     * Compared as text, which is what YYYY-MM-DD is for. */
    if (target.iso < clock.date) {
      return [];
    }

    var busy = busyRanges(data, providerId, dateStr);
    /* Only today has a partial past to exclude. -1 is before every slot
     * start, so a future date compares against something no slot can be at
     * or below. */
    var earliest = target.iso === clock.date ? clock.minutes : -1;

    var slots = [];
    windows.forEach(function (window) {
      slots = slots.concat(tile(window, busy, earliest));
    });
    /* Stable, and on the start alone, exactly as the Python's
     * list.sort(key=...) is. */
    slots.sort(function (a, b) {
      return a.start < b.start ? -1 : (a.start > b.start ? 1 : 0);
    });
    return slots;
  }

  /* Is [startTime, endTime) bookable, across however many slots it spans?
   *
   * Walking consecutive free slots rather than matching one exactly: a
   * provider offering 30-minute slots can still take a 60-minute booking,
   * and a single-slot booking behaves identically. */
  function isSlotFree(data, providerId, dateStr, startTime, endTime, now) {
    var free = getFreeSlots(data, providerId, dateStr, now);
    if (!free.length) {
      return false;
    }

    /* Built the same way round as the dict comprehension it came from, so
     * two windows that produce the same start leave the same one behind. */
    var nextBoundary = Object.create(null);
    free.forEach(function (slot) {
      nextBoundary[slot.start] = slot.end;
    });

    var cursor = startTime;
    while (cursor < endTime) {
      var following = nextBoundary[cursor];
      if (following === undefined) {
        return false;                   // not the start of a free slot
      }
      if (following > endTime) {
        return false;                   // the last slot would overrun
      }
      cursor = following;
    }
    return cursor === endTime;
  }

  /* Start times on this date that can actually hold durationMin.
   *
   * The booking page needs this rather than the raw slot list: offering a
   * guest a 16:30 start for a 60-minute session when the day ends at 17:00
   * is an invitation to hit an error. */
  function slotStartsFor(data, providerId, dateStr, durationMin, now) {
    var free = getFreeSlots(data, providerId, dateStr, now);
    var out = [];
    free.forEach(function (slot) {
      var start = slot.start;
      var total = toMinutes(start) + durationMin;
      var end = toHhmm(total);
      if (total <= MINUTES_IN_A_DAY &&
          isSlotFree(data, providerId, dateStr, start, end, now)) {
        out.push({ start: start, end: end });
      }
    });
    return out;
  }

  return {
    MINUTES_IN_A_DAY: MINUTES_IN_A_DAY,
    TimeError: TimeError,
    DateError: DateError,
    toMinutes: toMinutes,
    toHhmm: toHhmm,
    parseDate: parseDate,
    dayOfWeek: dayOfWeek,
    windowsFor: windowsFor,
    busyRanges: busyRanges,
    blockRange: blockRange,
    tile: tile,
    getFreeSlots: getFreeSlots,
    isSlotFree: isSlotFree,
    slotStartsFor: slotStartsFor
  };
}());
