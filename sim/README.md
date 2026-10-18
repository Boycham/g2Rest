# Dinner-rush simulator (step 9, not built yet)

Replays a two-hour service in about 3 minutes, once FIFO and once with priority scoring, and
reports hot-food wait at the pass side by side.

## Must model runner availability

The pass only hands a run to a **free** server (`Store.dispatch()` in `backend/app/state.py`:
a server is free when they have no open `RUN` task; the best-scoring run takes the section's
free server first, then anyone free; if it needs more hands than are free, everything below
it waits too). If the simulator marks every `RUN` task done the instant it is created, every
course leaves alone the moment it is ready and FIFO and priority look almost the same.

So the simulated server must:

1. accept the `task.assigned` card after a short reaction time,
2. keep the task open for a travel time (for example 45-90 s from pass to table and back,
   plus 15 s per extra table in the run), and only then send `task.done`,
3. which triggers the backend's re-plan and frees the server for the next run.

## Must report the cost of the reservation rule

Free servers are held for the top-scoring run even when that briefly blocks smaller runs (it
protects "a table's whole course goes out together"; letting small runs slip past would starve big
tables in a rush). The simulator must measure what that costs: for each run of the simulation,
report **how long servers sat idle while reserved for a bigger run** (seconds a free server had
no RUN task while a ready run was waiting at the pass for more hands than were free), total and
per server, next to the hot-plate wait times. Derive it from the event log: a `pass.up` with no
`pass.run` for its plate while `GET /tasks` shows a server with no open RUN task, or add a
`pass.reserved {run, waitingFor, idle: [server]}` event on the backend side when the ticker
re-plans and the best run cannot go.

Hot-food wait is measured from `pass.up` to `pass.run` in the event log (`GET /events?type=pass.`),
per plate, split by temperature. Drive the planner with `POST /pass/planner {"planner": "fifo"|"priority"}`
and tune `RunWeights` through `backend/app/run_weights.py`.
