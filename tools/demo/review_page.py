"""Synchronized multi-camera review page.

Generates a single self-contained HTML page: N camera videos sharing one play/
pause/seek timeline (via requestAnimationFrame), a metrics panel, and a Global ID
legend (colour -> GID). This is the demo artifact -- when the same person walks
between Cam2 and Cam3 their box colour (Global ID) stays identical.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from common.utils.jsonio import write_json_atomic  # noqa: F401  (kept for artifact siblings)
from tools.demo.colors import global_id_hex


def build_review_html(cameras: list[dict], metrics: dict, global_ids: list[str]) -> str:
    """cameras: [{'camera_id': str, 'video_src': str}]; metrics: flat dict;
    global_ids: the Global IDs to show in the legend."""
    players = "\n".join(
        f'<figure><figcaption>{escape(c["camera_id"])}</figcaption>'
        f'<video class="cam" src="{escape(c["video_src"])}" muted preload="auto"></video></figure>'
        for c in cameras
    )
    metric_rows = "\n".join(
        f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>" for k, v in metrics.items()
    )
    legend = "\n".join(
        f'<li><span class="swatch" style="background:{global_id_hex(g)}"></span>'
        f"{escape(str(g))}</li>"
        for g in global_ids
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>RetailVision — Cross-Camera Review</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 1rem; background:#111; color:#eee; }}
 .cams {{ display:flex; gap:1rem; flex-wrap:wrap; }}
 figure {{ margin:0; }} video {{ width:380px; background:#000; border:1px solid #333; }}
 figcaption {{ font-size:.9rem; padding:.25rem 0; }}
 .controls {{ margin:1rem 0; }} button {{ font-size:1rem; padding:.4rem .9rem; }}
 table {{ border-collapse:collapse; margin-top:1rem; }} td {{ border:1px solid #333; padding:.2rem .6rem; }}
 .legend {{ list-style:none; padding:0; display:flex; gap:1rem; flex-wrap:wrap; }}
 .swatch {{ display:inline-block; width:14px; height:14px; margin-right:.3rem; border-radius:3px; vertical-align:middle; }}
</style></head>
<body>
 <h1>Cross-Camera ReID Review</h1>
 <div class="controls">
   <button id="play">Play</button><button id="pause">Pause</button>
   <button id="restart">Restart</button>
 </div>
 <div class="cams">{players}</div>
 <h2>Global ID legend</h2>
 <ul class="legend">{legend}</ul>
 <h2>Metrics</h2>
 <table>{metric_rows}</table>
<script>
 const vids = Array.from(document.querySelectorAll('video.cam'));
 const sync = () => {{ const t = vids[0]?.currentTime || 0;
   for (const v of vids.slice(1)) if (Math.abs(v.currentTime - t) > 0.15) v.currentTime = t;
   requestAnimationFrame(sync); }};
 document.getElementById('play').onclick = () => vids.forEach(v => v.play());
 document.getElementById('pause').onclick = () => vids.forEach(v => v.pause());
 document.getElementById('restart').onclick = () => vids.forEach(v => {{ v.currentTime = 0; v.play(); }});
 requestAnimationFrame(sync);
</script>
</body></html>"""


def render_review_page(output_path: str | Path, cameras: list[dict], metrics: dict,
                       global_ids: list[str]) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_review_html(cameras, metrics, global_ids), encoding="utf-8")
    return path
