"""Cards grown before the Black-only rule are brought into line with it."""

from __future__ import annotations

from datetime import date

from chess_trainer.db import cards_repo, schedule_repo
from chess_trainer.db.cards_repo import STATUS_ACTIVE, STATUS_DEAD_END, CardRow
from chess_trainer.openings import line as line_module, prune


def add(conn, line: str, *, parent=None, answer=None, expanded=False, status=STATUS_ACTIVE):
    ucis = line.split()
    position = line_module.position_of(ucis)
    before = line_module.position_of(ucis[:-1])
    return cards_repo.insert(
        conn,
        CardRow(
            epd=position.epd,
            fen=position.fen,
            line_uci=position.line_uci,
            depth=position.depth,
            parent_card_id=parent.id if parent else None,
            side_to_move=position.side_to_move,
            given_move_uci=ucis[-1],
            given_move_san=line_module.san_of(before.fen, ucis[-1]),
            status=status,
            position_games=100,
            queue_seq=len(line),
            answer_uci=answer,
            expanded_at="then" if expanded else None,
        ),
    )


def schedule(conn, card) -> None:
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=card.id, n=1, ef=2.5, interval_days=1, due_on=date(2026, 11, 6)
        ),
    )


def lines(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT line_uci FROM cards")}


def old_g3_tree(conn):
    """1.g3 grown the old way: every Black move, and White-to-move cards."""
    g3 = add(conn, "g2g3", answer="d7d5", expanded=True)
    d5 = add(conn, "g2g3 d7d5", parent=g3, answer="f1g2", expanded=True)
    nf6 = add(conn, "g2g3 g8f6", parent=g3, answer="f1g2", expanded=True)
    add(conn, "g2g3 g8f6 f1g2", parent=nf6)
    bg2 = add(conn, "g2g3 d7d5 f1g2", parent=d5, answer="e7e5")
    add(conn, "g2g3 d7d5 b2b3", parent=d5, status=STATUS_DEAD_END)
    return g3, d5, bg2


def test_other_black_moves_go_with_everything_under_them(conn):
    old_g3_tree(conn)
    prune.prune_black_only(conn)
    assert not any(line.startswith("g2g3 g8f6") for line in lines(conn))


def test_the_white_to_move_card_goes_and_its_replies_move_up(conn):
    g3, _, bg2 = old_g3_tree(conn)
    prune.prune_black_only(conn)
    assert lines(conn) == {"g2g3", "g2g3 d7d5 f1g2", "g2g3 d7d5 b2b3"}
    assert cards_repo.get(conn, bg2.id).parent_card_id == g3.id


def test_a_moved_card_keeps_its_schedule(conn):
    _, _, bg2 = old_g3_tree(conn)
    schedule(conn, bg2)
    prune.prune_black_only(conn)
    assert schedule_repo.get(conn, bg2.id) is not None


def test_a_deleted_card_takes_its_schedule_with_it(conn):
    _, d5, _ = old_g3_tree(conn)
    schedule(conn, d5)
    prune.prune_black_only(conn)
    assert schedule_repo.get(conn, d5.id) is None


def test_my_white_first_moves_are_left_alone(conn):
    e4 = add(conn, "e2e4", answer="c7c5", expanded=True)
    c5 = add(conn, "e2e4 c7c5", parent=e4, answer="g1f3")
    add(conn, "e2e4 e7e5", parent=e4, answer="g1f3")
    prune.prune_black_only(conn)
    assert lines(conn) == {"e2e4", "e2e4 c7c5", "e2e4 e7e5"}
    assert cards_repo.get(conn, c5.id) is not None


def test_an_answer_never_expanded_lets_the_card_grow_again(conn):
    g3 = add(conn, "g2g3", answer="d7d5", expanded=True)
    add(conn, "g2g3 d7d5", parent=g3)
    prune.prune_black_only(conn)
    assert lines(conn) == {"g2g3"}
    assert not cards_repo.get(conn, g3.id).is_expanded


def test_a_dead_end_answer_stays_as_the_note(conn):
    g3 = add(conn, "g2g3", answer="d7d5", expanded=True)
    add(conn, "g2g3 d7d5", parent=g3, status=STATUS_DEAD_END)
    prune.prune_black_only(conn)
    assert lines(conn) == {"g2g3", "g2g3 d7d5"}


def test_pruning_goes_all_the_way_down(conn):
    g3, _, bg2 = old_g3_tree(conn)
    cards_repo.mark_expanded(conn, bg2.id)
    e5 = add(conn, "g2g3 d7d5 f1g2 e7e5", parent=bg2, answer="d2d3", expanded=True)
    add(conn, "g2g3 d7d5 f1g2 c7c6", parent=bg2)
    add(conn, "g2g3 d7d5 f1g2 e7e5 d2d3", parent=e5)
    prune.prune_black_only(conn)
    assert "g2g3 d7d5 f1g2 e7e5 d2d3" in lines(conn)
    assert "g2g3 d7d5 f1g2 e7e5" not in lines(conn)
    assert "g2g3 d7d5 f1g2 c7c6" not in lines(conn)


def test_pruning_twice_changes_nothing(conn):
    old_g3_tree(conn)
    prune.prune_black_only(conn)
    before = lines(conn)
    assert prune.prune_black_only(conn) == 0
    assert lines(conn) == before
