Search Tests the databse queries using the check1.py
--- Search ---
PASS  'عندكم الهودي البني مقاس M؟ وبكام؟' -> ['H-014', 'H-022'] (needs_clarification=True)
PASS  'عايز هودي اسود' -> ['H-031'] (needs_clarification=False)
PASS  'عندكم بنطلون؟' -> ['T-005'] (needs_clarification=False)
PASS  'hodi aswad' -> ['H-031'] (needs_clarification=False)
PASS  'عندكم جاكيت؟' -> [] (needs_clarification=False)

--- Reservations ---
PASS  last item starts with 1 available
PASS  two simultaneous reservations: exactly one wins (results=[False, True])
PASS  reserved count is 1 (got 1)
PASS  a third customer is refused
PASS  release works
PASS  releasing twice does nothing
PASS  reserved back to 0 (got 0)
PASS  asking for more than the stock is refused
PASS  expiry job releases an expired hold
PASS  reserved back to 0 after expiry (got 0)

All checks passed.