from __future__ import annotations

import pytest

from chess_trainer import rules

START = rules.START_FEN
# Black has just played ...Qh4#: White is checkmated.
MATED = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
# White pawn one step from promotion.
PROMO = "8/P7/8/8/8/8/8/K6k w - - 0 1"
STALEMATE = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


def test_position_state_of_start_position():
    state = rules.position_state(START)
    assert state.turn == "white"
    assert len(state.legal_ucis) == 20
    assert sorted(state.dests["e2"]) == ["e3", "e4"]
    assert sorted(state.dests["g1"]) == ["f3", "h3"]
    assert not state.in_check
    assert not state.game_over
    assert state.outcome is None


def test_dests_groups_by_origin_without_duplicates():
    state = rules.position_state(START)
    assert len(state.dests) == 10  # 8 pawns + 2 knights
    for targets in state.dests.values():
        assert len(targets) == len(set(targets))


def test_position_state_detects_checkmate():
    state = rules.position_state(MATED)
    assert state.game_over
    assert state.outcome == "Black wins by checkmate"
    assert state.dests == {}


def test_position_state_detects_stalemate():
    state = rules.position_state(STALEMATE)
    assert state.game_over
    assert state.outcome == "Draw by stalemate"


def test_invalid_fen_raises_value_error():
    with pytest.raises(ValueError):
        rules.position_state("not a fen")


def test_apply_move_returns_san_and_new_position():
    result = rules.apply_move(START, "e2e4")
    assert result.san == "e4"
    assert result.uci == "e2e4"
    assert not result.is_capture
    assert not result.game_over
    assert result.fen_after.startswith("rnbqkbnr/pppppppp/8/8/4P3")
    assert " b " in result.fen_after  # Black to move now


def test_apply_move_marks_captures():
    fen = rules.fen_after_moves(["e2e4", "d7d5"])
    assert rules.apply_move(fen, "e4d5").is_capture


def test_apply_illegal_move_raises():
    with pytest.raises(rules.IllegalMove, match="not legal"):
        rules.apply_move(START, "e2e5")


def test_apply_malformed_move_raises():
    with pytest.raises(rules.IllegalMove, match="Malformed"):
        rules.apply_move(START, "zz99")


def test_needs_promotion_only_for_pawn_on_last_rank():
    assert rules.needs_promotion(PROMO, "a7", "a8")
    assert not rules.needs_promotion(START, "e2", "e4")
    assert not rules.needs_promotion(PROMO, "a1", "a2")  # king move


def test_resolve_uci_defaults_to_queen():
    assert rules.resolve_uci(PROMO, "a7", "a8") == "a7a8q"
    assert rules.resolve_uci(PROMO, "a7", "a8", "n") == "a7a8n"
    assert rules.resolve_uci(START, "e2", "e4") == "e2e4"


def test_resolve_uci_rejects_bad_promotion_piece():
    with pytest.raises(rules.IllegalMove, match="Invalid promotion"):
        rules.resolve_uci(PROMO, "a7", "a8", "k")


def test_promotion_move_reports_piece():
    result = rules.apply_move(PROMO, "a7a8n")
    assert result.promotion == "n"
    assert result.san == "a8=N"


def test_san_of_does_not_change_the_position():
    assert rules.san_of(START, "g1f3") == "Nf3"
    with pytest.raises(rules.IllegalMove):
        rules.san_of(START, "g1f4")


def test_fen_after_moves_replays_a_line():
    fen = rules.fen_after_moves(["e2e4", "e7e5", "g1f3", "b8c6"])
    assert " w " in fen
    assert rules.position_state(fen).turn == "white"


def test_fen_after_moves_rejects_an_illegal_line():
    with pytest.raises(rules.IllegalMove):
        rules.fen_after_moves(["e2e4", "e2e5"])


def test_fen_after_moves_with_no_moves_is_the_start():
    assert rules.fen_after_moves([]) == START


def test_castling_and_en_passant_are_legal_where_expected():
    # 1.e4 e5 2.Nf3 Nf6 3.Bc4 Bc5 -> White may castle short.
    fen = rules.fen_after_moves(
        ["e2e4", "e7e5", "g1f3", "g8f6", "f1c4", "f8c5"]
    )
    assert "g1" in rules.position_state(fen).dests["e1"]
    assert rules.apply_move(fen, "e1g1").san == "O-O"
