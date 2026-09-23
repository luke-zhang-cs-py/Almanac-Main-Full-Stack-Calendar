"""
notify/
--------
Everything that reaches somebody outside the request they made.

Not called `email`, which would shadow the standard library's package for
the whole process -- `mailer.py` imports `email.mime.text`, so that name is
not available to take.

The stack, bottom to top:

  email_render.py         how a message is laid out: one description in,
                          a text half and an HTML half out, which is what
                          stops the two drifting apart
  mailer.py               transport -- SMTP or the console, a background
                          queue, and the delivery log with the unique index
                          that makes "once each" a database guarantee
  notifications.py        what is said, and on what occasion: register,
                          book, cancel, remind
  coffee_notifications.py the same for the invite flow, whose audience has
                          no account and no app to be sent back to
  scheduler.py            the one background timer, and the only thing here
                          that runs outside a request

`scheduler` is in this package rather than beside `app.py` because the only
thing it schedules is this package: one thread, waking up to call
`notifications` and `coffee_notifications`. `app.py` starts it and knows
nothing else about it.
"""
