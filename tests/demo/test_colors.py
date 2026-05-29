"""Deterministic GlobalID -> colour."""

from __future__ import annotations

from tools.demo.colors import global_id_bgr, global_id_hex, global_id_rgb


def test_color_is_deterministic():
    gid = "11111111-1111-1111-1111-111111111111"
    assert global_id_rgb(gid) == global_id_rgb(gid)
    assert global_id_hex(gid) == global_id_hex(gid)


def test_different_ids_usually_differ():
    a = global_id_hex("aaaaaaaa-0000-0000-0000-000000000000")
    b = global_id_hex("bbbbbbbb-0000-0000-0000-000000000000")
    assert a != b


def test_bgr_is_rgb_reversed():
    gid = "cccccccc-0000-0000-0000-000000000000"
    r, g, b = global_id_rgb(gid)
    assert global_id_bgr(gid) == (b, g, r)


def test_hex_format():
    h = global_id_hex("dddddddd-0000-0000-0000-000000000000")
    assert h.startswith("#") and len(h) == 7
