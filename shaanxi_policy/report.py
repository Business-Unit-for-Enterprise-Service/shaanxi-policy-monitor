"""Public reports containing short policy evidence and original-source links."""

import html
import json
from pathlib import Path

from .extract import deadline_state

SITE = "https://business-unit-for-enterprise-service.github.io/shaanxi-policy-monitor"
LABELS = {"discovered": "新收录", "updated": "原文有更新", "baseline": "首次建档"}


def payload(state, health, instant):
    today = instant.date().isoformat()
    events = [e for e in state["events"] if e["date"] == today]
    records = []
    for record in state["records"].values():
        item = {k: v for k, v in record.items() if k != "content_hash"}
        item["deadline"] = deadline_state(record, instant.date())
        item["changes"] = list(dict.fromkeys(e["kind"] for e in events if e["url"] == record["url"]))
        records.append(item)
    records.sort(key=lambda r: (r["region"] != "西安市", not bool(r["changes"]), -(int((r["published_date"] or "0000-00-00").replace("-", "")))))
    enabled = [s for s in health if s["status"] != "disabled"]
    counts = {kind: len({e["url"] for e in events if e["kind"] == kind}) for kind in LABELS}
    counts.update(total=len(records), urgent=sum(r["deadline"]["status"] in {"7天内截止", "今日截止，时点需核实"} for r in records), sources=len(enabled), healthy=sum(s["status"] == "ok" for s in enabled), partial=sum(s["status"] == "partial" for s in enabled), failed=sum(s["status"] == "failed" for s in enabled))
    return {
        "schema_version": 1, "report_type": "shaanxi-policy-daily", "date": today,
        "generated_at": instant.isoformat(timespec="seconds"), "timezone": "Asia/Shanghai",
        "count_basis": "discovery_and_changes_on_report_date", "counts": counts,
        "coverage": "监测已列明官方栏目的首页及待处理队列；不代表全省全部政策。首次建档不计为当日新政策。",
        "sources": health, "policies": records, "report_url": f"{SITE}/daily/{today}.html",
    }


def esc(value):
    return html.escape(str(value or ""), quote=True)


def card(item):
    d = item["deadline"]
    tags = " ".join(f'<span class="tag">{esc(LABELS[x])}</span>' for x in item["changes"])
    highlights = "".join(f"<li>{esc(t)}</li>" for t in item["highlights"])
    cutoff = f'<div class="deadline">{esc(d["status"])} {esc(d["date"])}</div>'
    evidence = f'<p class="evidence">截止依据：{esc(d["evidence"])}' + ('（年份按发布日期推定）' if d.get("year_inferred") else '') + '</p>' if d["evidence"] else ""
    details = "".join(f'<li>{esc(x["kind"])} · {esc(x["date"])}：{esc(x["evidence"])}</li>' for x in item["dates"] if x["kind"] != "企业申报截止")
    attachments = "".join(f'<li><a href="{esc(a["url"])}" target="_blank" rel="noopener noreferrer">{esc(a["title"])}</a></li>' for a in item["attachments"])
    extras = f'<details><summary>其他日期与附件</summary><ul>{details}{attachments}</ul></details>' if details or attachments else ""
    return f'''<article class="policy" data-region="{esc(item['region'])}" data-category="{esc(item['category'])}" data-changed="{'yes' if item['changes'] else 'no'}">
      <div class="eyebrow">{esc(item['region'])} · {esc(item['category'])} {tags}</div>
      <h3><a href="{esc(item['url'])}" target="_blank" rel="noopener noreferrer">{esc(item['title'])} ↗</a></h3>
      <p class="meta">{esc(item['source_name'])} · 发布 {esc(item['published_date'] or '待核实')} · {esc(item['publication_basis'])}</p>
      {cutoff}<ul class="highlights">{highlights}</ul>{evidence}{extras}
      <p class="meta">首次收录 {esc(item['first_seen_at'][:10])} · 最近核对 {esc(item['last_checked_at'][:10])}</p>
    </article>'''


def render(report, archive_dates):
    c = report["counts"]
    cards = "".join(card(r) for r in report["policies"])
    source_rows = "".join(f'<tr><td><a href="{esc(s["url"])}">{esc(s["name"])}</a></td><td>{esc({"ok":"已完成", "partial":"部分完成", "failed":"采集失败", "disabled":"待接入"}[s["status"]])}</td><td>{s["checked"]} / {s["pending"]}</td><td>{esc(s.get("message"))}</td></tr>' for s in report["sources"])
    archives = " · ".join(f'<a href="{SITE}/daily/{d}.html">{d}</a>' for d in archive_dates)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>陕西政策日报 · {report['date']}</title><style>
      :root{{--ink:#163c39;--muted:#55716d;--line:#d8e5dd;--paper:#f5f8f2;--accent:#116b55}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,"Microsoft YaHei",sans-serif;line-height:1.65}}main{{max-width:1160px;margin:auto;padding:48px 28px}}a{{color:inherit;text-decoration:none}}a:hover{{text-decoration:underline}}header{{border-bottom:2px solid var(--ink);padding-bottom:28px}}.eyebrow{{font-size:12px;letter-spacing:1px;color:var(--accent);font-weight:650}}h1{{font-size:42px;letter-spacing:-1px;margin:9px 0}}header p{{max-width:740px;color:var(--muted)}}.date{{float:right;font-variant-numeric:tabular-nums}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}}.stat{{border:1px solid var(--line);border-radius:10px;padding:20px;background:#fff}}.stat b{{font-size:32px;display:block}}.stat span{{color:var(--muted);font-size:13px}}.notice{{padding:16px 20px;background:#e8f0e6;border-left:3px solid var(--accent);font-size:14px}}.controls{{display:flex;gap:10px;flex-wrap:wrap;margin:28px 0 18px}}input,select{{font:inherit;border:1px solid var(--line);border-radius:6px;background:white;padding:10px;color:var(--ink)}}input{{flex:1;min-width:190px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.policy{{padding:23px;border:1px solid var(--line);border-radius:10px;background:white;overflow-wrap:anywhere}}h3{{font-size:18px;line-height:1.65;margin:10px 0}}.meta{{font-size:12px;color:var(--muted)}}.tag{{background:#e9f1d9;padding:3px 6px;border-radius:3px;letter-spacing:0}}.deadline{{font-size:13px;font-weight:650;color:#916125;margin:12px 0}}.highlights,.evidence,details{{font-size:13px;color:#3d5753}}.highlights{{padding-left:20px}}.evidence{{border-top:1px solid var(--line);padding-top:12px}}summary{{cursor:pointer}}h2{{font-size:23px;margin-top:38px}}.table-wrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{text-align:left;padding:13px 10px;border-bottom:1px solid var(--line)}}td:first-child{{min-width:190px}}footer{{margin-top:40px;font-size:12px;color:var(--muted)}}[hidden]{{display:none!important}}@media(max-width:720px){{main{{padding:28px 18px}}h1{{font-size:32px}}.date{{float:none;display:block;margin-top:10px}}.stats{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
      </style></head><body><main><header><div class="eyebrow">企业政策观察 / SHAANXI <span class="date">{report['date']} · 北京时间</span></div><h1>陕西政策日报<span style="color:#718a65">，西安优先。</span></h1><p>汇集企业申报、补贴奖励、科技创新与产业扶持政策。每条信息连接官方原文，申报时间保留可核对的依据。</p></header>
      <section class="stats"><div class="stat"><b>{c['discovered']}</b><span>今日新收录 · 按发现时间</span></div><div class="stat"><b>{c['updated']}</b><span>今日发现原文更新</span></div><div class="stat"><b>{c['urgent']}</b><span>已识别的 7 天内截止事项</span></div><div class="stat"><b>{c['total']}</b><span>累计政策 · 首次建档 {c['baseline']}</span></div></section>
      <p class="notice">栏目状态：{c['healthy']} 个完成、{c['partial']} 个部分完成、{c['failed']} 个失败，共 {c['sources']} 个启用栏目。{esc(report['coverage'])}<br>“尚未到原文截止日期”仅为日期比较；是否受理、是否延期及企业资格均须查阅官方原文。附件仅提供链接，未自动解析。</p>
      <div class="controls"><input id="query" aria-label="搜索政策" placeholder="搜索企业、补贴、数字化…"><select id="region" aria-label="筛选区域"><option value="">全部区域</option><option>西安市</option><option>陕西省</option></select><select id="changed" aria-label="筛选变化"><option value="">全部已收录政策</option><option value="yes">今日收录或更新</option></select></div>
      <section class="grid">{cards}</section><p id="empty" hidden>没有符合当前筛选条件的政策。</p>
      <h2>采集覆盖与运行状态</h2><div class="table-wrap"><table><thead><tr><th>官方栏目</th><th>状态</th><th>已核对 / 排队</th><th>说明</th></tr></thead><tbody>{source_rows}</tbody></table></div>
      <h2>日报归档</h2><p>{archives}</p><footer>生成时间 {esc(report['generated_at'])} · <a href="https://github.com/Business-Unit-for-Enterprise-Service/shaanxi-policy-monitor">项目与采集范围</a><br>自动筛选可能遗漏，摘录不构成完整申报条件。以官方原文及最新通知为准。</footer></main><script>
      const controls=['query','region','changed'].map(id=>document.getElementById(id));function filter(){{let count=0;const [q,r,c]=controls.map(x=>x.value.trim().toLowerCase());document.querySelectorAll('.policy').forEach(el=>{{el.hidden=!!((q&&!el.textContent.toLowerCase().includes(q))||(r&&el.dataset.region!==r)||(c&&el.dataset.changed!==c));if(!el.hidden)count++}});document.getElementById('empty').hidden=count>0}}controls.forEach(el=>el.addEventListener('input',filter));
      </script></body></html>'''


def write_report(report, output):
    output = Path(output)
    daily = output / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    dates = sorted({p.stem for p in daily.glob("????-??-??.json")} | {report["date"]}, reverse=True)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (daily / f"{report['date']}.json").write_text(encoded, encoding="utf-8")
    (output / "latest.json").write_text(encoded, encoding="utf-8")
    page = render(report, dates)
    (daily / f"{report['date']}.html").write_text(page, encoding="utf-8")
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / ".nojekyll").touch()
