"""Two sessions at once: row locks in register() and the lock order in swap_course().

These tests need committed data that several connections can see, so they use
the "committed" fixture instead of the rolled-back "db" fixture.
"""
import threading
import time

from .fixtures import S1, S2


def test_last_seat_goes_to_exactly_one_of_two_sessions(committed):
    first, second = committed(), committed()
    # Offering 105 has one seat. Session 1 takes it and keeps its transaction open.
    assert first.execute("SELECT register(%s, 105)", (S1,)).fetchone()[0] == "OK"

    result = {}

    def second_session():
        # Blocks on SELECT ... FOR UPDATE of offering 105 until session 1 ends.
        result["status"] = second.execute("SELECT register(%s, 105)", (S2,)).fetchone()[0]
        second.commit()

    thread = threading.Thread(target=second_session)
    thread.start()
    time.sleep(0.5)
    assert thread.is_alive(), "session 2 should be waiting for session 1's row lock"

    first.commit()                     # releases the lock; session 2 now sees seats_left = 0
    thread.join(timeout=10)
    assert result["status"] == "FULL"

    check = committed()
    assert check.execute("SELECT seats_left FROM offering WHERE offering_id = 105").fetchone()[0] == 0
    assert check.execute("SELECT count(*) FROM registration WHERE offering_id = 105").fetchone()[0] == 1


def test_opposite_swaps_do_not_deadlock(committed):
    # S1 is in 105 and wants 107; S2 is in 107 and wants 105 (both BMAT101L).
    setup = committed()
    setup.execute("UPDATE offering SET capacity = 5, seats_left = 5 WHERE offering_id = 105")
    setup.execute("SELECT register(%s, 105)", (S1,))
    setup.execute("SELECT register(%s, 107)", (S2,))
    setup.commit()

    barrier = threading.Barrier(2)
    results, errors = {}, []

    def swap(reg_no, from_id, to_id):
        conn = committed()
        try:
            barrier.wait()                                    # start together
            status = conn.execute("SELECT swap_course(%s, %s, %s)",
                                  (reg_no, from_id, to_id)).fetchone()[0]
            conn.execute("SELECT pg_sleep(0.3)")              # hold the locks a little longer
            conn.commit()
            results[reg_no] = status
        except Exception as exc:                              # a deadlock would land here
            errors.append(exc)

    threads = [threading.Thread(target=swap, args=(S1, 105, 107)),
               threading.Thread(target=swap, args=(S2, 107, 105))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    assert results == {S1: "OK", S2: "OK"}
