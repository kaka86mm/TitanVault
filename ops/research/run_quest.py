#!/usr/bin/env python3
"""
run_quest.py — QUEST deep research agent 本地运行入口

用法:
    ~/quest-venv/bin/python run_quest.py "AMD Strix Halo 的推理性能如何?"

输入一个问题, QUEST agent 自主搜索→阅读→总结→报告, 输出 markdown 研究报告。

依赖:
    - QUEST-9B 跑在 llama.cpp :8085 (OpenAI 兼容)
    - LiteLLM :4000 (主力模型, 做 memory/summary)
    - SearXNG :8087 (搜索)
    - 可选 Chrome CDP :9222 (JS 重度页面)

环境变量:
    LITELLM_MASTER_KEY  LiteLLM 认证 key
    QUEST_MODEL_PATH    QUEST-9B 的 HF 目录路径 (tokenizer 用)
"""
import os
import sys
import json
import yaml
from pathlib import Path

# 配置
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "quest_config.yaml"

def load_config():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # 渲染环境变量
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "EMPTY")
    cfg["memory_model"]["api_key"] = cfg["memory_model"]["api_key"].replace(
        "${LITELLM_MASTER_KEY}", litellm_key
    )
    return cfg


def main():
    if len(sys.argv) < 2:
        print("用法: run_quest.py <研究问题>", file=sys.stderr)
        sys.exit(1)
    question = sys.argv[1]
    cfg = load_config()

    # 设置 QUEST 需要的环境变量
    os.environ["SEARXNG_URL"] = cfg["search"]["searxng_url"]
    os.environ["CHROME_CDP_URL"] = cfg["visit"]["chrome_cdp_url"]
    os.environ["MEMORY_MODEL_NAME"] = cfg["memory_model"]["model_name"]
    os.environ["MEMORY_API_BASE"] = cfg["memory_model"]["base_url"]
    os.environ["MEMORY_API_KEY"] = cfg["memory_model"]["api_key"]
    os.environ["SUMMARY_MODEL_NAME"] = cfg["memory_model"]["model_name"]
    os.environ["SUMMARY_API_BASE"] = cfg["memory_model"]["base_url"]
    os.environ["SUMMARY_API_KEY"] = cfg["memory_model"]["api_key"]
    os.environ["MAX_LLM_CALL_PER_RUN"] = str(cfg["agent"]["max_llm_calls"])
    os.environ["MEMORY_THRESHOLD"] = str(cfg["agent"]["context_threshold"])

    # 写 server_endpoints.conf (QUEST react_agent 运行时读)
    endpoints_conf = SCRIPT_DIR / "server_endpoints.conf"
    endpoints_conf.write_text(
        f"HOSTNAME_LIST={cfg['main_model']['hostname']}\n"
        f"PORTS={cfg['main_model']['port']}\n"
    )

    # 导入本地化工具 (覆盖 QUEST 原生工具的 search/visit)
    sys.path.insert(0, str(SCRIPT_DIR))
    import tool_search_local  # noqa: F401 - 注册 "search" 工具
    import tool_visit_local   # noqa: F401 - 注册 "visit" 工具

    # 导入 QUEST 的 prompt 和 agent
    # 需要 QUEST inference 目录在 path 里
    quest_inference = os.environ.get("QUEST_INFERENCE_DIR", str(SCRIPT_DIR / "quest_inference"))
    if Path(quest_inference).exists():
        sys.path.insert(0, quest_inference)
    
    # 延迟导入 ( QUEST agent 依赖较多)
    from qwen_agent.agents.fncall_agent import FnCallAgent
    from qwen_agent.llm.schema import Message

    # 构建工具列表
    function_list = ["search", "visit", "memory"]
    # python 工具 (可选, 需要 sandbox)
    if os.environ.get("QUEST_PYTHON_TOOL") == "1":
        function_list.append("PythonInterpreter")

    # 模型配置
    quest_model_path = os.environ.get("QUEST_MODEL_PATH", "")
    llm_cfg = {
        "model_path": quest_model_path,  # tokenizer 用
        "generate_cfg": {
            "max_input_length": 100000,
            "max_gen_length": 4096,
        },
    }

    print(f"═══ QUEST Deep Research ═══", flush=True)
    print(f"问题: {question}", flush=True)
    print(f"模型: {cfg['main_model']['model_name']} @ {cfg['main_model']['hostname']}:{cfg['main_model']['port']}", flush=True)
    print(f"工具: {function_list}", flush=True)
    print(f"═══════════════════════════", flush=True)
    print()

    # 导入 QUEST agent (从 quest_inference 目录)
    # 这里用我们自己的精简 agent 包装, 避免 QUEST 完整依赖链
    from quest_agent_wrapper import QuestAgent
    
    agent = QuestAgent(
        function_list=function_list,
        llm=llm_cfg,
        endpoint=f"http://{cfg['main_model']['hostname']}:{cfg['main_model']['port']}/v1",
        api_key=cfg["main_model"]["api_key"],
    )

    # 运行
    report = agent.run(question)

    # 保存
    save_dir = Path(cfg["output"]["save_dir"])
    save_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 安全文件名
    safe_q = "".join(c if c.isalnum() or c in "-_" else "_" for c in question[:30])
    outfile = save_dir / f"quest-{ts}-{safe_q}.md"
    outfile.write_text(report)
    print(f"\n═══ 报告已保存: {outfile} ═══", flush=True)
    print(f"\n{report[:500]}...", flush=True)


if __name__ == "__main__":
    main()
