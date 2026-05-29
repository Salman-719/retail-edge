"""Synchronized review page HTML generation."""

from __future__ import annotations

from tools.demo.colors import global_id_hex
from tools.demo.review_page import build_review_html, render_review_page


def _cameras():
    return [
        {"camera_id": "cam1", "video_src": "annotated/cam1.mp4"},
        {"camera_id": "cam2", "video_src": "annotated/cam2.mp4"},
    ]


def test_html_contains_videos_metrics_and_legend():
    gids = ["G-abc", "G-def"]
    html = build_review_html(_cameras(), {"global_ids": 2, "cross_camera_links": 1}, gids)
    assert html.count("<video") == 2
    assert "annotated/cam1.mp4" in html and "annotated/cam2.mp4" in html
    assert "cross_camera_links" in html and ">1<" in html
    for g in gids:
        assert g in html
        assert global_id_hex(g) in html  # legend swatch colour


def test_html_escapes_camera_ids():
    html = build_review_html([{"camera_id": "<x>", "video_src": "a.mp4"}], {}, [])
    assert "<x>" not in html and "&lt;x&gt;" in html


def test_render_writes_file(tmp_path):
    out = render_review_page(tmp_path / "review.html", _cameras(), {"n": 1}, ["G-1"])
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
