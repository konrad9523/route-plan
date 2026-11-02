"""武汉 Dijkstra 逐查询配对复测：10 轮，同一路径上随机交错所有实现。"""

from pathlib import Path

import wuhan_dijkstra_layered_ablation as experiment

experiment.ROUNDS = 10
experiment.ORDER_MODE = "random"
experiment.TIMING_MODE = "paired_query"
experiment.RESULT_FILE = experiment.RESULT_FILE.with_name("wuhan_dijkstra_layered_results_v3.json")


if __name__ == "__main__":
    experiment.main()
