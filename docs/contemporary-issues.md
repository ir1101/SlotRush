# Contemporary issues: absorbing registration spikes (draft)

## The problem

Registration opens at a fixed time, so almost all demand arrives in the first minutes: a
**flash crowd**. The load is also very uneven: most requests target the same few popular
offerings, and in this design every request for one offering must take that offering's **one
row lock** (`SELECT … FOR UPDATE` in `register()`).

The locking demo measures what that means: 80 bots on one offering are served strictly one after
another (`results/demo_locking.png`, the queue of waiting sessions drains in a straight line).
With a 50 ms transaction that is about 5 s for just 80 students (4.7 to 7.1 s across our runs, `results/demo_locking.json`). For
5,000 students wanting the same
popular course it would be minutes, and long before that the server runs out of connections
(PostgreSQL starts one process per connection; this project raised `max_connections` from 100
to 200 just for 80 bots and a monitor).

So large portals do not let the whole crowd reach the database. They put a queue in front of it.

## Virtual waiting rooms

A **virtual waiting room** sits in front of the application:

1. When the portal opens, every visitor is sent to a lightweight waiting page served from a
   CDN, not from the application servers, so it costs the real system almost nothing.
2. Each visitor gets a **position in a queue**. Many systems assign positions **at random**
   among everyone who arrived before opening time, so refreshing faster or running scripts does
   not help; after opening, arrivals are first come, first served.
3. Visitors are let out of the queue at a fixed rate that the back end is known to handle (for
   example, a few hundred per minute). Each one receives a signed, time-limited **admission
   token**; the application rejects requests without one.
4. The page shows the position and an estimated wait, which reduces the urge to refresh.

Commercial services (for example Queue-it) and the queues used by large ticketing sites work
this way. The design moves the waiting from the database lock queue, where waiting holds
connections and memory, into a cheap queue at the edge.

## Other techniques used together with it

| Technique | What it does | Link to this project |
|---|---|---|
| **Admission control / rate limiting** (token bucket, leaky bucket) | caps requests per second per user and overall; excess gets "try again later" (HTTP 429/503 with Retry-After) | protects `max_connections` |
| **Connection pooling** (PgBouncer, `psycopg_pool`) | many clients share a few database connections | each PostgreSQL connection is a whole process |
| **Short critical sections** | do validation and "think time" outside the transaction; hold the hot row lock only for the update itself | the locking demo holds the lock for 50 ms on purpose; that is what makes it slow |
| **Ordered locking** | always lock rows in one global order | `swap_course` locks the lower offering id first, so no deadlocks |
| **Optimistic concurrency** | no locks; detect conflicts and retry (SERIALIZABLE, or a version column) | the serializable demo: correct, faster here, but about 1,400 retries of wasted work (`results/demo_serializable.json`) |
| **Asynchronous queues** | requests go into a message queue; one worker per offering applies them in order and reports OK/FULL later | removes lock contention completely; the student gets the answer a few seconds later |
| **Caching and read replicas** | the course catalogue and seat counts shown while browsing come from a cache or replica, slightly stale | the authoritative check still happens in `register()` on the primary (CAP doc: browse = AP, allot = CP) |
| **Seat holds with expiry** | a seat is reserved for a few minutes while the user confirms, then released | common in ticketing; would need a `hold_expires_at` column and a cleanup job |
| **Staggered windows** | open registration for different years or programmes at different times | spreads one huge spike into several smaller ones |
| **Bot protection** | CAPTCHA, one session per student, per-account limits | keeps scripts from taking all seats in the first second |

## Trade-offs to discuss in the review

- **Fairness vs throughput**: a strict FIFO queue is fair but slow to drain; batching admissions
  is faster but coarser. A random order at opening time is fair only if everyone arrives before
  opening.
- **Consistency vs availability**: the seat check must stay strongly consistent (one primary,
  row locks or serializable transactions). Everything around it (catalogue, seat counts on screen,
  reviews) can be eventually consistent. See [nosql-cap.md](nosql-cap.md).
- **User experience vs load**: a waiting room tells users the truth ("you are 4,213th") instead
  of timing out, which also stops the retry storms that make outages worse.
