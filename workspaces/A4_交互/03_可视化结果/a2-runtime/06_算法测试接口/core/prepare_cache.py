from __future__ import annotations

import argparse

from .benchmark_service import BenchmarkService


def main() -> None:
    service = BenchmarkService()
    parser = argparse.ArgumentParser(description="提前生成路径规划算法预处理缓存")
    parser.add_argument("--dataset", action="append", help="数据集ID，可重复指定")
    parser.add_argument("--all", action="store_true", help="处理所有已配置数据集")
    parser.add_argument("--force", action="store_true", help="强制重新生成缓存")
    args = parser.parse_args()
    selected = list(service.datasets) if args.all else (args.dataset or [service.config["defaults"]["dataset"]])

    for dataset_id in selected:
        if dataset_id not in service.datasets:
            raise SystemExit(f"未知数据集：{dataset_id}")
        dataset = service.datasets[dataset_id]
        if not dataset.graphml.exists():
            print(f"跳过 {dataset.name}：未找到 {dataset.graphml}")
            continue
        print(f"\n正在准备：{dataset.name}")
        status = service.prepare_cache(
            dataset_id,
            force=args.force,
            notify=lambda stage, percent: print(f"  {stage}: {percent}%"),
        )
        print(f"已完成：{status['created_at']}")
        for name, value in status["preprocess_ms"].items():
            print(f"  {name}: {value:.6f} ms")


if __name__ == "__main__":
    main()
