from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .instruction_candidates import build_instruction_candidates
from .redaction import redact_sensitive_text, redact_tree


RUNTIME_START = "<!-- ai-dev-runtime:start -->"
RUNTIME_END = "<!-- ai-dev-runtime:end -->"
LEGACY_MARKER = "<!-- ai-dev-token-economics-injected -->"

DISPLAY_NAMES = {
    "prompt_duplication": "Prompt Sent Twice",
    "error_dump": "Full Error Dump",
    "file_thrash": "Files Re-read Repeatedly",
    "repeated_constraint": "Repeated Constraint",
    "correction_spiral": "Correction Spiral",
    "vague_opener": "Vague Opening Prompt",
    "constraint_missing_scaffold": "Missing Scaffolding",
    "convergence_gate1_miss": "Slow to Start Productive Work",
    "convergence_gate2_failure": "Corrections Interrupted Execution",
    "convergence_gate3_inconclusive": "Unclear Session Ending",
    "abandoned_session": "Session Ended Mid-correction",
    "scope_creep": "Task Scope Kept Expanding",
}


def _project_rows(per_session: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"sessions": 0, "cost": 0.0, "recoverable": 0.0, "tokens": 0}
    )
    for session in per_session:
        project = str(session.get("project_folder") or "unknown")
        cost = float((session.get("session_features") or {}).get("total_cost", 0.0) or 0.0)
        recoverable = min(cost, float(session.get("recoverable_cost_total_usd", 0.0) or 0.0))
        grouped[project]["sessions"] += 1
        grouped[project]["cost"] += cost
        grouped[project]["recoverable"] += recoverable
        grouped[project]["tokens"] += int((session.get("session_features") or {}).get("total_tokens", 0) or 0)
    rows = []
    for project, values in grouped.items():
        cost = float(values["cost"])
        recoverable = float(values["recoverable"])
        rows.append(
            {
                "project": project,
                "sessions": int(values["sessions"]),
                "cost": round(cost, 6),
                "recoverable": round(recoverable, 6),
                "tokens": int(values["tokens"]),
                "waste_pct": round((recoverable / cost * 100.0) if cost > 0 else 0.0, 2),
            }
        )
    return sorted(rows, key=lambda row: (-float(row["cost"]), -int(row["tokens"]), str(row["project"])))


def _flag_rows(per_session: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"occurrences": 0, "sessions": set(), "recoverable": 0.0, "description": "", "remedy": ""}
    )
    for session in per_session:
        session_id = str(session.get("session_id") or "unknown")
        session_flags = session.get("flags") or []
        raw_recoverable = sum(float(flag.get("recoverable_cost_usd", 0.0) or 0.0) for flag in session_flags)
        capped_recoverable = float(session.get("recoverable_cost_total_usd", 0.0) or 0.0)
        scale = min(1.0, capped_recoverable / raw_recoverable) if raw_recoverable > 0 else 1.0
        for flag in session_flags:
            flag_id = str(flag.get("flag_id") or "unknown")
            row = grouped[flag_id]
            row["occurrences"] += int(flag.get("occurrences", 0) or 0)
            row["sessions"].add(session_id)
            row["recoverable"] += float(flag.get("recoverable_cost_usd", 0.0) or 0.0) * scale
            row["description"] = str(flag.get("description") or row["description"])
            row["remedy"] = str(flag.get("remedy") or row["remedy"])
    return sorted(
        [
            {
                "flag_id": flag_id,
                "name": DISPLAY_NAMES.get(flag_id, flag_id.replace("_", " ").title()),
                "occurrences": int(row["occurrences"]),
                "sessions": len(row["sessions"]),
                "recoverable": round(float(row["recoverable"]), 6),
                "description": row["description"],
                "remedy": row["remedy"],
            }
            for flag_id, row in grouped.items()
        ],
        key=lambda row: (-float(row["recoverable"]), -int(row["occurrences"]), str(row["flag_id"])),
    )


def _session_rows(per_session: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for session in per_session:
        flags = []
        session_flags = session.get("flags") or []
        raw_recoverable = sum(float(flag.get("recoverable_cost_usd", 0.0) or 0.0) for flag in session_flags)
        capped_recoverable = float(session.get("recoverable_cost_total_usd", 0.0) or 0.0)
        scale = min(1.0, capped_recoverable / raw_recoverable) if raw_recoverable > 0 else 1.0
        for flag in session_flags:
            flags.append(
                {
                    "flag_id": str(flag.get("flag_id") or "unknown"),
                    "name": DISPLAY_NAMES.get(
                        str(flag.get("flag_id") or "unknown"),
                        str(flag.get("flag_id") or "unknown").replace("_", " ").title(),
                    ),
                    "severity": str(flag.get("severity") or "unknown"),
                    "occurrences": int(flag.get("occurrences", 0) or 0),
                    "deduction": float(flag.get("total_deduction_points", 0.0) or 0.0),
                    "recoverable": float(flag.get("recoverable_cost_usd", 0.0) or 0.0) * scale,
                    "description": str(flag.get("description") or ""),
                    "remedy": str(flag.get("remedy") or ""),
                    "evidence": [
                        {
                            "turn_index": int(item.get("turn_index", 0) or 0),
                            "timestamp": str(item.get("timestamp") or ""),
                            "snippet": str(item.get("snippet") or ""),
                            "note": str(item.get("note") or ""),
                        }
                        for item in (flag.get("evidence") or [])[:8]
                    ],
                }
            )
        features = session.get("session_features") or {}
        scores = session.get("scores") or {}
        convergence = session.get("convergence") or {}
        rows.append(
            {
                "session_id": str(session.get("session_id") or "unknown"),
                "project": str(session.get("project_folder") or "unknown"),
                "score": float(scores.get("composite", 0.0) or 0.0),
                "shape": str(convergence.get("shape") or "unknown"),
                "cost": float(features.get("total_cost", 0.0) or 0.0),
                "recoverable": float(session.get("recoverable_cost_total_usd", 0.0) or 0.0),
                "turns": int(features.get("total_turns", 0) or 0),
                "tokens": int(features.get("total_tokens", 0) or 0),
                "flags": flags,
            }
        )
    return sorted(
        rows,
        key=lambda row: (-float(row["cost"]), -int(row["tokens"]), str(row["session_id"])),
    )


def build_html_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    v2 = report.get("v2") or {}
    rollup = v2.get("project_rollup") or {}
    per_session = v2.get("per_session_v2") or []
    total_cost = float(report.get("total_cost_derived", 0.0) or 0.0)
    recoverable = float(rollup.get("recoverable_cost_total_usd", 0.0) or 0.0)
    total_tokens = sum(
        int((session.get("session_features") or {}).get("total_tokens", 0) or 0)
        for session in per_session
    )
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "score": float(rollup.get("composite", 0.0) or 0.0),
            "sessions": int(rollup.get("session_count", 0) or 0),
            "total_cost": total_cost,
            "recoverable": recoverable,
            "recoverable_pct": (recoverable / total_cost * 100.0) if total_cost > 0 else 0.0,
            "cache_savings": float((report.get("session_features") or {}).get("estimated_cache_savings", 0.0) or 0.0),
            "total_tokens": total_tokens,
            "cost_available": total_cost > 0.0,
            "source": str(report.get("source") or "claude"),
        },
        "projects": _project_rows(per_session),
        "flags": _flag_rows(per_session),
        "sessions": _session_rows(per_session),
        "instruction_candidates": build_instruction_candidates(report),
    }
    return redact_tree(payload)


def _json_for_script(payload: Dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


_INSIGHTS_CSS = r"""
#ai-dev-token-economics{margin:40px 0;padding:24px;border:1px solid #dbeafe;border-radius:14px;background:#f8fbff}
#ai-dev-token-economics *{box-sizing:border-box}.ai-dev-kicker{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#2563eb}
.ai-dev-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}.ai-dev-card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px}
.ai-dev-value{font-size:24px;font-weight:700}.ai-dev-label{font-size:12px;color:#64748b}.ai-dev-table-wrap{overflow-x:auto}.ai-dev-table{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0 24px}
.ai-dev-table th,.ai-dev-table td{text-align:left;padding:9px;border-bottom:1px solid #e2e8f0;vertical-align:top}.ai-dev-table .num{text-align:right}.ai-dev-finding{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px;margin:8px 0}
.ai-dev-finding summary{cursor:pointer;font-weight:650}.ai-dev-muted{color:#64748b;font-size:12px}.ai-dev-evidence{margin:8px 0 0;padding-left:20px}.ai-dev-code{white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1f5f9;border-radius:6px;padding:10px}
.ai-dev-copy{border:1px solid #cbd5e1;background:white;border-radius:6px;padding:5px 9px;cursor:pointer}.ai-dev-warning{padding:10px;border-radius:8px;background:#fffbeb;color:#92400e}
""".strip()


_INSIGHTS_JS = r"""
(() => {
  const dataNode = document.getElementById('ai-dev-data');
  if (!dataNode || document.getElementById('ai-dev-token-economics')) return;
  const data = JSON.parse(dataNode.textContent);
  const el = (tag, cls, text) => { const node=document.createElement(tag); if(cls) node.className=cls; if(text!==undefined) node.textContent=String(text); return node; };
  const money = value => '$' + Number(value || 0).toFixed(2);
  const section = el('section'); section.id='ai-dev-token-economics';
  section.append(el('div','ai-dev-kicker','Local agent-session analysis'), el('h2','', 'Token Economics'));
  const intro=el('p','ai-dev-muted','Estimated avoidable spend is heuristic and should be interpreted with the evidence below, not as measured savings.'); section.append(intro);
  const cards=el('div','ai-dev-grid');
  [['Score',Math.round(data.summary.score)+'/100'],['Sessions',data.summary.sessions],['Total spend',money(data.summary.total_cost)],['Estimated avoidable',money(data.summary.recoverable)],['Avoidable share',Number(data.summary.recoverable_pct||0).toFixed(0)+'%']].forEach(([label,value])=>{const card=el('div','ai-dev-card');card.append(el('div','ai-dev-value',value),el('div','ai-dev-label',label));cards.append(card);});
  section.append(cards);
  const table=(headers, rows) => { const wrap=el('div','ai-dev-table-wrap'), t=el('table','ai-dev-table'), head=el('thead'), hr=el('tr'); headers.forEach(h=>hr.append(el('th',h.num?'num':'',h.label))); head.append(hr); const body=el('tbody'); rows.forEach(values=>{const tr=el('tr');values.forEach((v,i)=>tr.append(el('td',headers[i].num?'num':'',v)));body.append(tr);});t.append(head,body);wrap.append(t);return wrap; };
  section.append(el('h3','', 'Project cost summary'));
  section.append(table([{label:'Project'},{label:'Sessions',num:true},{label:'Cost',num:true},{label:'Estimated avoidable',num:true},{label:'Share',num:true}],data.projects.map(p=>[p.project,p.sessions,money(p.cost),money(p.recoverable),Number(p.waste_pct).toFixed(1)+'%'])));
  section.append(el('h3','', 'Findings and evidence'));
  if(!data.sessions.length) section.append(el('p','ai-dev-muted','No sessions were available.'));
  data.sessions.forEach(session=>{const details=el('details','ai-dev-finding'), summary=el('summary','',session.project+' · '+session.session_id.slice(0,12)+' · '+Math.round(session.score)+'/100 · '+money(session.cost));details.append(summary,el('p','ai-dev-muted',session.shape+' · '+session.turns+' turns · '+session.tokens.toLocaleString()+' incremental tokens'));
    if(!session.flags.length) details.append(el('p','ai-dev-muted','No named anti-pattern fired.'));
    session.flags.forEach(flag=>{const fd=el('details','ai-dev-finding'), fs=el('summary','',flag.name+' · -'+Number(flag.deduction).toFixed(1)+' points · '+money(flag.recoverable));fd.append(fs,el('p','',flag.description),el('p','',flag.remedy));if(flag.evidence.length){const list=el('ul','ai-dev-evidence');flag.evidence.forEach(ev=>{const parts=[ev.note,ev.snippet].filter(Boolean);list.append(el('li','',('Turn '+(ev.turn_index||'?')+': '+(parts.join(' — ')||'Evidence recorded'))));});fd.append(list);}details.append(fd);});section.append(details);});
  section.append(el('h3','', 'Suggested project instructions'));
  if(!data.instruction_candidates.length) section.append(el('p','ai-dev-muted','No instruction candidate met the promotion threshold.'));
  data.instruction_candidates.forEach(candidate=>{const box=el('div','ai-dev-finding');box.append(el('strong','',candidate.title),el('p','ai-dev-code',candidate.instruction),el('p','ai-dev-muted',(candidate.project?'Project: '+candidate.project+'. ':'')+candidate.reason+' Evidence: '+candidate.sessions+' session(s), confidence '+candidate.confidence+'.'));const copy=el('button','ai-dev-copy','Copy instruction');copy.type='button';copy.addEventListener('click',()=>navigator.clipboard.writeText(candidate.instruction).then(()=>{copy.textContent='Copied';setTimeout(()=>copy.textContent='Copy instruction',1500);}));box.append(copy);section.append(box);});
  const friction=document.getElementById('section-friction'); if(friction && friction.parentNode) friction.parentNode.insertBefore(section,friction); else (document.querySelector('.container')||document.body).append(section);
  const nav=document.querySelector('nav'); if(nav){const link=el('a','', 'Token Economics');link.href='#ai-dev-token-economics';nav.append(link);}
  const labels=[...document.querySelectorAll('.stat-label')], marker=labels.find(node=>node.textContent.trim()==='Msgs/Day'); const stats=marker&&marker.closest('.stats-row'); if(stats){[['Spend',money(data.summary.total_cost)],['Avoidable',money(data.summary.recoverable)],['Efficiency',Math.round(data.summary.score)+'/100']].forEach(([label,value])=>{const card=el('div','stat');card.append(el('div','stat-value',value),el('div','stat-label',label));stats.append(card);});}
})();
""".strip()


def build_insights_runtime_block(report: Dict[str, Any]) -> str:
    payload = _json_for_script(build_html_payload(report))
    return "\n".join(
        [
            RUNTIME_START,
            f'<script id="ai-dev-data" type="application/json">{payload}</script>',
            f'<style id="ai-dev-styles">{_INSIGHTS_CSS}</style>',
            f'<script id="ai-dev-runtime">{_INSIGHTS_JS}</script>',
            RUNTIME_END,
        ]
    )


def augment_insights_html(report: Dict[str, Any], html_path: Path) -> None:
    if not html_path.exists():
        raise FileNotFoundError(f"Insights HTML file not found: {html_path}")
    content = html_path.read_text(encoding="utf-8")
    if LEGACY_MARKER in content and RUNTIME_START not in content:
        raise ValueError(
            "This report contains the legacy structural injection. Regenerate a fresh Claude Insights report "
            "before applying the safe runtime augmentation."
        )
    content = re.sub(
        re.escape(RUNTIME_START) + r".*?" + re.escape(RUNTIME_END),
        "",
        content,
        flags=re.DOTALL,
    )
    block = build_insights_runtime_block(report)
    if "</body>" in content:
        content = content.replace("</body>", f"{block}\n</body>", 1)
    else:
        content = f"{content}\n{block}\n"
    html_path.write_text(content, encoding="utf-8")


_STANDALONE_CSS = """
:root{color-scheme:light;--ink:#172033;--muted:#667085;--line:#d9e2f0;--blue:#2855d9;--paper:#fff;--wash:#f5f8ff}*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}main{max-width:1120px;margin:auto;padding:40px 24px 80px}h1{font-size:36px;margin:.2em 0}h2{margin-top:42px}header p{color:var(--muted);max-width:760px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:24px 0}.card,details{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px}.value{font-size:26px;font-weight:750}.label,.muted{font-size:13px;color:var(--muted)}table{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--line)}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.num{text-align:right}details{margin:10px 0}summary{cursor:pointer;font-weight:700}.finding{margin:12px 0;padding:12px;border-left:4px solid var(--blue);background:#f8faff}.evidence{background:#f1f4f9;border-radius:8px;padding:10px;white-space:pre-wrap;overflow-wrap:anywhere}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#e8efff;color:#2448a8;font-size:12px}.warning{background:#fff8e8;border:1px solid #f5d58a;border-radius:10px;padding:12px}.copy{border:1px solid #b7c4d8;background:#fff;border-radius:7px;padding:6px 10px;cursor:pointer}@media(max-width:700px){.table-wrap{overflow-x:auto}h1{font-size:30px}}
""".strip()


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _evidence_text(item: Dict[str, Any]) -> str:
    parts = [str(item.get("note") or "").strip(), str(item.get("snippet") or "").strip()]
    return " — ".join(part for part in parts if part) or "Evidence recorded"


def build_standalone_html(report: Dict[str, Any]) -> str:
    data = build_html_payload(report)
    summary = data["summary"]
    cost_available = bool(summary["cost_available"])
    if cost_available:
        project_headers = "<th>Project</th><th class='num'>Sessions</th><th class='num'>Tokens</th><th class='num'>Cost</th><th class='num'>Estimated avoidable</th><th class='num'>Share</th>"
        project_rows = "".join(
            "<tr>"
            f"<td>{_e(row['project'])}</td><td class='num'>{row['sessions']}</td><td class='num'>{row['tokens']:,}</td>"
            f"<td class='num'>${row['cost']:.2f}</td><td class='num'>${row['recoverable']:.2f}</td>"
            f"<td class='num'>{row['waste_pct']:.1f}%</td></tr>"
            for row in data["projects"]
        ) or "<tr><td colspan='6'>No project data.</td></tr>"
    else:
        project_headers = "<th>Project</th><th class='num'>Sessions</th><th class='num'>Tokens</th>"
        project_rows = "".join(
            f"<tr><td>{_e(row['project'])}</td><td class='num'>{row['sessions']}</td><td class='num'>{row['tokens']:,}</td></tr>"
            for row in data["projects"]
        ) or "<tr><td colspan='3'>No project data.</td></tr>"

    session_sections: List[str] = []
    for session in data["sessions"]:
        findings: List[str] = []
        for flag in session["flags"]:
            evidence = "".join(
                f"<li><strong>Turn {_e(item['turn_index'] or '?')}</strong> — {_e(_evidence_text(item))}</li>"
                for item in flag["evidence"]
            ) or "<li>No text excerpt retained.</li>"
            findings.append(
                "<div class='finding'>"
                f"<strong>{_e(flag['name'])}</strong> <span class='pill'>{_e(flag['severity'])}</span>"
                f"<p>{_e(flag['description'])}</p><p><strong>Remedy:</strong> {_e(flag['remedy'])}</p>"
                f"<p class='muted'>Deduction: {flag['deduction']:.1f} points"
                + (f" · Estimated avoidable: ${flag['recoverable']:.2f}" if cost_available else "")
                + "</p>"
                f"<ul>{evidence}</ul></div>"
            )
        session_sections.append(
            "<details>"
            f"<summary>{_e(session['project'])} · {_e(session['session_id'][:16])} · {session['score']:.0f}/100"
            + (f" · ${session['cost']:.2f}" if cost_available else "")
            + "</summary>"
            f"<p class='muted'>{_e(session['shape'])} · {session['turns']} turns · {session['tokens']:,} incremental tokens</p>"
            + ("".join(findings) or "<p>No named anti-pattern fired.</p>")
            + "</details>"
        )

    candidates: List[str] = []
    for candidate in data["instruction_candidates"]:
        project_line = (
            f"<p class='muted'>Project: {_e(candidate['project'])}</p>"
            if candidate.get("project")
            else ""
        )
        candidates.append(
            "<div class='card'>"
            f"<h3>{_e(candidate['title'])}</h3><pre class='evidence'><code>{_e(candidate['instruction'])}</code></pre>"
            f"{project_line}"
            f"<p>{_e(candidate['reason'])}</p><p class='muted'>{candidate['sessions']} session(s) · {candidate['occurrences']} occurrence(s) · {_e(candidate['confidence'])} confidence</p>"
            f"<button class='copy' type='button' data-copy='{_e(candidate['instruction'])}'>Copy instruction</button></div>"
        )

    source_name = "Codex" if summary["source"] == "codex" else "Claude Code"
    cost_cards = (
        f'<div class="card"><div class="value">${summary["total_cost"]:.2f}</div><div class="label">Total spend</div></div>'
        f'<div class="card"><div class="value">${summary["recoverable"]:.2f}</div><div class="label">Estimated avoidable</div></div>'
        if cost_available
        else f'<div class="card"><div class="value">{summary["total_tokens"]:,}</div><div class="label">Analyzed tokens</div></div>'
    )
    interpretation = (
        '“Estimated avoidable” associates spend with detected friction. It is not a measured counterfactual or guaranteed saving.'
        if cost_available
        else 'Token usage is read from local Codex rollouts. Dollar estimates are omitted unless a matching pricing profile is supplied.'
    )
    instruction_target = "<code>AGENTS.md</code>" if summary["source"] == "codex" else "<code>AGENTS.md</code> or <code>CLAUDE.md</code>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{source_name} Session Evidence Report</title><style>{_STANDALONE_CSS}</style></head>
<body><main><header><span class="pill">Local analysis</span><h1>AI Coding Session Evidence Report</h1>
<p>Evidence drill-down for {_e(source_name)} sessions. Scores are heuristic; inspect the evidence before changing behavior.</p>
<p class="muted">Generated {_e(data['generated_at'])} · Schema {data['schema_version']}</p></header>
<section class="grid"><div class="card"><div class="value">{summary['score']:.0f}/100</div><div class="label">Efficiency score</div></div>
<div class="card"><div class="value">{summary['sessions']}</div><div class="label">Sessions</div></div>
{cost_cards}</section>
<p class="warning"><strong>Interpretation:</strong> {_e(interpretation)}</p>
<h2>Project summary</h2><div class="table-wrap"><table><thead><tr>{project_headers}</tr></thead><tbody>{project_rows}</tbody></table></div>
<h2>Session evidence</h2>{''.join(session_sections) or '<p>No sessions were available.</p>'}
<h2>Suggested project instructions</h2><p>Review before copying into {instruction_target}. The analyzer never modifies project instruction files automatically.</p>
<div class="grid">{''.join(candidates) or '<div class="card">No instruction candidate met the promotion threshold.</div>'}</div>
</main><script>document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',()=>navigator.clipboard.writeText(button.dataset.copy).then(()=>{{button.textContent='Copied';setTimeout(()=>button.textContent='Copy instruction',1500);}})));</script></body></html>"""


def export_standalone_html(report: Dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_standalone_html(report), encoding="utf-8")
