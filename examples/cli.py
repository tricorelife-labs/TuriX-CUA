#!/usr/bin/env python3
"""TuriX-CUA CLI — model-callable single-command entry.

Usage (from anywhere):
    /path/to/.turix_env/bin/python /path/to/examples/cli.py run "your task"

External callers (MCP servers, shell scripts, models with shell access):
    turix run "open WeChat and message 大马 saying hi" --json
    turix run --task-file task.txt --max-steps 30
    turix validate                      # check config + API key + weights

Exit codes:
    0   task completed (is_done == True)
    1   ran out of steps without completion
    2   config / setup error (missing key, weights, etc.)
    3   runtime error / interrupted
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Resolve project root so this works regardless of CWD
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from src.controller.service import Controller  # noqa: E402

# Reuse main.py's plumbing — keeps build_llm() in one place.
import examples.main as _main  # noqa: E402


# ---------- helpers ----------

def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise SystemExit(
            f"[cli] config not found: {config_path}\n"
            f"      copy examples/config.example.json -> {config_path} and fill in your DashScope key"
        )
    with config_path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _has_real_key(cfg: dict) -> bool:
    for role in ("brain_llm", "actor_llm", "memory_llm", "planner_llm"):
        block = cfg.get(role) or {}
        key = block.get("api_key", "")
        if not key or "YOUR_" in key.upper() or key == "your_api_key_here":
            return False
    return True


def _apply_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    if args.task is not None:
        cfg["agent"]["task"] = args.task
    if args.max_steps is not None:
        cfg["agent"]["max_steps"] = args.max_steps
    if args.max_actions is not None:
        cfg["agent"]["max_actions_per_step"] = args.max_actions
    if args.use_plan is not None:
        cfg["agent"]["use_plan"] = args.use_plan
    if args.use_skills is not None:
        cfg["agent"]["use_skills"] = args.use_skills
    if args.use_ui is not None:
        cfg["agent"]["use_ui"] = args.use_ui
    if args.use_omniparser is not None:
        cfg["agent"]["use_omniparser"] = args.use_omniparser
    if args.api_key:
        for role in ("brain_llm", "actor_llm", "memory_llm", "planner_llm"):
            cfg[role]["api_key"] = args.api_key
    return cfg


# ---------- subcommands ----------

def _cmd_validate(args: argparse.Namespace) -> int:
    cfg = _load_config(Path(args.config))
    issues = []

    if not _has_real_key(cfg):
        issues.append("api_key still has YOUR_DASHSCOPE_API_KEY placeholder in at least one LLM role")

    yolo = cfg.get("agent", {}).get("omniparser_yolo_path")
    if yolo:
        yolo_path = Path(yolo)
        if not yolo_path.is_absolute():
            yolo_path = _ROOT / yolo_path
        if not yolo_path.exists():
            issues.append(f"OmniParser weights missing: {yolo_path}")

    # Try a tiny LLM call to verify auth + model access
    try:
        from openai import OpenAI

        first = cfg["brain_llm"]
        client = OpenAI(api_key=first["api_key"], base_url=first["base_url"])
        client.chat.completions.create(
            model=first["model_name"],
            messages=[{"role": "user", "content": "reply ok"}],
            max_tokens=4,
        )
    except Exception as e:
        issues.append(f"LLM probe failed: {type(e).__name__}: {str(e)[:200]}")

    out = {
        "config_path": str(Path(args.config).resolve()),
        "model": cfg["brain_llm"]["model_name"],
        "use_omniparser": cfg["agent"].get("use_omniparser", False),
        "task": cfg["agent"].get("task", "")[:120],
        "issues": issues,
        "status": "ok" if not issues else "error",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


def _cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    cfg = _load_config(config_path)

    # Allow --task-file as alternative to positional
    if args.task_file:
        args.task = Path(args.task_file).read_text(encoding="utf-8").strip()

    cfg = _apply_overrides(cfg, args)
    if not cfg["agent"].get("task"):
        print("[cli] no task specified — pass it as positional arg or via --task-file", file=sys.stderr)
        return 2
    if not _has_real_key(cfg):
        print("[cli] api_key placeholder still present — set --api-key or fill examples/config.json", file=sys.stderr)
        return 2

    # --- build LLMs (delegates to main.py) ---
    brain_thinking = cfg.get("brain_enable_thinking", False)
    brain_llm = _main.build_llm(cfg["brain_llm"], enable_thinking=brain_thinking)
    actor_llm = _main.build_llm(cfg["actor_llm"], enable_thinking=False)
    memory_llm = _main.build_llm(cfg["memory_llm"], enable_thinking=False)
    planner_llm = (
        _main.build_llm(cfg["planner_llm"], enable_thinking=True)
        if cfg["agent"].get("use_plan") else None
    )

    # --- output dir ---
    output_dir = _main.resolve_output_dir(cfg, config_path)

    # --- agent ---
    from src import Agent
    agent_cfg = cfg["agent"]
    skills_dir = agent_cfg.get("skills_dir")
    if skills_dir:
        sp = Path(skills_dir)
        if not sp.is_absolute():
            sp = (_ROOT / sp).resolve()
        skills_dir = str(sp)

    controller = Controller()

    # --- OmniParser instance (cross-branch). The wrapper lives in
    # src.mac.omni_parser on the macOS branch and src.windows.omni_parser
    # on the multi-agent-windows branch.
    omni_instance = None
    if agent_cfg.get("use_omniparser"):
        try:
            try:
                from src.mac.omni_parser import OmniParser
            except ImportError:
                from src.windows.omni_parser import OmniParser
            yolo_path = Path(agent_cfg.get("omniparser_yolo_path", "weights/icon_detect/model.pt"))
            if not yolo_path.is_absolute():
                yolo_path = (_ROOT / yolo_path).resolve()
            caption_path = agent_cfg.get("omniparser_caption_path") or None
            if caption_path:
                caption_path = str(_ROOT / caption_path) if not Path(caption_path).is_absolute() else caption_path
            omni_instance = OmniParser(
                yolo_path=str(yolo_path),
                caption_model_path=caption_path,
                conf=float(agent_cfg.get("omniparser_conf", 0.25)),
            )
            iou = float(agent_cfg.get("omniparser_iou_threshold", 0.5))
            # Mac path: Controller has mac_tree_builder
            if hasattr(controller, "mac_tree_builder"):
                controller.mac_tree_builder.omni = omni_instance
                controller.mac_tree_builder.omni_iou_threshold = iou
        except Exception as e:
            print(f"[cli] OmniParser init failed: {e}", file=sys.stderr)
            omni_instance = None

    agent = Agent(
        task=agent_cfg["task"],
        brain_llm=brain_llm,
        actor_llm=actor_llm,
        planner_llm=planner_llm,
        memory_llm=memory_llm,
        memory_budget=agent_cfg.get("memory_budget_tokens", 2000),
        summary_memory_budget=agent_cfg.get("summary_memory_budget_tokens"),
        controller=controller,
        use_ui=agent_cfg.get("use_ui", True),
        use_search=agent_cfg.get("use_search", False),
        use_skills=agent_cfg.get("use_skills", False),
        skills_dir=skills_dir,
        skills_max_chars=agent_cfg.get("skills_max_chars", 4000),
        max_actions_per_step=agent_cfg.get("max_actions_per_step", 3),
        artifacts_dir=str(output_dir),
    )

    # Wire OmniParser onto the runtime instance:
    # - Mac branch: agent.mac_tree_builder is the one used by build_tree
    # - Win branch: agent.omni is read directly inside brain_step
    if omni_instance is not None:
        if hasattr(agent, "mac_tree_builder"):
            agent.mac_tree_builder.omni = omni_instance
            agent.mac_tree_builder.omni_iou_threshold = float(
                agent_cfg.get("omniparser_iou_threshold", 0.5)
            )
        elif hasattr(agent, "omni"):
            agent.omni = omni_instance

    # --- run ---
    t0 = time.time()
    try:
        history = asyncio.run(agent.run(max_steps=agent_cfg.get("max_steps", 20)))
    except KeyboardInterrupt:
        print("[cli] interrupted", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"[cli] runtime error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    duration = time.time() - t0

    is_done = bool(history and history.is_done())
    n_steps = getattr(agent, "n_steps", 0) - 1  # n_steps is 1-indexed and post-incremented

    summary = {
        "status": "success" if is_done else "incomplete",
        "task": agent_cfg["task"],
        "is_done": is_done,
        "n_steps": n_steps,
        "duration_s": round(duration, 2),
        "model": cfg["brain_llm"]["model_name"],
        "log_file": str(output_dir / "logging.log"),
    }

    if args.json:
        # Single-line JSON to stdout (machine-readable). Logs went to stderr/file.
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"\n{'✅' if is_done else '⚠'} {summary['status']}: {n_steps} steps, {duration:.1f}s", file=sys.stderr)

    return 0 if is_done else 1


# ---------- arg parser ----------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="turix",
        description="TuriX-CUA CLI — model-callable desktop automation agent.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ---- run ----
    pr = sub.add_parser("run", help="Run a task end-to-end")
    pr.add_argument("task", nargs="?", help="Task description (in any language)")
    pr.add_argument("--task-file", help="Read task from a file instead of positional arg")
    pr.add_argument("-c", "--config", default=str(_ROOT / "examples" / "config.json"),
                    help="Path to config.json (default: examples/config.json)")
    pr.add_argument("--api-key", help="DashScope/OpenAI key — overrides all 4 LLM roles")
    pr.add_argument("--max-steps", type=int)
    pr.add_argument("--max-actions", type=int, dest="max_actions")
    pr.add_argument("--use-plan", dest="use_plan", action="store_const", const=True)
    pr.add_argument("--no-plan", dest="use_plan", action="store_const", const=False)
    pr.add_argument("--use-skills", dest="use_skills", action="store_const", const=True)
    pr.add_argument("--no-skills", dest="use_skills", action="store_const", const=False)
    pr.add_argument("--use-ui", dest="use_ui", action="store_const", const=True)
    pr.add_argument("--no-ui", dest="use_ui", action="store_const", const=False)
    pr.add_argument("--use-omniparser", dest="use_omniparser", action="store_const", const=True)
    pr.add_argument("--no-omniparser", dest="use_omniparser", action="store_const", const=False)
    pr.add_argument("--json", action="store_true",
                    help="Print a single JSON line of result to stdout (logs go to stderr)")
    pr.set_defaults(func=_cmd_run, use_plan=None, use_skills=None, use_ui=None,
                    use_omniparser=None, max_steps=None, max_actions=None)

    # ---- validate ----
    pv = sub.add_parser("validate", help="Sanity-check config + LLM auth + weights")
    pv.add_argument("-c", "--config", default=str(_ROOT / "examples" / "config.json"))
    pv.set_defaults(func=_cmd_validate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
