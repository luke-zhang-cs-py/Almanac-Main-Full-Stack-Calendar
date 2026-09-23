/* The page around the engine.
 *
 * Everything that decides *which slots exist* is in slots.js and nowhere
 * else -- this file reads controls, hands rows to AlmanacSlots, and draws
 * what comes back. That split is not tidiness: slots.js is the file
 * tools/build_static.py compares against domain/calendar_logic.py, and a
 * rule that leaked in here would be a rule nothing checks.
 *
 * The "how it got there" list is derived the same way, by calling the
 * engine's own tile() three times with different filters rather than by
 * counting anything a second time here.
 */
(function () {
  'use strict';

  var S = window.AlmanacSlots;
  var SCENARIOS = window.AlmanacScenarios;

  var DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
              'Friday', 'Saturday'];

  var providerId = SCENARIOS.providerId;
  var data = null;
  var now = null;

  function el(id) { return document.getElementById(id); }

  function clear(node) {
    while (node.firstChild) { node.removeChild(node.firstChild); }
  }

  function copy(value) { return JSON.parse(JSON.stringify(value)); }

  // ------------------------------------------------------------- setup

  function start() {
    var select = el('preset');
    SCENARIOS.presets.forEach(function (preset, index) {
      var option = document.createElement('option');
      option.value = String(index);
      option.textContent = preset.name;
      select.appendChild(option);
    });
    select.addEventListener('change', function () {
      load(SCENARIOS.presets[Number(select.value)]);
    });

    var dayPicker = el('windowDay');
    DAYS.forEach(function (name, index) {
      var option = document.createElement('option');
      option.value = String(index);
      option.textContent = name;
      dayPicker.appendChild(option);
    });

    el('addWindow').addEventListener('submit', onAddWindow);
    el('addBlock').addEventListener('submit', onAddBlock);
    el('addBooking').addEventListener('submit', onAddBooking);
    el('probeForm').addEventListener('submit', onProbe);
    ['askDate', 'askDuration', 'askNow'].forEach(function (id) {
      el(id).addEventListener('change', render);
      el(id).addEventListener('input', render);
    });

    load(SCENARIOS.presets[0]);
  }

  function load(preset) {
    data = copy(preset.data);
    el('presetNote').textContent = preset.note;
    el('askDate').value = preset.date;
    el('askNow').value = preset.now;
    el('askDuration').value = String(preset.duration);
    el('blockDate').value = preset.date;
    el('bookingDate').value = preset.date;
    el('windowDay').value = String(preset.day);
    render();
  }

  // ------------------------------------------------------------ adding

  function onAddWindow(event) {
    event.preventDefault();
    data.availability.push({
      provider_id: providerId,
      day_of_week: Number(el('windowDay').value),
      start_time: el('windowStart').value.trim(),
      end_time: el('windowEnd').value.trim(),
      slot_minutes: Number(el('windowSlot').value)
    });
    render();
  }

  function onAddBlock(event) {
    event.preventDefault();
    /* An empty box is a NULL column, not an empty string: both times null is
     * the documented way to take a whole day off, and a start with no end
     * reads as "blocked from here on". */
    data.blocked_slots.push({
      provider_id: providerId,
      date: el('blockDate').value,
      start_time: el('blockStart').value.trim() || null,
      end_time: el('blockEnd').value.trim() || null
    });
    render();
  }

  function onAddBooking(event) {
    event.preventDefault();
    data.appointments.push({
      provider_id: providerId,
      date: el('bookingDate').value,
      start_time: el('bookingStart').value.trim(),
      end_time: el('bookingEnd').value.trim(),
      status: el('bookingStatus').value
    });
    render();
  }

  function drop(list, index) {
    list.splice(index, 1);
    render();
  }

  // ----------------------------------------------------------- drawing

  function row(parent, whenText, labelText, onDrop) {
    var line = document.createElement('div');
    line.className = 'demo-row';

    var when = document.createElement('span');
    when.className = 'when';
    when.textContent = whenText;
    line.appendChild(when);

    if (labelText) {
      var label = document.createElement('span');
      label.className = 'label';
      label.textContent = labelText;
      line.appendChild(label);
    }

    var spacer = document.createElement('span');
    spacer.className = 'spacer';
    line.appendChild(spacer);

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'demo-drop';
    button.textContent = 'remove';
    button.addEventListener('click', onDrop);
    line.appendChild(button);

    parent.appendChild(line);
    return line;
  }

  function emptyNote(parent, text) {
    var note = document.createElement('div');
    note.className = 'demo-empty';
    note.textContent = text;
    parent.appendChild(note);
  }

  function drawWeek() {
    var host = el('weekRows');
    clear(host);
    if (!data.availability.length) {
      emptyNote(host, 'No hours set at all, so nothing is ever bookable.');
      return;
    }
    DAYS.forEach(function (name, index) {
      var mine = [];
      data.availability.forEach(function (window, at) {
        if (window.provider_id === providerId && window.day_of_week === index) {
          mine.push({ window: window, at: at });
        }
      });
      if (!mine.length) { return; }
      mine.forEach(function (entry) {
        row(host,
            name + '  ' + entry.window.start_time + '–' + entry.window.end_time,
            entry.window.slot_minutes + ' min slots',
            function () { drop(data.availability, data.availability.indexOf(entry.window)); });
      });
    });
    if (!host.firstChild) {
      emptyNote(host, 'No hours on any weekday.');
    }
  }

  function drawBlocks() {
    var host = el('blockRows');
    clear(host);
    if (!data.blocked_slots.length) {
      emptyNote(host, 'No blocks.');
      return;
    }
    data.blocked_slots.forEach(function (block) {
      var span;
      if (block.start_time === null || block.start_time === undefined) {
        span = 'the whole day';
      } else if (block.end_time === null || block.end_time === undefined) {
        span = 'from ' + block.start_time;
      } else {
        span = block.start_time + '–' + block.end_time;
      }
      row(host, block.date, span, function () {
        drop(data.blocked_slots, data.blocked_slots.indexOf(block));
      });
    });
  }

  function drawBookings() {
    var host = el('bookingRows');
    clear(host);
    if (!data.appointments.length) {
      emptyNote(host, 'Nothing booked.');
      return;
    }
    data.appointments.forEach(function (booking) {
      var line = row(host,
          booking.date + '  ' + booking.start_time + '–' + booking.end_time,
          null,
          function () { drop(data.appointments, data.appointments.indexOf(booking)); });
      var pill = document.createElement('span');
      pill.className = 'status-pill ' + booking.status;
      pill.textContent = booking.status;
      line.insertBefore(pill, line.querySelector('.spacer'));
    });
  }

  function drawBoard(slots, durationMin) {
    var grid = el('boardGrid');
    var empty = el('boardEmpty');
    clear(grid);

    if (!slots.length) {
      empty.classList.remove('hidden');
      empty.textContent = durationMin
        ? 'Nothing on this date is long enough to hold ' + durationMin + ' minutes.'
        : 'Nothing bookable on this date.';
      return;
    }
    empty.classList.add('hidden');
    slots.forEach(function (slot) {
      var chip = document.createElement('div');
      chip.className = 'slot-chip';
      chip.textContent = slot.start;
      chip.title = slot.start + ' – ' + slot.end;
      grid.appendChild(chip);
    });
  }

  function trace(items) {
    var host = el('traceList');
    clear(host);
    items.forEach(function (text) {
      var item = document.createElement('li');
      item.innerHTML = text;
      host.appendChild(item);
    });
  }

  function escape(text) {
    return String(text).replace(/[&<>"]/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch];
    });
  }

  function strong(text) { return '<b>' + escape(text) + '</b>'; }

  // ---------------------------------------------------------- the work

  function render() {
    drawWeek();
    drawBlocks();
    drawBookings();

    var dateStr = el('askDate').value;
    var durationMin = Number(el('askDuration').value);
    now = el('askNow').value || null;

    var problem = null;
    var slots = [];
    var lines = [];

    try {
      var date = S.parseDate(dateStr);
      var windows = S.windowsFor(data, providerId, date);
      var busy = S.busyRanges(data, providerId, dateStr);

      var gross = 0;
      var afterBusy = 0;
      windows.forEach(function (window) {
        gross += S.tile(window, [], -1).length;
        afterBusy += S.tile(window, busy, -1).length;
      });

      var free = S.getFreeSlots(data, providerId, dateStr, now);
      slots = durationMin
        ? S.slotStartsFor(data, providerId, dateStr, durationMin, now)
        : free;

      el('boardDay').textContent =
        DAYS[S.dayOfWeek(date)] + ' ' + date.iso;
      el('boardCount').textContent =
        slots.length + (slots.length === 1 ? ' slot' : ' slots');

      lines.push(DAYS[S.dayOfWeek(date)] + ' is day ' +
                 strong(S.dayOfWeek(date)) + ' — the table stores Sunday as 0, ' +
                 'so this reads ' + strong(windows.length) +
                 (windows.length === 1 ? ' window' : ' windows') + ' of hours.');
      lines.push(strong(busy.length) +
                 (busy.length === 1 ? ' busy range' : ' busy ranges') +
                 ' on this date, from blocks and confirmed bookings together — ' +
                 'the engine does not distinguish them.');
      lines.push('Those windows tile into ' + strong(gross) +
                 (gross === 1 ? ' slot' : ' slots') + ' before anything is ' +
                 'taken out.');
      lines.push(strong(gross - afterBusy) + ' dropped for overlapping ' +
                 'something busy — any overlap at all, not just an exact one.');
      lines.push(strong(afterBusy - free.length) + ' dropped as past. ' +
                 pastReason(date.iso, now, afterBusy - free.length));
      if (durationMin) {
        lines.push(strong(free.length - slots.length) + ' of the ' +
                   strong(free.length) + ' free slots cannot hold ' +
                   strong(durationMin + ' minutes') + ', because the slots ' +
                   'after them are not free or the day ends first.');
      }
    } catch (bad) {
      problem = bad && bad.message ? bad.message : String(bad);
      el('boardDay').textContent = '—';
      el('boardCount').textContent = '—';
      lines = ['The engine refused this input, exactly as the Python does: ' +
               strong(problem)];
    }

    drawBoard(slots, durationMin);
    trace(lines);
    answerProbe();
  }

  function pastReason(iso, clock, dropped) {
    var today = clock ? String(clock).split('T')[0] : null;
    if (today && iso < today) {
      return 'The date is before the pretended today, and a date entirely in ' +
             'the past has nothing left on it at all.';
    }
    if (today && iso === today) {
      return dropped
        ? 'Today is the only date with a partial past to exclude.'
        : 'Today, but nothing has started yet.';
    }
    return 'A future date has no past to exclude.';
  }

  function onProbe(event) {
    event.preventDefault();
    answerProbe();
  }

  function answerProbe() {
    var target = el('probeAnswer');
    var dateStr = el('askDate').value;
    var from = el('probeStart').value.trim();
    var to = el('probeEnd').value.trim();
    try {
      var free = S.isSlotFree(data, providerId, dateStr, from, to, now);
      target.className = 'demo-answer ' + (free ? 'yes' : 'no');
      target.textContent = from + '–' + to + ' on ' + dateStr + ': ' +
        (free ? 'bookable — every slot it covers is free and it ends on a boundary.'
              : 'not bookable.');
    } catch (bad) {
      target.className = 'demo-answer no';
      target.textContent = 'refused: ' + (bad && bad.message ? bad.message : bad);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}());
