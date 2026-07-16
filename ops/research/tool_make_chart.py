"""
tool_make_chart.py — QUEST chart tool (mcpjungle → flint-chart-mcp)

通过 mcpjungle MCP 网关调用 flint-chart-mcp 的 compile_chart 工具,
生成 ECharts spec, 包装成 ```echarts markdown 块嵌入研究报告。

原生部署, mcpjungle 在 localhost:8086。

环境变量:
    MCPJUNGLE_URL  默认 http://localhost:8086
"""
import os
import json
import re
import requests
from typing import Union

from qwen_agent.tools.base import BaseTool, register_tool

MCPJUNGLE_URL = os.environ.get("MCPJUNGLE_URL", "http://localhost:8086")


def _infer_semantic_types(data: list, x_field: str, y_field: str,
                          color_field: str = "") -> dict:
    """根据数据自动推断 Flint 语义类型。"""
    types = {}
    sample = data[0] if data else {}
    for field in [x_field, y_field, color_field]:
        if not field:
            continue
        val = sample.get(field)
        if isinstance(val, (int, float)):
            types[field] = "Quantity"
        elif isinstance(val, str):
            if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", val):
                types[field] = "Date"
            else:
                types[field] = "Nominal"
        else:
            types[field] = "Nominal"
    return types


def make_chart(title: str, chart_type: str, x_field: str, y_field: str,
               data: list, color_field: str = "",
               semantic_types: dict = None) -> dict:
    """通过 mcpjungle → flint-chart-mcp 生成 ECharts spec。

    返回 {"ok": bool, "markdown": "```echarts\\n{...}\\n```"}
    """
    if semantic_types is None:
        semantic_types = _infer_semantic_types(data, x_field, y_field, color_field)

    encodings = {"x": {"field": x_field}, "y": {"field": y_field}}
    if color_field:
        encodings["color"] = {"field": color_field}

    chart_spec = {
        "chartType": chart_type,
        "encodings": encodings,
        "baseSize": {"width": 560, "height": 380},
    }

    # mcpjungle /api/v0/tools/invoke: 参数 flat 放顶层 (不用 input 包装)
    payload = {
        "name": "flint-chart__compile_chart",
        "backend": "echarts",
        "chart_spec": chart_spec,
        "data": {"values": data},
        "semantic_types": semantic_types,
    }

    try:
        resp = requests.post(
            f"{MCPJUNGLE_URL}/api/v0/tools/invoke",
            json=payload, timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return {"ok": False, "error": f"mcpjungle invoke failed: {e}"}

    if result.get("isError"):
        err_text = result.get("content", [{}])[0].get("text", "unknown error")
        return {"ok": False, "error": f"flint-chart error: {err_text[:300]}"}

    try:
        text = result["content"][0]["text"]
        spec_obj = json.loads(text)
        echarts_spec = spec_obj.get("spec", {})
    except (KeyError, json.JSONDecodeError, IndexError) as e:
        return {"ok": False, "error": f"parse spec failed: {e}"}

    echarts_spec["title"] = {"text": title, "left": "center",
                             "textStyle": {"fontSize": 14}}
    markdown = f"```echarts\n{json.dumps(echarts_spec, ensure_ascii=False)}\n```"
    return {"ok": True, "markdown": markdown, "spec": echarts_spec}


def auto_chart_from_tables(report: str) -> str:
    """扫描报告中的 markdown 表格, 对含数值对比数据的自动生成图表。

    在 QuestAgent.run() 返回报告后调用。原生部署, mcpjungle 在 localhost。
    """
    if "```echarts" in report:
        return report

    tables = _extract_markdown_tables(report)
    if not tables:
        return report

    charts_inserted = 0
    for tbl in tables[:2]:
        chart_md = _table_to_chart(tbl)
        if chart_md:
            tbl_end = tbl["end_pos"]
            insert_point = report.find("\n\n", tbl_end)
            if insert_point < 0:
                insert_point = len(report)
            report = (report[:insert_point] + "\n\n" + chart_md +
                      report[insert_point:])
            charts_inserted += 1
            offset = len(chart_md) + 2
            for t in tables:
                t["start_pos"] += offset
                t["end_pos"] += offset

    return report


def _extract_markdown_tables(report: str) -> list:
    """提取报告中的 markdown 表格, 返回 [{header, rows, start_pos, end_pos}]。"""
    tables = []
    lines = report.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|"):
            start = i
            header_cells = [c.strip() for c in line.strip("|").split("|")]
            if i + 1 < len(lines) and re.match(r"^\|[\s:|-]+$", lines[i + 1].strip()):
                i += 2
                rows = []
                while (i < len(lines) and lines[i].strip().startswith("|")
                       and lines[i].strip().endswith("|")):
                    row_cells = [c.strip() for c in lines[i].strip("|").split("|")]
                    rows.append(row_cells)
                    i += 1
                if rows:
                    start_pos = sum(len(lines[j]) + 1 for j in range(start))
                    end_pos = sum(len(lines[j]) + 1 for j in range(i))
                    tables.append({
                        "header": header_cells, "rows": rows,
                        "start_pos": start_pos, "end_pos": end_pos,
                    })
            else:
                i += 1
        else:
            i += 1
    return tables


def _parse_number(s):
    """从文本中提取数值: '256 TFLOPS' → 256。跳过型号名里的数字。"""
    s = s.strip().replace(",", "").replace("，", "")
    if not s or s in ("—", "未披露", "N/A", "未知", "-"):
        return None
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(TFLOPS|PFLOPS|GB|TB|MB|GHz|MHz|亿元|千万|万元|万|W|%|fps|TOPS)",
        s, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    if re.match(r"^\d+(?:\.\d+)?$", s):
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _table_to_chart(tbl: dict) -> str:
    """将一个含数值的表格转为 ECharts 图表 markdown。"""
    header = tbl["header"]
    rows = tbl["rows"]
    if len(header) < 2 or len(rows) < 2:
        return ""

    col_numbers = {}
    for col_idx in range(len(header)):
        nums = []
        for row in rows:
            if col_idx < len(row):
                n = _parse_number(row[col_idx])
                if n is not None:
                    nums.append(n)
        if len(nums) >= len(rows) * 0.5:
            col_numbers[col_idx] = nums

    if not col_numbers:
        return ""

    x_col = 0
    x_field = header[x_col] if header[x_col] else "category"
    y_candidates = {c: n for c, n in col_numbers.items() if c != x_col}
    if not y_candidates:
        return ""
    y_col = max(y_candidates.keys(), key=lambda c: len(y_candidates[c]))
    y_field = header[y_col] if header[y_col] else "value"

    data = []
    for row in rows:
        if x_col < len(row) and y_col < len(row):
            x_val = row[x_col].strip()[:20]
            y_val = _parse_number(row[y_col])
            if y_val is not None:
                data.append({x_field: x_val, y_field: y_val})

    if len(data) < 2:
        return ""

    title = f"{y_field} 对比"
    r = make_chart(title=title, chart_type="Bar Chart",
                   x_field=x_field, y_field=y_field, data=data)
    if r.get("ok"):
        return r["markdown"]
    return ""
