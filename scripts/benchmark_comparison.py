#!/usr/bin/env python3
"""TripPlanner 性能基准与架构对照压测脚本 (Benchmark Comparison Suite)

对比 Sovereign Harness vs LangGraph Legacy 真实环境下的性能表现：
1. 单轮规划端到端时延 (E2E Latency)
2. 首事件发射耗时 (TTFT / Time to First Token)
3. 交互澄清响应时延 (Clarification Latency)
4. 吞吐量与事件完整度
"""
import json
import sys
import time
import httpx

API_BASE = "http://localhost:8000"

TEST_CASES = [
    {
        "name": "多轮缺失槽位澄清 (Missing City & Days)",
        "payload": {
            "input_text": "我想出去旅游，预算1万元",
        },
        "expect_event": "clarification",
    },
    {
        "name": "短途经典行程规划 (Beijing 2-Day Classical)",
        "payload": {
            "input_text": "我想去北京玩2天，2026-09-21出发，预算3000元，必须去故宫和天坛",
        },
        "expect_event": "plan_version",
    },
    {
        "name": "深度全景游规划 (Chengdu 3-Day Culture & Food)",
        "payload": {
            "input_text": "2026-09-22想去成都玩3天，喜欢历史文化和地道火锅，必须去杜甫草堂",
        },
        "expect_event": "plan_version",
    },
]


def run_benchmark(engine: str) -> list[dict]:
    results = []
    print(f"\n🚀 开始评测引擎: [{engine.upper()}] ...")

    for idx, case in enumerate(TEST_CASES, 1):
        case_name = case["name"]
        payload = {
            "session_id": f"bench_{engine}_{idx}_{int(time.time())}",
            "engine": engine,
            **case["payload"],
        }

        t_start = time.perf_counter()
        first_event_ms = None
        event_count = 0
        received_events = []

        try:
            with httpx.Client(timeout=60.0, trust_env=False) as client:
                with client.stream("POST", f"{API_BASE}/api/session/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        print(f"  ❌ [{case_name}] HTTP 状态异常: {resp.status_code}")
                        continue

                    for line in resp.iter_lines():
                        if line.startswith("event:"):
                            event_type = line.replace("event:", "").strip()
                            if first_event_ms is None:
                                first_event_ms = round((time.perf_counter() - t_start) * 1000, 2)
                            event_count += 1
                            received_events.append(event_type)

            total_latency_ms = round((time.perf_counter() - t_start) * 1000, 2)
            passed = case["expect_event"] in received_events

            print(f"  ✓ [{case_name}]: 总耗时 {total_latency_ms}ms | 首事件 {first_event_ms}ms | 事件数 {event_count}")
            results.append({
                "case": case_name,
                "engine": engine,
                "total_ms": total_latency_ms,
                "first_event_ms": first_event_ms,
                "event_count": event_count,
                "status": "PASS" if passed else "FAIL",
            })
        except Exception as e:
            print(f"  ❌ [{case_name}] 请求失败: {e}")
            results.append({
                "case": case_name,
                "engine": engine,
                "total_ms": 99999.0,
                "first_event_ms": 99999.0,
                "event_count": 0,
                "status": f"ERR: {e}",
            })

    return results


def print_scoreboard(harness_results: list[dict], langgraph_results: list[dict]):
    print("\n" + "═" * 80)
    print("🏆 TRIPPLANNER 架构代差性能评测看板 (BENCHMARK SCOREBOARD)")
    print("═" * 80)
    print(f"{'测试用例':<32} | {'Harness 时延':<14} | {'LangGraph 时延':<15} | {'性能提速比':<10}")
    print("─" * 80)

    total_harness = 0.0
    total_langgraph = 0.0

    for h, lg in zip(harness_results, langgraph_results):
        h_time = h["total_ms"]
        lg_time = lg["total_ms"]
        total_harness += h_time
        total_langgraph += lg_time
        speedup = f"{lg_time / h_time:.1f}x" if h_time > 0 else "N/A"
        print(f"{h['case']:<32} | {h_time:>8.1f} ms     | {lg_time:>9.1f} ms      | {speedup:>8}")

    print("─" * 80)
    overall_speedup = total_langgraph / total_harness if total_harness > 0 else 1.0
    print(f"{'综合平均':<32} | {total_harness / len(harness_results):>8.1f} ms     | {total_langgraph / len(langgraph_results):>9.1f} ms      | {overall_speedup:>7.1f}x")
    print("═" * 80)


if __name__ == "__main__":
    h_res = run_benchmark("harness")
    lg_res = run_benchmark("langgraph")
    print_scoreboard(h_res, lg_res)
