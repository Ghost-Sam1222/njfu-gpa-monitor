from __future__ import annotations

from html import escape
from pathlib import Path

from models import Grade


def _number(value: str) -> float | None:
    try:
        return float(value.strip())
    except (AttributeError, TypeError, ValueError):
        return None


def weighted_average(grades: list[Grade], field: str) -> float | None:
    total = 0.0
    credits = 0.0
    for grade in grades:
        credit = _number(grade.credit)
        value = _number(getattr(grade, field))
        if credit is None or credit <= 0 or value is None:
            continue
        total += value * credit
        credits += credit
    return total / credits if credits else None


def mask_student_id(student_id: str) -> str:
    if len(student_id) < 7:
        return "未显示"
    return f"{student_id[:4]}****{student_id[-3:]}"


def _metric(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f}"


def render_transcript(grades: list[Grade], semester: str, student_id: str = "") -> str:
    average_score = weighted_average(grades, "score")
    average_gpa = weighted_average(grades, "gpa")
    rows = []
    for grade in grades:
        score_number = _number(grade.score)
        gpa_number = _number(grade.gpa)
        credit_number = _number(grade.credit)
        rows.append(
            "<tr>"
            f'<td data-sort="{escape(grade.course_name)}"><strong>{escape(grade.course_name)}</strong></td>'
            f'<td data-sort="{escape(grade.course_code)}">{escape(grade.course_code or "--")}</td>'
            f'<td data-sort="{credit_number if credit_number is not None else -1}">{escape(grade.credit or "--")}</td>'
            f'<td data-sort="{escape(grade.course_type)}">{escape(grade.course_type or "--")}</td>'
            f'<td data-sort="{score_number if score_number is not None else -1}"><span class="score">{escape(grade.score)}</span></td>'
            f'<td data-sort="{gpa_number if gpa_number is not None else -1}">{escape(grade.gpa or "--")}</td>'
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>NJFU {escape(semester)} 成绩单</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#f5f5f7; --surface:#fff; --text:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7; --blue:#0071e3; --green:#16883e; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif; letter-spacing:0; }}
    main {{ width:min(1080px,100%); margin:0 auto; padding:32px 20px 56px; }}
    header {{ padding:32px; border-radius:8px; color:white; background:#1d1d1f; }}
    .eyebrow {{ margin:0 0 8px; color:#b8e4c4; font-size:13px; font-weight:700; }}
    h1 {{ margin:0; font-size:32px; line-height:1.15; }}
    .meta {{ margin:12px 0 0; color:#d2d2d7; }}
    .metrics {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; margin-top:28px; background:#48484a; border:1px solid #48484a; }}
    .metric {{ min-width:0; padding:18px; background:#2c2c2e; }}
    .metric span {{ display:block; color:#aeaeb2; font-size:12px; }}
    .metric strong {{ display:block; margin-top:4px; font-size:24px; }}
    section {{ margin-top:30px; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin-bottom:12px; }}
    h2 {{ margin:0; font-size:22px; }}
    .hint {{ margin:0; color:var(--muted); font-size:13px; }}
    .table-wrap {{ overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; }}
    table {{ width:100%; min-width:760px; border-collapse:collapse; }}
    th,td {{ padding:15px 16px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }}
    th {{ color:var(--muted); font-size:12px; font-weight:700; background:var(--surface); cursor:pointer; user-select:none; }}
    th:hover {{ color:var(--blue); }}
    tbody tr:last-child td {{ border-bottom:0; }}
    tbody tr:hover {{ background:color-mix(in srgb,var(--blue) 5%,var(--surface)); }}
    .score {{ color:var(--green); font-weight:800; }}
    footer {{ margin-top:18px; color:var(--muted); font-size:12px; }}
    @media(max-width:640px) {{ main{{padding:16px 12px 40px}} header{{padding:24px 20px}} h1{{font-size:27px}} .metrics{{grid-template-columns:1fr}} .section-head{{align-items:flex-start;flex-direction:column}} }}
    @media(prefers-color-scheme:dark) {{ :root{{--bg:#000;--surface:#1c1c1e;--text:#f5f5f7;--muted:#aeaeb2;--line:#38383a;--blue:#2997ff;--green:#46c466}} header{{background:#1c1c1e;border:1px solid var(--line)}} }}
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">南京林业大学 · 学期成绩</p>
    <h1>{escape(semester)} 成绩单</h1>
    <p class="meta">学号 {escape(mask_student_id(student_id))}</p>
    <div class="metrics">
      <div class="metric"><span>平均成绩（学分加权）</span><strong>{_metric(average_score)}</strong></div>
      <div class="metric"><span>平均绩点（学分加权）</span><strong>{_metric(average_gpa)}</strong></div>
      <div class="metric"><span>已出成绩</span><strong>{len(grades)} 门</strong></div>
    </div>
  </header>
  <section>
    <div class="section-head"><h2>课程明细</h2><p class="hint">在浏览器中点击表头可排序</p></div>
    <div class="table-wrap">
      <table id="transcript">
        <thead><tr><th>课程</th><th>课程编号</th><th>学分</th><th>课程属性</th><th>成绩</th><th>绩点</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </section>
  <footer>由 NJFU GPA Monitor 生成。成绩与账户信息不会写入公开仓库。</footer>
</main>
<script>
  document.querySelectorAll('th').forEach((th,index)=>th.addEventListener('click',()=>{{
    const body=document.querySelector('#transcript tbody');
    const rows=[...body.rows];
    const ascending=th.dataset.direction!=='asc';
    document.querySelectorAll('th').forEach(item=>delete item.dataset.direction);
    th.dataset.direction=ascending?'asc':'desc';
    rows.sort((a,b)=>{{
      const av=a.cells[index].dataset.sort||a.cells[index].textContent.trim();
      const bv=b.cells[index].dataset.sort||b.cells[index].textContent.trim();
      const an=Number(av),bn=Number(bv);
      const result=Number.isNaN(an)||Number.isNaN(bn)?av.localeCompare(bv,'zh-CN'):an-bn;
      return ascending?result:-result;
    }});
    rows.forEach(row=>body.appendChild(row));
  }}));
</script>
</body>
</html>"""


def write_transcript(path: Path, grades: list[Grade], semester: str, student_id: str = "") -> str:
    html = render_transcript(grades, semester, student_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html
