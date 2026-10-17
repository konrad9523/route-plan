from __future__ import annotations

import ctypes as ct
import hashlib
import importlib.util
import json
import math
import platform
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components


SCRIPT_DIR = Path(__file__).resolve().parent
A3_ROOT = SCRIPT_DIR.parents[1]
PROJECT_ROOT = A3_ROOT.parents[1]
ALGORITHM_DIR = SCRIPT_DIR
BASELINE_DIR = PROJECT_ROOT / "workspaces" / "A2_算法" / "01_实现清单"
DATA_DIR = A3_ROOT / "深圳实验数据_本地"
SOURCE_DIR = DATA_DIR / "解压"
ROAD_FILE = SOURCE_DIR / "Shenzhen.road-d"
COORD_FILE = SOURCE_DIR / "Shenzhen.co"
OUTPUT_ROOT = A3_ROOT / "03_实验结果" / "深圳" / "全量复现实验"

GRAPH_POLICY = "shenzhen-github-osm-car-distance-2021"
EXPECTED_NODES = 236_647
EXPECTED_EDGES = 517_110
QUERY_COUNT = 100
ROUNDS = 5
WARMUP_COUNT = 5
RANDOM_SEED = 20261016
ABS_TOL_M = 1e-5
REL_TOL = 1e-10

DIJKSTRA_LAYERS = ("L0", "L1", "L2", "L3", "L4", "B1")
ASTAR_CASES = [
    {"name": "L0", "version": "L0", "heuristic": "H0", "k": 0},
    {"name": "L0-CachedScale", "version": "L0-CachedScale", "heuristic": "H0", "k": 0},
    *[
        {"name": layer, "version": layer, "heuristic": "H0", "k": 0}
        for layer in ("L1", "L2", "L3", "L4", "L5")
    ],
    {"name": "L4-PLANE", "version": "L4", "heuristic": "PLANE", "k": 0},
    *[
        {"name": f"L4-ALT{k}", "version": "L4", "heuristic": "ALT", "k": k}
        for k in (4, 8, 16)
    ],
    *[
        {"name": f"L4-MAX{k}", "version": "L4", "heuristic": "MAX", "k": k}
        for k in (4, 8, 16)
    ],
    {"name": "B1-H0", "version": "B1", "heuristic": "H0", "k": 0},
]
ASTAR_CASE_ORDER = tuple(case["name"] for case in ASTAR_CASES)
CPP_VERSION_IDS = {
    "L0": 0,
    "L0-CachedScale": 1,
    "L1": 2,
    "L2": 3,
    "L3": 4,
    "L4": 5,
    "L5": 6,
    "B1": 7,
}
CPP_HEURISTIC_IDS = {"H0": 0, "PLANE": 1, "ALT": 2, "MAX": 3}
CPP_STATUS_NAMES = {
    0: "OK",
    1: "INVALID_ARGUMENT",
    2: "INVALID_GRAPH",
    3: "INVALID_QUERY",
    4: "BUFFER_TOO_SMALL",
    5: "PREPARATION_REQUIRED",
    6: "INTERNAL_ERROR",
}
CPP_FLAGS = ("/std:c++17", "/O2", "/EHsc", "/LD", "/DNDEBUG")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_shenzhen_graph():
    started = time.perf_counter_ns()
    coordinate_rows = [
        line.strip()
        for line in COORD_FILE.open(encoding="utf-8")
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not coordinate_rows:
        raise ValueError("Shenzhen.co is empty")
    n_nodes = int(coordinate_rows[0])
    if n_nodes != EXPECTED_NODES or len(coordinate_rows) != n_nodes + 1:
        raise ValueError(
            f"coordinate count mismatch: header={n_nodes}, rows={len(coordinate_rows)-1}"
        )

    lon = np.empty(n_nodes, dtype=np.float64)
    lat = np.empty(n_nodes, dtype=np.float64)
    for node, row in enumerate(coordinate_rows[1:]):
        latitude, longitude = map(float, row.split())
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError(f"invalid coordinate at node {node}: {row}")
        lat[node], lon[node] = latitude, longitude

    sources, targets, edge_weights = [], [], []
    last_source = -1
    zero_weight_edges = 0
    for line_number, line in enumerate(ROAD_FILE.open(encoding="utf-8"), start=1):
        row = line.strip()
        if not row or row.lstrip().startswith("#"):
            continue
        fields = row.split()
        if len(fields) != 3:
            raise ValueError(f"invalid road row {line_number}: {row!r}")
        source, target = int(fields[0]), int(fields[1])
        weight = float(fields[2])
        if not (0 <= source < n_nodes and 0 <= target < n_nodes):
            raise ValueError(f"edge endpoint out of range at line {line_number}")
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"invalid edge weight at line {line_number}: {weight}")
        if source < last_source:
            raise ValueError("road edges are not grouped by source; CSR order is unsafe")
        last_source = source
        zero_weight_edges += weight == 0.0
        sources.append(source)
        targets.append(target)
        edge_weights.append(weight)

    n_edges = len(sources)
    if n_edges != EXPECTED_EDGES:
        raise ValueError(f"edge count mismatch: expected {EXPECTED_EDGES}, got {n_edges}")
    source_array = np.asarray(sources, dtype=np.int64)
    indices = np.asarray(targets, dtype=np.int64)
    weights = np.asarray(edge_weights, dtype=np.float64)
    edge_ids = np.arange(n_edges, dtype=np.int64)
    counts = np.bincount(source_array, minlength=n_nodes)
    indptr = np.empty(n_nodes + 1, dtype=np.int64)
    indptr[0] = 0
    np.cumsum(counts, out=indptr[1:])
    if int(indptr[-1]) != n_edges or np.any(indptr[1:] < indptr[:-1]):
        raise ValueError("invalid CSR pointers built from source graph")
    if not (len(indices) == len(weights) == len(edge_ids) == n_edges):
        raise ValueError("edge arrays have inconsistent lengths")
    if not np.isfinite(weights).all():
        raise ValueError("edge weights contain non-finite values")

    graph_sha = hashlib.sha256(
        f"{sha256_file(ROAD_FILE)}:{sha256_file(COORD_FILE)}".encode("ascii")
    ).hexdigest()
    parse_ns = time.perf_counter_ns() - started
    return {
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "indptr": indptr,
        "indices": indices,
        "weights": weights,
        "edge_ids": edge_ids,
        "edge_sources": source_array,
        "lon": lon,
        "lat": lat,
        "zero_weight_edges": int(zero_weight_edges),
        "graph_sha256": graph_sha,
        "parse_ns": parse_ns,
    }


def build_python_graph(graph_data):
    started = time.perf_counter_ns()
    n = graph_data["n_nodes"]
    graph = {node: [] for node in range(n)}
    for edge_id, (source, target, weight) in enumerate(
        zip(graph_data["edge_sources"], graph_data["indices"], graph_data["weights"])
    ):
        graph[int(source)].append((int(target), float(weight), edge_id))
    positions = {
        node: (float(graph_data["lon"][node]), float(graph_data["lat"][node]))
        for node in range(n)
    }
    return graph, positions, time.perf_counter_ns() - started


def precheck_dijkstra_graph(graph, graph_data):
    started = time.perf_counter_ns()
    seen = bytearray(graph_data["n_edges"])
    for source, outgoing in graph.items():
        for target, weight, edge_id in outgoing:
            if not 0 <= target < graph_data["n_nodes"]:
                raise ValueError(f"edge {source}->{target} points outside graph")
            if not math.isfinite(weight) or weight < 0:
                raise ValueError(f"invalid edge weight at {source}->{target}")
            if not 0 <= edge_id < graph_data["n_edges"] or seen[edge_id]:
                raise ValueError(f"edge ID out of range or duplicated: {edge_id}")
            if graph_data["edge_sources"][edge_id] != source:
                raise ValueError(f"edge ID {edge_id} has wrong source")
            if graph_data["indices"][edge_id] != target:
                raise ValueError(f"edge ID {edge_id} has wrong target")
            if not math.isclose(
                float(graph_data["weights"][edge_id]), weight,
                rel_tol=1e-12, abs_tol=1e-9,
            ):
                raise ValueError(f"edge ID {edge_id} has wrong weight")
            seen[edge_id] = 1
    if not all(seen):
        raise ValueError("some edge IDs are missing from adjacency list")
    return time.perf_counter_ns() - started


def build_reverse_graph(graph):
    reverse = {node: [] for node in graph}
    for source, outgoing in graph.items():
        for target, weight, edge_id in outgoing:
            reverse[target].append((source, weight, edge_id))
    return reverse


def make_queries(graph_data, astar_variants):
    matrix = csr_matrix(
        (
            np.ones(graph_data["n_edges"], dtype=np.uint8),
            graph_data["indices"],
            graph_data["indptr"],
        ),
        shape=(graph_data["n_nodes"], graph_data["n_nodes"]),
    )
    scc_count, labels = connected_components(
        matrix, directed=True, connection="strong", return_labels=True
    )
    sizes = np.bincount(labels, minlength=scc_count)
    largest_component = int(np.argmax(sizes))
    candidates = np.flatnonzero(labels == largest_component).tolist()

    rng = random.Random(RANDOM_SEED)
    strata = ("0-1km", "1-5km", "5-20km", "20-50km", ">=50km")
    thresholds = (1_000, 5_000, 20_000, 50_000)
    quota = Counter()
    queries, used = [], set()
    for _ in range(100_000):
        source, target = rng.sample(candidates, 2)
        direct = astar_variants.haversine_distance(
            {source: (graph_data["lon"][source], graph_data["lat"][source]),
             target: (graph_data["lon"][target], graph_data["lat"][target])},
            source,
            target,
        )
        band = next(
            (name for upper, name in zip(thresholds, strata) if direct < upper),
            strata[-1],
        )
        if quota[band] < 20 and (source, target) not in used:
            queries.append({
                "source": source,
                "target": target,
                "straight_distance_band": band,
                "straight_distance_m": direct,
            })
            quota[band] += 1
            used.add((source, target))
        if len(queries) == QUERY_COUNT:
            break
    if len(queries) != QUERY_COUNT or any(value != 20 for value in quota.values()):
        raise ValueError(f"could not create the five 20-query strata: {dict(quota)}")
    return {
        "seed": RANDOM_SEED,
        "graph_policy": GRAPH_POLICY,
        "strata_by": "endpoint Haversine distance (not route distance)",
        "queries": queries,
    }, scc_count, sizes, labels, largest_component, candidates


def validate_route(result, source, target, graph_data):
    nodes = result["nodes"]
    edge_ids = result["edge_ids"]
    distance = float(result["distance_m"])
    if not nodes:
        return not edge_ids and math.isinf(distance)
    if nodes[0] != source or nodes[-1] != target:
        return False
    if len(nodes) != len(edge_ids) + 1:
        return False
    path_weights = []
    for u, v, edge_id in zip(nodes, nodes[1:], edge_ids):
        if not 0 <= int(edge_id) < graph_data["n_edges"]:
            return False
        if graph_data["edge_sources"][edge_id] != u:
            return False
        if graph_data["indices"][edge_id] != v:
            return False
        path_weights.append(float(graph_data["weights"][edge_id]))
    return math.isclose(
        math.fsum(path_weights), distance,
        rel_tol=REL_TOL, abs_tol=ABS_TOL_M,
    )


def same_distance(left, right):
    if math.isfinite(left):
        return math.isfinite(right) and math.isclose(
            left, right, rel_tol=REL_TOL, abs_tol=ABS_TOL_M
        )
    return math.isinf(right)


def configure_dijkstra_cpp(dll_path, graph_data):
    library = ct.CDLL(str(dll_path))
    i64p = ct.POINTER(ct.c_int64)
    doublep = ct.POINTER(ct.c_double)
    u64p = ct.POINTER(ct.c_uint64)
    library.dijkstra_graph_create.argtypes = [
        ct.c_int64, ct.c_int64, i64p, i64p, doublep, i64p,
        ct.POINTER(ct.c_int32),
    ]
    library.dijkstra_graph_create.restype = ct.c_void_p
    library.dijkstra_graph_destroy.argtypes = [ct.c_void_p]
    library.dijkstra_graph_destroy.restype = None
    library.dijkstra_run.argtypes = [
        ct.c_void_p, ct.c_int32, ct.c_int64, ct.c_int64,
        i64p, ct.c_int64, i64p, ct.c_int64,
        ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64), doublep, u64p, u64p,
    ]
    library.dijkstra_run.restype = ct.c_int32

    started = time.perf_counter_ns()
    handle_error = ct.c_int32()
    handle = library.dijkstra_graph_create(
        graph_data["n_nodes"], graph_data["n_edges"],
        graph_data["indptr"].ctypes.data_as(i64p),
        graph_data["indices"].ctypes.data_as(i64p),
        graph_data["weights"].ctypes.data_as(doublep),
        graph_data["edge_ids"].ctypes.data_as(i64p),
        ct.byref(handle_error),
    )
    create_ns = time.perf_counter_ns() - started
    if not handle or handle_error.value != 0:
        if handle:
            library.dijkstra_graph_destroy(handle)
        raise RuntimeError(f"Dijkstra C++ graph create failed: {handle_error.value}")
    return {
        "library": library,
        "handle": handle,
        "i64p": i64p,
        "doublep": doublep,
        "u64p": u64p,
        "node_buffer": np.empty(graph_data["n_nodes"], dtype=np.int64),
        "edge_buffer": np.empty(graph_data["n_nodes"], dtype=np.int64),
        "create_ns": create_ns,
    }


def run_dijkstra_cpp(state, layer, source, target):
    library = state["library"]
    node_count, edge_count = ct.c_int64(), ct.c_int64()
    distance, settled, elapsed = ct.c_double(), ct.c_uint64(), ct.c_uint64()
    status = library.dijkstra_run(
        state["handle"], DIJKSTRA_LAYERS.index(layer), source, target,
        state["node_buffer"].ctypes.data_as(state["i64p"]),
        state["node_buffer"].size,
        state["edge_buffer"].ctypes.data_as(state["i64p"]),
        state["edge_buffer"].size,
        ct.byref(node_count), ct.byref(edge_count), ct.byref(distance),
        ct.byref(settled), ct.byref(elapsed),
    )
    if status != 0:
        raise RuntimeError(f"Dijkstra C++ {layer} failed for {source}->{target}: {status}")
    if not (
        0 <= node_count.value <= state["node_buffer"].size
        and 0 <= edge_count.value <= state["edge_buffer"].size
    ):
        raise RuntimeError("Dijkstra C++ path exceeds output buffer")
    return {
        "nodes": state["node_buffer"][:node_count.value].tolist(),
        "edge_ids": state["edge_buffer"][:edge_count.value].tolist(),
        "distance_m": float(distance.value),
        "expanded_nodes": int(settled.value),
        "kernel_ns": int(elapsed.value),
    }


def run_dijkstra_python(baseline, variants, layer, graph, reverse, csr, source, target):
    if layer == "L0":
        result = baseline.dijkstra(graph, source, target)
    elif layer == "B1":
        result = variants.dijkstra_b1(graph, reverse, source, target)
    elif layer == "L4":
        result = variants.dijkstra_l4(csr, source, target)
    else:
        result = getattr(variants, f"dijkstra_{layer.lower()}")(graph, source, target)
    return {
        "nodes": result[0],
        "edge_ids": result[1],
        "distance_m": float(result[2]),
        "expanded_nodes": int(result[3]),
        "kernel_ns": None,
    }


def run_dijkstra_correctness(language, runner, queries, graph_data):
    checked = 0
    references = []
    for query_id, query in enumerate(queries):
        source, target = int(query["source"]), int(query["target"])
        reference = runner("L0", source, target)
        if not validate_route(reference, source, target, graph_data):
            raise AssertionError(f"{language}/L0 invalid route for query {query_id}")
        references.append(float(reference["distance_m"]))
        for layer in DIJKSTRA_LAYERS:
            result = reference if layer == "L0" else runner(layer, source, target)
            if not same_distance(references[-1], result["distance_m"]):
                raise AssertionError(
                    f"{language}/{layer} distance mismatch at query {query_id}: "
                    f"{result['distance_m']} vs {references[-1]}"
                )
            if not validate_route(result, source, target, graph_data):
                raise AssertionError(f"{language}/{layer} invalid route at query {query_id}")
            checked += 1
        if (query_id + 1) % 20 == 0:
            print(f"Dijkstra {language} correctness: {query_id + 1}/{len(queries)}", flush=True)
    return checked, references


def benchmark_dijkstra(language, runner, queries):
    rng = random.Random(RANDOM_SEED)
    for layer in DIJKSTRA_LAYERS:
        for query in queries[:WARMUP_COUNT]:
            runner(layer, int(query["source"]), int(query["target"]))
    records = []
    for round_id in range(1, ROUNDS + 1):
        for query_id, query in enumerate(queries):
            layers = list(DIJKSTRA_LAYERS)
            rng.shuffle(layers)
            for order_id, layer in enumerate(layers, start=1):
                source, target = int(query["source"]), int(query["target"])
                started = time.perf_counter_ns()
                result = runner(layer, source, target)
                outer_ns = time.perf_counter_ns() - started
                records.append({
                    "language": language,
                    "layer": layer,
                    "round": round_id,
                    "query_id": query_id,
                    "source": source,
                    "target": target,
                    "order_id": order_id,
                    "outer_ns": outer_ns,
                    "outer_ms": outer_ns / 1e6,
                    "kernel_ns": result["kernel_ns"],
                    "kernel_ms": None if result["kernel_ns"] is None else result["kernel_ns"] / 1e6,
                    "distance_m": result["distance_m"],
                    "expanded_nodes": result["expanded_nodes"],
                })
            if (query_id + 1) % 25 == 0:
                print(
                    f"Dijkstra {language} timing: round {round_id}/{ROUNDS}, "
                    f"query {query_id + 1}/{len(queries)}",
                    flush=True,
                )
        print(f"Dijkstra {language} timing: round {round_id}/{ROUNDS}", flush=True)
    expected = len(queries) * ROUNDS * len(DIJKSTRA_LAYERS)
    if len(records) != expected:
        raise AssertionError(f"Dijkstra timing rows mismatch: {len(records)} != {expected}")
    return pd.DataFrame(records)


def dijkstra_query_summary(raw):
    summary = raw.groupby(["layer", "query_id"], as_index=False).agg(
        outer_query_median_ms=("outer_ms", "median"),
        expanded_nodes=("expanded_nodes", "median"),
    )
    cpp_kernel = (
        raw.loc[raw["language"] == "C++"]
        .groupby(["layer", "query_id"], as_index=False)
        .agg(kernel_query_median_ms=("kernel_ms", "median"))
    )
    return summary.merge(cpp_kernel, on=["layer", "query_id"], how="left")


def summarize_dijkstra(query_medians):
    summary = query_medians.groupby("layer", sort=False).agg(
        median_ms=("outer_query_median_ms", "median"),
        q1_ms=("outer_query_median_ms", lambda values: values.quantile(0.25)),
        q3_ms=("outer_query_median_ms", lambda values: values.quantile(0.75)),
        kernel_median_ms=("kernel_query_median_ms", "median"),
        mean_expanded_nodes=("expanded_nodes", "mean"),
    )
    return summary.reindex(DIJKSTRA_LAYERS).reset_index()


def dijkstra_paired_analysis(py_medians, cpp_medians):
    rows = []
    comparisons = (("L1", "L0"), ("L2", "L1"), ("L3", "L2"), ("L4", "L3"), ("B1", "L0"))
    for language, medians in (("Python", py_medians), ("C++", cpp_medians)):
        indexed = medians.pivot(index="query_id", columns="layer", values="outer_query_median_ms")
        for layer, previous in comparisons:
            change = (indexed[previous] - indexed[layer]) / indexed[previous] * 100
            q1, median, q3 = np.percentile(change.to_numpy(), [25, 50, 75])
            rows.append({
                "language": language,
                "comparison": f"{layer} vs {previous}",
                "paired_queries": len(change),
                "median_speedup_pct": float(median),
                "q1_speedup_pct": float(q1),
                "q3_speedup_pct": float(q3),
            })
    return pd.DataFrame(rows)


def dijkstra_cross_language(py_medians, cpp_medians):
    py = py_medians.pivot(index="query_id", columns="layer", values="outer_query_median_ms")
    cpp = cpp_medians.pivot(index="query_id", columns="layer", values="outer_query_median_ms")
    rows = []
    for layer in DIJKSTRA_LAYERS:
        ratio = py[layer] / cpp[layer]
        q1, median, q3 = np.percentile(ratio.to_numpy(), [25, 50, 75])
        rows.append({
            "layer": layer,
            "python_median_ms": float(py[layer].median()),
            "cpp_outer_median_ms": float(cpp[layer].median()),
            "paired_ratio_median": float(median),
            "ratio_q1": float(q1),
            "ratio_q3": float(q3),
            "python_slower_queries": int((py[layer] > cpp[layer]).sum()),
            "queries": len(ratio),
        })
    return pd.DataFrame(rows)


def configure_astar_cpp(dll_path, graph_data):
    library = ct.CDLL(str(dll_path))
    i64p = ct.POINTER(ct.c_int64)
    doublep = ct.POINTER(ct.c_double)
    u64p = ct.POINTER(ct.c_uint64)
    library.astar_graph_create.argtypes = [
        ct.c_int64, ct.c_int64, i64p, i64p, doublep, i64p,
        doublep, doublep, ct.POINTER(ct.c_int32),
    ]
    library.astar_graph_create.restype = ct.c_void_p
    library.astar_graph_destroy.argtypes = [ct.c_void_p]
    library.astar_graph_destroy.restype = None
    library.astar_prepare_geometry.argtypes = [ct.c_void_p, doublep, doublep, u64p]
    library.astar_prepare_geometry.restype = ct.c_int32
    library.astar_prepare_reverse.argtypes = [ct.c_void_p, u64p]
    library.astar_prepare_reverse.restype = ct.c_int32
    library.astar_prepare_alt.argtypes = [ct.c_void_p, ct.c_int32, i64p, u64p]
    library.astar_prepare_alt.restype = ct.c_int32
    library.astar_run.argtypes = [
        ct.c_void_p, ct.c_int32, ct.c_int32, ct.c_int32,
        ct.c_int64, ct.c_int64, i64p, ct.c_int64, i64p, ct.c_int64,
        ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64), doublep,
        u64p, u64p, u64p, u64p, u64p,
    ]
    library.astar_run.restype = ct.c_int32

    started = time.perf_counter_ns()
    handle_error = ct.c_int32()
    handle = library.astar_graph_create(
        graph_data["n_nodes"], graph_data["n_edges"],
        graph_data["indptr"].ctypes.data_as(i64p),
        graph_data["indices"].ctypes.data_as(i64p),
        graph_data["weights"].ctypes.data_as(doublep),
        graph_data["edge_ids"].ctypes.data_as(i64p),
        graph_data["lon"].ctypes.data_as(doublep),
        graph_data["lat"].ctypes.data_as(doublep),
        ct.byref(handle_error),
    )
    create_ns = time.perf_counter_ns() - started
    if not handle or handle_error.value != 0:
        if handle:
            library.astar_graph_destroy(handle)
        raise RuntimeError(f"A* C++ graph create failed: {handle_error.value}")
    return {
        "library": library,
        "handle": handle,
        "i64p": i64p,
        "doublep": doublep,
        "u64p": u64p,
        "node_buffer": np.empty(graph_data["n_nodes"], dtype=np.int64),
        "edge_buffer": np.empty(graph_data["n_nodes"], dtype=np.int64),
        "create_ns": create_ns,
    }


def check_astar_cpp_status(status, operation):
    if status != 0:
        raise RuntimeError(
            f"A* C++ {operation} failed: {CPP_STATUS_NAMES.get(status, status)}"
        )


def prepare_astar_cpp(state, graph_data, landmark_ids):
    library = state["library"]
    elapsed = ct.c_uint64()
    h0_scale, plane_scale = ct.c_double(), ct.c_double()
    timings = {}

    started = time.perf_counter_ns()
    status = library.astar_prepare_geometry(
        state["handle"], ct.byref(h0_scale), ct.byref(plane_scale), ct.byref(elapsed)
    )
    timings["geometry_outer_ns"] = time.perf_counter_ns() - started
    check_astar_cpp_status(status, "geometry preparation")
    timings["geometry_kernel_ns"] = int(elapsed.value)

    started = time.perf_counter_ns()
    status = library.astar_prepare_reverse(state["handle"], ct.byref(elapsed))
    timings["reverse_outer_ns"] = time.perf_counter_ns() - started
    check_astar_cpp_status(status, "reverse-graph preparation")
    timings["reverse_kernel_ns"] = int(elapsed.value)

    landmark_array = np.ascontiguousarray(landmark_ids, dtype=np.int64)
    started = time.perf_counter_ns()
    status = library.astar_prepare_alt(
        state["handle"], len(landmark_array),
        landmark_array.ctypes.data_as(state["i64p"]), ct.byref(elapsed),
    )
    timings["alt_outer_ns"] = time.perf_counter_ns() - started
    check_astar_cpp_status(status, "ALT preparation")
    timings["alt_kernel_ns"] = int(elapsed.value)
    state["h0_scale"] = float(h0_scale.value)
    state["plane_scale"] = float(plane_scale.value)
    state["landmark_array"] = landmark_array
    state["prep"] = timings


def run_astar_cpp(state, case, source, target):
    library = state["library"]
    node_count, edge_count = ct.c_int64(), ct.c_int64()
    distance = ct.c_double()
    expanded, pushed, scanned, h_calls, elapsed = (ct.c_uint64() for _ in range(5))
    status = library.astar_run(
        state["handle"], CPP_VERSION_IDS[case["version"]],
        CPP_HEURISTIC_IDS[case["heuristic"]], case["k"], source, target,
        state["node_buffer"].ctypes.data_as(state["i64p"]),
        state["node_buffer"].size,
        state["edge_buffer"].ctypes.data_as(state["i64p"]),
        state["edge_buffer"].size,
        ct.byref(node_count), ct.byref(edge_count), ct.byref(distance),
        ct.byref(expanded), ct.byref(pushed), ct.byref(scanned),
        ct.byref(h_calls), ct.byref(elapsed),
    )
    check_astar_cpp_status(status, case["name"])
    if not (
        0 <= node_count.value <= state["node_buffer"].size
        and 0 <= edge_count.value <= state["edge_buffer"].size
    ):
        raise RuntimeError("A* C++ path exceeds output buffer")
    return {
        "nodes": state["node_buffer"][:node_count.value].tolist(),
        "edge_ids": state["edge_buffer"][:edge_count.value].tolist(),
        "distance_m": float(distance.value),
        "expanded_nodes": int(expanded.value),
        "pushed_count": int(pushed.value),
        "scanned_edges": int(scanned.value),
        "heuristic_evaluations": int(h_calls.value),
        "kernel_ns": int(elapsed.value),
    }


def run_astar_python(
    case, source, target, baseline, variants, graph, reverse, positions,
    csr, h0_scale, projected, plane_scale, alt,
):
    stats = {}
    if case["name"] == "L0":
        nodes, edge_ids, distance, expanded = baseline.astar(
            graph, positions, source, target
        )
        stats = None
    elif case["version"] == "B1":
        nodes, edge_ids, distance, expanded = variants.bidirectional_astar(
            graph, reverse, positions, source, target,
            heuristic=case["heuristic"], heuristic_scale=h0_scale,
            projected=projected, plane_scale=plane_scale,
            alt=alt, landmark_count=case["k"], stats=stats,
        )
    else:
        nodes, edge_ids, distance, expanded = variants.run_astar(
            case["version"], graph, positions, source, target,
            heuristic=case["heuristic"], heuristic_scale=h0_scale,
            projected=projected, plane_scale=plane_scale,
            csr=csr, alt=alt, landmark_count=case["k"], stats=stats,
        )
    return {
        "nodes": nodes,
        "edge_ids": edge_ids,
        "distance_m": float(distance),
        "expanded_nodes": int(expanded),
        "pushed_count": None if stats is None else stats.get("pushed_count"),
        "scanned_edges": None if stats is None else stats.get("scanned_edges"),
        "heuristic_evaluations": None if stats is None else stats.get("heuristic_evaluations"),
        "kernel_ns": None,
    }


def run_astar_correctness(queries, python_runner, cpp_state, graph_data):
    checked = 0
    for query_id, query in enumerate(queries):
        source, target = int(query["source"]), int(query["target"])
        reference = python_runner(ASTAR_CASES[0], source, target)
        if not validate_route(reference, source, target, graph_data):
            raise AssertionError(f"A*/Python/L0 invalid path at query {query_id}")
        reference_distance = reference["distance_m"]
        for case in ASTAR_CASES:
            py_result = reference if case["name"] == "L0" else python_runner(case, source, target)
            if not same_distance(reference_distance, py_result["distance_m"]):
                raise AssertionError(f"A*/Python/{case['name']} distance mismatch at {query_id}")
            if not validate_route(py_result, source, target, graph_data):
                raise AssertionError(f"A*/Python/{case['name']} invalid path at {query_id}")
            cpp_result = run_astar_cpp(cpp_state, case, source, target)
            if not same_distance(reference_distance, cpp_result["distance_m"]):
                raise AssertionError(f"A*/C++/{case['name']} distance mismatch at {query_id}")
            if not validate_route(cpp_result, source, target, graph_data):
                raise AssertionError(f"A*/C++/{case['name']} invalid path at {query_id}")
            checked += 2
        if (query_id + 1) % 10 == 0:
            print(f"A* correctness: {query_id + 1}/{len(queries)} queries", flush=True)
    return checked


def benchmark_astar(queries, python_runner, cpp_state):
    rng = random.Random(RANDOM_SEED)
    items = [(case, language) for case in ASTAR_CASES for language in ("Python", "C++")]
    warmup_items = items.copy()
    rng.shuffle(warmup_items)
    for query in queries[:WARMUP_COUNT]:
        source, target = int(query["source"]), int(query["target"])
        for case, language in warmup_items:
            if language == "Python":
                python_runner(case, source, target)
            else:
                run_astar_cpp(cpp_state, case, source, target)

    records = []
    for round_id in range(1, ROUNDS + 1):
        for query_id, query in enumerate(queries):
            source, target = int(query["source"]), int(query["target"])
            round_items = items.copy()
            rng.shuffle(round_items)
            for order_id, (case, language) in enumerate(round_items, start=1):
                started = time.perf_counter_ns()
                if language == "Python":
                    result = python_runner(case, source, target)
                else:
                    result = run_astar_cpp(cpp_state, case, source, target)
                outer_ns = time.perf_counter_ns() - started
                records.append({
                    "language": language,
                    "case": case["name"],
                    "version": case["version"],
                    "heuristic": case["heuristic"],
                    "landmark_count": case["k"],
                    "round": round_id,
                    "query_id": query_id,
                    "source": source,
                    "target": target,
                    "order_id": order_id,
                    "outer_ns": outer_ns,
                    "outer_ms": outer_ns / 1e6,
                    "kernel_ns": result["kernel_ns"],
                    "kernel_ms": None if result["kernel_ns"] is None else result["kernel_ns"] / 1e6,
                    "distance_m": result["distance_m"],
                    "expanded_nodes": result["expanded_nodes"],
                    "pushed_count": result["pushed_count"],
                    "scanned_edges": result["scanned_edges"],
                    "heuristic_evaluations": result["heuristic_evaluations"],
                })
            if (query_id + 1) % 10 == 0:
                print(f"A* timing: round {round_id}/{ROUNDS}, query {query_id + 1}/{len(queries)}", flush=True)
    expected = ROUNDS * len(queries) * len(ASTAR_CASES) * 2
    if len(records) != expected:
        raise AssertionError(f"A* timing rows mismatch: {len(records)} != {expected}")
    return pd.DataFrame(records)


def astar_query_summary(raw):
    keys = ["case", "language", "query_id"]
    summary = raw.groupby(keys, as_index=False).agg(
        outer_query_median_ms=("outer_ms", "median"),
        expanded_nodes=("expanded_nodes", "median"),
        pushed_count=("pushed_count", "median"),
        scanned_edges=("scanned_edges", "median"),
        heuristic_evaluations=("heuristic_evaluations", "median"),
    )
    cpp_kernel = (
        raw.loc[raw["language"] == "C++"]
        .groupby(keys, as_index=False)
        .agg(kernel_query_median_ms=("kernel_ms", "median"))
    )
    return summary.merge(cpp_kernel, on=keys, how="left")


def summarize_astar(raw):
    rows = []
    for language in ("Python", "C++"):
        subset = raw[raw["language"] == language]
        for case in ASTAR_CASE_ORDER:
            group = subset[subset["case"] == case]
            q1, median, q3 = np.percentile(group["outer_ms"], [25, 50, 75])
            rows.append({
                "language": language,
                "case": case,
                "median_ms": float(median),
                "q1_ms": float(q1),
                "q3_ms": float(q3),
                "kernel_median_ms": float(group["kernel_ms"].median()) if language == "C++" else np.nan,
                "mean_expanded_nodes": float(group["expanded_nodes"].mean()),
                "mean_pushed_count": float(group["pushed_count"].mean()),
                "mean_scanned_edges": float(group["scanned_edges"].mean()),
                "mean_heuristic_evaluations": float(group["heuristic_evaluations"].mean()),
            })
    return pd.DataFrame(rows)


def analyze_astar(raw, query_medians, summary):
    layer_previous = {
        "L0": None,
        "L0-CachedScale": "L0",
        "L1": "L0-CachedScale",
        "L2": "L1",
        "L3": "L2",
        "L4": "L3",
        "L5": "L4",
        "B1-H0": "L4",
    }
    layer_rows = []
    summary_index = summary.set_index(["language", "case"])
    for language in ("Python", "C++"):
        baseline = summary_index.loc[(language, "L0"), "median_ms"]
        baseline_expanded = summary_index.loc[(language, "L0"), "mean_expanded_nodes"]
        for case, previous in layer_previous.items():
            row = summary_index.loc[(language, case)]
            previous_ms = np.nan if previous is None else summary_index.loc[(language, previous), "median_ms"]
            previous_expanded = np.nan if previous is None else summary_index.loc[(language, previous), "mean_expanded_nodes"]
            layer_rows.append({
                "language": language,
                "case": case,
                "comparison": previous or "baseline",
                "median_ms": float(row["median_ms"]),
                "change_vs_previous_pct": np.nan if previous is None else float((row["median_ms"] / previous_ms - 1) * 100),
                "mean_expanded_nodes": float(row["mean_expanded_nodes"]),
                "expanded_change_vs_previous_pct": np.nan if previous is None else float((row["mean_expanded_nodes"] / previous_expanded - 1) * 100),
                "speedup_vs_L0": float(baseline / row["median_ms"]),
                "expanded_change_vs_L0_pct": float((row["mean_expanded_nodes"] / baseline_expanded - 1) * 100),
            })

    heuristic_cases = ("L4", "L4-PLANE", "L4-ALT4", "L4-ALT8", "L4-ALT16", "L4-MAX4", "L4-MAX8", "L4-MAX16")
    heuristic_rows = []
    for language in ("Python", "C++"):
        subset = query_medians[query_medians["language"] == language]
        raw_subset = raw[raw["language"] == language]
        indexed = raw_subset.pivot(index=["round", "query_id"], columns="case", values="outer_ns")
        l4_expanded = float(summary_index.loc[(language, "L4"), "mean_expanded_nodes"])
        for case in heuristic_cases:
            ratios = indexed["L4"] / indexed[case]
            q1, median, q3 = np.percentile(ratios.to_numpy(), [25, 50, 75])
            row = summary_index.loc[(language, case)]
            heuristic_rows.append({
                "language": language,
                "case": case,
                "median_ms": float(row["median_ms"]),
                "paired_speedup_q1": float(q1),
                "paired_speedup_median": float(median),
                "paired_speedup_q3": float(q3),
                "mean_expanded_nodes": float(row["mean_expanded_nodes"]),
                "expanded_reduction_vs_L4_pct": float((1 - row["mean_expanded_nodes"] / l4_expanded) * 100),
            })
    return pd.DataFrame(layer_rows), pd.DataFrame(heuristic_rows)


def astar_cross_language(raw, query_medians):
    pivot = raw.pivot(index=["case", "round", "query_id"], columns="language", values="outer_ns")
    query_pivot = query_medians.pivot(index=["case", "query_id"], columns="language", values="outer_query_median_ms")
    rows = []
    for case in ASTAR_CASE_ORDER:
        pair = pivot.xs(case, level="case")
        ratios = pair["Python"] / pair["C++"]
        q1, median, q3 = np.percentile(ratios.to_numpy(), [25, 50, 75])
        query_pair = query_pivot.xs(case, level="case")
        rows.append({
            "case": case,
            "python_median_ms": float(pair["Python"].median() / 1e6),
            "cpp_outer_median_ms": float(pair["C++"].median() / 1e6),
            "paired_ratio_median": float(median),
            "ratio_q1": float(q1),
            "ratio_q3": float(q3),
            "python_slower_queries": int((query_pair["Python"] > query_pair["C++"]).sum()),
            "queries": len(query_pair),
        })
    return pd.DataFrame(rows)


def markdown_table(rows, headers):
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join((header, divider, *body))


def fmt_num(value, digits=3):
    if pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"


def plot_comparison(dijkstra_summary, astar_summary, run_dir):
    plt.rcParams.update({
        "figure.dpi": 130,
        "savefig.dpi": 180,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.22,
        "font.size": 9,
    })
    colors = {"Python": "#4477AA", "C++": "#EE7733"}

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True, layout="constrained")
    for ax, language in zip(axes, ("Python", "C++")):
        values = dijkstra_summary[dijkstra_summary["language"] == language].set_index("layer").loc[list(DIJKSTRA_LAYERS)]
        med = values["median_ms"].to_numpy()
        lower = med - values["q1_ms"].to_numpy()
        upper = values["q3_ms"].to_numpy() - med
        ax.bar(np.arange(len(values)), med, color=colors[language], alpha=0.9, width=0.72)
        ax.errorbar(np.arange(len(values)), med, yerr=np.vstack([lower, upper]), fmt="none", ecolor="#222222", capsize=3, linewidth=1)
        ax.set_xticks(np.arange(len(values)), values.index)
        ax.set_yscale("log")
        ax.set_title(language)
        ax.set_xlabel("Algorithm layer")
        ax.grid(axis="y", which="both")
        for x, y in enumerate(med):
            ax.annotate(f"{y:.2g}", (x, y), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7)
    axes[0].set_ylabel("Median query time (ms, log scale; whiskers: Q1–Q3)")
    fig.suptitle("Shenzhen road network — Dijkstra implementations")
    fig.savefig(run_dir / "dijkstra_python_cpp.png", bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True, layout="constrained")
    case_colors = [
        "#4477AA" if case in ("L0", "L0-CachedScale", "L1", "L2", "L3", "L4", "L5", "B1-H0") else "#228833"
        for case in ASTAR_CASE_ORDER
    ]
    for ax, language in zip(axes, ("Python", "C++")):
        values = astar_summary[astar_summary["language"] == language].set_index("case").loc[list(ASTAR_CASE_ORDER)]
        med = values["median_ms"].to_numpy()
        lower = med - values["q1_ms"].to_numpy()
        upper = values["q3_ms"].to_numpy() - med
        x = np.arange(len(values))
        ax.bar(x, med, color=case_colors, alpha=0.9, width=0.78)
        ax.errorbar(x, med, yerr=np.vstack([lower, upper]), fmt="none", ecolor="#222222", capsize=2.5, linewidth=0.8)
        ax.set_xticks(x, values.index, rotation=48, ha="right")
        ax.set_yscale("log")
        ax.set_title(language)
        ax.set_xlabel("A* layer / heuristic")
        ax.grid(axis="y", which="both")
    axes[0].set_ylabel("Median query time (ms, log scale; whiskers: Q1–Q3)")
    fig.suptitle("Shenzhen road network — A* layers and heuristics")
    fig.savefig(run_dir / "astar_python_cpp.png", bbox_inches="tight")
    plt.close(fig)


def write_report(run_dir, graph_data, query_data, metadata, dijkstra_summaries, dijkstra_cross, dijkstra_paired, astar_summary, astar_layer, astar_heuristic, astar_cross, preprocessing):
    dijkstra_py = dijkstra_summaries[dijkstra_summaries["language"] == "Python"]
    dijkstra_cpp = dijkstra_summaries[dijkstra_summaries["language"] == "C++"]
    astar_layers = ("L0", "L0-CachedScale", "L1", "L2", "L3", "L4", "L5", "B1-H0")
    astar_heuristics = ("L4", "L4-PLANE", "L4-ALT4", "L4-ALT8", "L4-ALT16", "L4-MAX4", "L4-MAX8", "L4-MAX16")

    def dijkstra_table(frame, cpp=False):
        rows = []
        for row in frame.itertuples(index=False):
            interval = f"{fmt_num(row.q1_ms)}–{fmt_num(row.q3_ms)}"
            rows.append([
                row.layer,
                fmt_num(row.median_ms),
                interval,
                fmt_num(row.kernel_median_ms) if cpp else "—",
                fmt_num(row.mean_expanded_nodes, 1),
            ])
        return markdown_table(rows, ["层次", "外层中位数 (ms)", "Q1–Q3 (ms)", "C++ 内核中位数 (ms)", "平均 settled 节点"])

    sections = [
        "# 深圳路网 Dijkstra 与 A* 复现实验",
        "",
        f"实验批次：`{run_dir.name}`。算法源码与原武汉实验相同；路网更换为 GitHub 的深圳 `road-d` 距离图及对应坐标，权重单位为米。",
        "",
        "## 数据与实验设置",
        "",
        f"- 数据来源：[{metadata['dataset']['repository']}](https://github.com/yzengal/RoadNetwork-China-City) 的[深圳距离图文件]({metadata['dataset']['distance_archive_url']})及[数据说明页](https://yzengal.github.io/datasets/)；数据说明其 OSM 路网提取时间为 2021 年 2 月、网络类型为 car，距离图权重单位为米；深圳图标注 {graph_data['n_nodes']:,} 个节点、{graph_data['n_edges']:,} 条边。",
        f"- 图策略：`{GRAPH_POLICY}`；保留下载图中的全部节点和有向边，不重新抽取道路、不裁剪连通分量；边 ID 按原文件行序编号。图 SHA-256：`{graph_data['graph_sha256']}`。",
        f"- 固定查询：{len(query_data['queries'])} 对，随机种子 {RANDOM_SEED}；从最大 SCC 取端点，按端点 Haversine 直线距离分五档、每档 20 对。查询集 SHA-256：`{metadata['queries']['sha256']}`。",
        f"- 计时：预热 {WARMUP_COUNT} 对；5 轮；同一查询内随机打乱执行顺序。Dijkstra 按原 notebook 口径，先对每个查询的 5 次计时取中位数，再统计 100 个查询中位数及 Q1–Q3；A* 按其原 notebook 口径，直接对每配置、每语言的 500 次原始计时统计中位数及 Q1–Q3。A* 启发式和跨语言配对耗时比按相同查询、相同轮次的 500 对原始计时计算；“Python 较慢查询”按每查询 5 轮中位数比较。C++ 外层计时包含 ctypes 调用及结果转换，C++ 内核时间由库内 `steady_clock` 计量。",
        f"- 环境：Python {metadata['environment']['python']}、NumPy {metadata['environment']['numpy']}、SciPy {metadata['environment']['scipy']}；Dijkstra {sum(metadata['experiment']['dijkstra_correctness_runs'].values()):,} 次、A* {metadata['experiment']['astar_correctness_runs']:,} 次语言/配置查询正确性检查均通过。",
        "",
        "## Dijkstra 结果",
        "",
        "### Python",
        "",
        dijkstra_table(dijkstra_py),
        "",
        "### C++",
        "",
        dijkstra_table(dijkstra_cpp, cpp=True),
        "",
        "### Python 与 C++ 配对对比",
        "",
        markdown_table([
            [row.layer, fmt_num(row.python_median_ms), fmt_num(row.cpp_outer_median_ms),
             f"{row.paired_ratio_median:.2f} 倍（{row.ratio_q1:.2f}–{row.ratio_q3:.2f}）",
             f"{row.python_slower_queries}/{row.queries}"]
            for row in dijkstra_cross.itertuples(index=False)
        ], ["算法层", "Python 中位数 (ms)", "C++ 外层中位数 (ms)", "配对耗时比 Python/C++", "Python 较慢查询"]),
        "",
        markdown_table([
            [row.language, row.comparison, f"{row.median_speedup_pct:.2f}%", f"{row.q1_speedup_pct:.2f}%–{row.q3_speedup_pct:.2f}%"]
            for row in dijkstra_paired.itertuples(index=False)
        ], ["语言", "相邻层对比", "配对中位提速", "Q1–Q3"]),
        "",
        "## A* 结果",
        "",
        "### Python：逐层实现改进",
        "",
        markdown_table([
            [row.case, fmt_num(row.median_ms), f"{fmt_num(row.q1_ms)}–{fmt_num(row.q3_ms)}", fmt_num(row.mean_expanded_nodes, 1)]
            for row in astar_summary[(astar_summary.language == "Python") & astar_summary.case.isin(astar_layers)].itertuples(index=False)
        ], ["层次", "中位耗时 (ms)", "Q1–Q3 (ms)", "平均展开节点"]),
        "",
        "### C++：逐层实现改进",
        "",
        markdown_table([
            [row.case, fmt_num(row.median_ms), f"{fmt_num(row.q1_ms)}–{fmt_num(row.q3_ms)}", fmt_num(row.kernel_median_ms), fmt_num(row.mean_expanded_nodes, 1)]
            for row in astar_summary[(astar_summary.language == "C++") & astar_summary.case.isin(astar_layers)].itertuples(index=False)
        ], ["层次", "外层中位耗时 (ms)", "Q1–Q3 (ms)", "内核中位耗时 (ms)", "平均展开节点"]),
        "",
        "### Python：启发函数与地标数",
        "",
        markdown_table([
            [row.case, fmt_num(row.median_ms), f"{row.paired_speedup_median:.2f} 倍（{row.paired_speedup_q1:.2f}–{row.paired_speedup_q3:.2f}）", fmt_num(row.mean_expanded_nodes, 1), f"{row.expanded_reduction_vs_L4_pct:.1f}%"]
            for row in astar_heuristic[astar_heuristic.language == "Python"].itertuples(index=False)
        ], ["L4 启发式", "中位耗时 (ms)", "相对 L4 配对提速", "平均展开节点", "展开减少"]),
        "",
        "### C++：启发函数与地标数",
        "",
        markdown_table([
            [row.case, fmt_num(row.median_ms), f"{row.paired_speedup_median:.2f} 倍（{row.paired_speedup_q1:.2f}–{row.paired_speedup_q3:.2f}）", fmt_num(row.mean_expanded_nodes, 1), f"{row.expanded_reduction_vs_L4_pct:.1f}%"]
            for row in astar_heuristic[astar_heuristic.language == "C++"].itertuples(index=False)
        ], ["L4 启发式", "中位耗时 (ms)", "相对 L4 配对提速", "平均展开节点", "展开减少"]),
        "",
        "### A* Python/C++ 对比",
        "",
        markdown_table([
            [row.case, fmt_num(row.python_median_ms), fmt_num(row.cpp_outer_median_ms),
             f"{row.paired_ratio_median:.2f} 倍（{row.ratio_q1:.2f}–{row.ratio_q3:.2f}）",
             f"{row.python_slower_queries}/{row.queries}"]
            for row in astar_cross.itertuples(index=False)
        ], ["配置", "Python 中位数 (ms)", "C++ 外层中位数 (ms)", "配对耗时比 Python/C++", "Python 较慢查询"]),
        "",
        "## 预处理与结果解释",
        "",
        markdown_table([
            [row.language, row.stage, fmt_num(row.elapsed_ms)]
            for row in preprocessing.itertuples(index=False)
        ], ["语言", "预处理项", "耗时 (ms)"]),
        "",
        "Dijkstra 与 A* 的正式计时都不包含图下载、文本解析、图校验、CSR/邻接表构建、反向图构建、几何比例计算、SCC 计算、地标选择和 ALT 表计算；这些成本另列于上表。A* 的 ALT4/8/16 与 MAX4/8/16 共享一次 ALT-16 预处理表，查询时使用其前缀。",
        "",
        "启发式实验固定在 L4 上进行；`MAX-k` 指 `max(H0, ALT-k)`。Dijkstra 配对变化的 Q1–Q3 按 100 个查询汇总；A* 启发式和 Python/C++ 配对耗时比的 Q1–Q3 按 500 组相同查询、相同轮次的原始计时比汇总；两者均是观测分布范围，不是置信区间。深圳图包含零权重边时，只有在端点球面距离为正的边才参与 H0/平面安全比例估计；本数据的 4 条零权重边端点坐标重合，因此不把安全比例压为零。",
        "",
        "## 图表",
        "",
        "![Dijkstra Python/C++ latency comparison](dijkstra_python_cpp.png)",
        "",
        "![A* Python/C++ latency comparison](astar_python_cpp.png)",
        "",
        "## 复现文件与限制",
        "",
        "原始代码和 notebook 未修改。脚本直接导入现有 A2 基线、各层 Python 实现及与其源码哈希匹配的 C++ DLL；本目录只新增深圳实验文件。原始数据来自 OSM 的 2021 年提取版本，不能据此代表当前深圳路况；这里比较的是固定图上的静态距离最短路，不含实时交通/时间权重。",
        "",
        "结果文件：`dijkstra_python_raw.csv`、`dijkstra_cpp_raw.csv`、`dijkstra_python_summary.csv`、`dijkstra_cpp_summary.csv`、`dijkstra_cross_language.csv`、`astar_raw.csv`、`astar_summary.csv`、`astar_layer_analysis.csv`、`astar_heuristic_analysis.csv`、`astar_cross_language.csv`、`experiment_metadata.json`。",
    ]
    (run_dir / "深圳路网_Dijkstra与A星实验报告.md").write_text("\n".join(sections) + "\n", encoding="utf-8")


def refresh_existing_run(run_dir):
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_relative_to(OUTPUT_ROOT.resolve()) or not run_dir.is_dir():
        raise ValueError(f"refresh target must be an existing run under {OUTPUT_ROOT}")

    metadata_file = run_dir / "experiment_metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    astar_raw = pd.read_csv(run_dir / "astar_raw.csv")
    astar_qm = astar_query_summary(astar_raw)
    astar_summary = summarize_astar(astar_raw)
    astar_layer, astar_heuristic = analyze_astar(astar_raw, astar_qm, astar_summary)
    astar_cross = astar_cross_language(astar_raw, astar_qm)

    astar_qm.to_csv(run_dir / "astar_query_medians.csv", index=False, encoding="utf-8-sig")
    astar_summary.to_csv(run_dir / "astar_summary.csv", index=False, encoding="utf-8-sig")
    astar_layer.to_csv(run_dir / "astar_layer_analysis.csv", index=False, encoding="utf-8-sig")
    astar_heuristic.to_csv(run_dir / "astar_heuristic_analysis.csv", index=False, encoding="utf-8-sig")
    astar_cross.to_csv(run_dir / "astar_cross_language.csv", index=False, encoding="utf-8-sig")

    dijkstra_py = pd.read_csv(run_dir / "dijkstra_python_summary.csv")
    dijkstra_cpp = pd.read_csv(run_dir / "dijkstra_cpp_summary.csv")
    dijkstra_summaries = pd.concat([
        dijkstra_py.drop(columns="kernel_median_ms"), dijkstra_cpp,
    ], ignore_index=True)
    dijkstra_cross = pd.read_csv(run_dir / "dijkstra_cross_language.csv")
    dijkstra_paired = pd.read_csv(run_dir / "dijkstra_paired_changes.csv")
    preprocessing = pd.read_csv(run_dir / "preprocessing_times.csv")
    query_data = json.loads((run_dir / "stratified_queries_100.json").read_text(encoding="utf-8"))
    graph_meta = metadata["dataset"]
    graph_data = {
        "n_nodes": graph_meta["nodes"],
        "n_edges": graph_meta["directed_edges"],
        "zero_weight_edges": graph_meta["zero_weight_edges"],
        "graph_sha256": graph_meta["graph_sha256"],
        "parse_ns": graph_meta["graph_parse_ms"] * 1e6,
    }

    metadata["experiment"]["aggregation"] = {
        "Dijkstra": "median of five timings per query, then median and Q1-Q3 across 100 query medians",
        "A*": "median and Q1-Q3 across 500 raw timings per configuration and language, matching Astar_pro.ipynb",
        "A*_paired_ratios": "paired raw timing ratios for the same query and round (500 pairs); slower-query counts compare per-query five-round medians",
    }
    metadata_file.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    plot_comparison(dijkstra_summaries, astar_summary, run_dir)
    write_report(
        run_dir, graph_data, query_data, metadata, dijkstra_summaries,
        dijkstra_cross, dijkstra_paired, astar_summary, astar_layer,
        astar_heuristic, astar_cross, preprocessing,
    )
    print(f"Refreshed A* summaries using original notebook aggregation: {run_dir}")
    print(astar_summary[["language", "case", "median_ms", "q1_ms", "q3_ms", "mean_expanded_nodes"]].to_string(index=False))


def main():
    missing = [path for path in (ROAD_FILE, COORD_FILE) if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing extracted dataset files: " + ", ".join(map(str, missing)))

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{time.perf_counter_ns() % 1_000_000:06d}"
    run_dir = OUTPUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    print(f"Output: {run_dir}", flush=True)

    py_dijkstra_file = BASELINE_DIR / "dijkstra.py"
    py_dijkstra_variants_file = ALGORITHM_DIR / "dijkstra_variants.py"
    cpp_dijkstra_file = ALGORITHM_DIR / "dijkstra_cpp.cpp"
    py_astar_file = BASELINE_DIR / "astar.py"
    py_astar_variants_file = ALGORITHM_DIR / "astar_variants.py"
    cpp_astar_file = ALGORITHM_DIR / "astar_cpp.cpp"
    cpp_dijkstra_dll = ALGORITHM_DIR / ".build" / "dijkstra_cpp.dll"
    dijkstra_old_meta = ALGORITHM_DIR / ".build" / "cpp_dijkstra_metadata.json"
    cpp_flags = CPP_FLAGS
    astar_key = hashlib.sha256(
        (sha256_file(cpp_astar_file) + "|".join(cpp_flags)).encode("utf-8")
    ).hexdigest()[:12]
    cpp_astar_dll = ALGORITHM_DIR / ".build" / f"astar_cpp_{astar_key}.dll"
    required = [
        py_dijkstra_file, py_dijkstra_variants_file, cpp_dijkstra_file, cpp_dijkstra_dll,
        py_astar_file, py_astar_variants_file, cpp_astar_file, cpp_astar_dll, dijkstra_old_meta,
    ]
    if any(not path.is_file() for path in required):
        raise FileNotFoundError("an existing algorithm source or matching C++ library is missing")

    dijkstra_meta = json.loads(dijkstra_old_meta.read_text(encoding="utf-8"))
    if dijkstra_meta["implementation"]["source_sha256"] != sha256_file(cpp_dijkstra_file):
        raise RuntimeError("Dijkstra DLL metadata does not match the current C++ source")
    if dijkstra_meta["implementation"]["dll_sha256"] != sha256_file(cpp_dijkstra_dll):
        raise RuntimeError("Dijkstra DLL hash does not match its recorded build")

    baseline = load_module("shenzhen_dijkstra_baseline", py_dijkstra_file)
    dijkstra_variants = load_module("shenzhen_dijkstra_variants", py_dijkstra_variants_file)
    astar_baseline = load_module("shenzhen_astar_baseline", py_astar_file)
    astar_variants = load_module("shenzhen_astar_variants", py_astar_variants_file)
    astar_variants.self_test()
    print("Existing Python self-test passed; source hashes verified.", flush=True)

    graph_data = load_shenzhen_graph()
    query_started = time.perf_counter_ns()
    query_data, scc_count, scc_sizes, scc_labels, landmark_component, candidates = make_queries(
        graph_data, astar_variants
    )
    query_prep_ns = time.perf_counter_ns() - query_started
    queries = query_data["queries"]
    if len(queries) != QUERY_COUNT:
        raise AssertionError("query count differs from experiment protocol")
    (run_dir / "stratified_queries_100.json").write_text(
        json.dumps(query_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    query_sha = sha256_file(run_dir / "stratified_queries_100.json")
    band_counts = dict(Counter(query["straight_distance_band"] for query in queries))
    print(
        f"Graph parsed: {graph_data['n_nodes']:,} nodes, {graph_data['n_edges']:,} directed edges; "
        f"SCC={scc_count}, largest={int(scc_sizes[landmark_component]):,}; queries={band_counts}",
        flush=True,
    )

    graph, positions, adjacency_ns = build_python_graph(graph_data)
    csr_graph = {
        "n_nodes": graph_data["n_nodes"],
        "indptr": graph_data["indptr"],
        "indices": graph_data["indices"],
        "weights": graph_data["weights"],
        "edge_ids": graph_data["edge_ids"],
    }

    prep_rows = [
        {"language": "Shared", "stage": "road/coordinate parse and CSR arrays", "elapsed_ms": graph_data["parse_ns"] / 1e6},
        {"language": "Shared", "stage": "fixed-query SCC and stratified sampling", "elapsed_ms": query_prep_ns / 1e6},
        {"language": "Python", "stage": "adjacency and coordinate dictionaries", "elapsed_ms": adjacency_ns / 1e6},
    ]

    dijkstra_precheck_ns = precheck_dijkstra_graph(graph, graph_data)
    dijkstra_reverse_started = time.perf_counter_ns()
    dijkstra_reverse = build_reverse_graph(graph)
    dijkstra_reverse_ns = time.perf_counter_ns() - dijkstra_reverse_started
    prep_rows.extend([
        {"language": "Python", "stage": "Dijkstra L1 full-graph precheck", "elapsed_ms": dijkstra_precheck_ns / 1e6},
        {"language": "Python", "stage": "Dijkstra B1 reverse graph", "elapsed_ms": dijkstra_reverse_ns / 1e6},
    ])

    dijkstra_cpp = configure_dijkstra_cpp(cpp_dijkstra_dll, graph_data)
    prep_rows.append({"language": "C++", "stage": "Dijkstra graph creation", "elapsed_ms": dijkstra_cpp["create_ns"] / 1e6})

    def py_dijkstra_runner(layer, source, target):
        return run_dijkstra_python(
            baseline, dijkstra_variants, layer, graph, dijkstra_reverse, csr_graph, source, target
        )

    def cpp_dijkstra_runner(layer, source, target):
        return run_dijkstra_cpp(dijkstra_cpp, layer, source, target)

    py_dijkstra_checked, _ = run_dijkstra_correctness("Python", py_dijkstra_runner, queries, graph_data)
    cpp_dijkstra_checked, _ = run_dijkstra_correctness("C++", cpp_dijkstra_runner, queries, graph_data)
    print(f"Dijkstra correctness passed: Python={py_dijkstra_checked}, C++={cpp_dijkstra_checked}", flush=True)

    dijkstra_py_raw = benchmark_dijkstra("Python", py_dijkstra_runner, queries)
    dijkstra_cpp_raw = benchmark_dijkstra("C++", cpp_dijkstra_runner, queries)
    dijkstra_py_qm = dijkstra_query_summary(dijkstra_py_raw)
    dijkstra_cpp_qm = dijkstra_query_summary(dijkstra_cpp_raw)
    dijkstra_py_summary = summarize_dijkstra(dijkstra_py_qm)
    dijkstra_cpp_summary = summarize_dijkstra(dijkstra_cpp_qm)
    dijkstra_py_summary.insert(0, "language", "Python")
    dijkstra_cpp_summary.insert(0, "language", "C++")
    dijkstra_cross = dijkstra_cross_language(dijkstra_py_qm, dijkstra_cpp_qm)
    dijkstra_paired = dijkstra_paired_analysis(dijkstra_py_qm, dijkstra_cpp_qm)

    dijkstra_py_raw.to_csv(run_dir / "dijkstra_python_raw.csv", index=False, encoding="utf-8-sig")
    dijkstra_cpp_raw.to_csv(run_dir / "dijkstra_cpp_raw.csv", index=False, encoding="utf-8-sig")
    dijkstra_py_qm.to_csv(run_dir / "dijkstra_python_query_medians.csv", index=False, encoding="utf-8-sig")
    dijkstra_cpp_qm.to_csv(run_dir / "dijkstra_cpp_query_medians.csv", index=False, encoding="utf-8-sig")
    dijkstra_py_summary.to_csv(run_dir / "dijkstra_python_summary.csv", index=False, encoding="utf-8-sig")
    dijkstra_cpp_summary.to_csv(run_dir / "dijkstra_cpp_summary.csv", index=False, encoding="utf-8-sig")
    dijkstra_cross.to_csv(run_dir / "dijkstra_cross_language.csv", index=False, encoding="utf-8-sig")
    dijkstra_paired.to_csv(run_dir / "dijkstra_paired_changes.csv", index=False, encoding="utf-8-sig")

    # A* preparation follows the existing notebook: all one-time data is outside query timing.
    py_prep = {}
    started = time.perf_counter_ns()
    if astar_variants.prevalidate_graph(graph, positions) != graph_data["n_nodes"]:
        raise ValueError("A* graph precheck returned the wrong node count")
    py_prep["graph_validation"] = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    h0_scale = astar_variants.estimate_heuristic_scale(graph, positions)
    py_prep["h0_scale"] = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    projected = astar_variants.project_coordinates(positions)
    plane_scale = astar_variants.estimate_plane_scale(graph, projected)
    py_prep["plane"] = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    astar_reverse = astar_variants.build_reverse_graph(graph)
    py_prep["reverse_graph"] = time.perf_counter_ns() - started

    same_scc_counts = Counter(
        int(scc_labels[int(query["source"])])
        for query in queries
        if scc_labels[int(query["source"])] == scc_labels[int(query["target"])]
    )
    if same_scc_counts:
        landmark_component = min(
            same_scc_counts,
            key=lambda component: (-same_scc_counts[component], -scc_sizes[component], component),
        )
    landmark_candidates = np.flatnonzero(scc_labels == landmark_component).tolist()
    if len(landmark_candidates) < 16:
        raise ValueError("ALT-16 component has fewer than 16 nodes")
    started = time.perf_counter_ns()
    landmark_ids = astar_variants.select_landmarks(positions, landmark_candidates, count_requested=16)
    py_prep["landmark_selection"] = time.perf_counter_ns() - started
    started = time.perf_counter_ns()
    alt_tables = astar_variants.prepare_landmarks(graph, landmark_ids)
    py_prep["alt_tables"] = time.perf_counter_ns() - started

    astar_cpp = configure_astar_cpp(cpp_astar_dll, graph_data)
    prep_rows.append({"language": "C++", "stage": "A* graph creation", "elapsed_ms": astar_cpp["create_ns"] / 1e6})
    prepare_astar_cpp(astar_cpp, graph_data, landmark_ids)
    prep_rows.extend([
        {"language": "Python", "stage": f"A* {stage}", "elapsed_ms": elapsed_ns / 1e6}
        for stage, elapsed_ns in py_prep.items()
    ])
    prep_rows.extend([
        {"language": "C++", "stage": "A* geometry (outer)", "elapsed_ms": astar_cpp["prep"]["geometry_outer_ns"] / 1e6},
        {"language": "C++", "stage": "A* geometry (kernel)", "elapsed_ms": astar_cpp["prep"]["geometry_kernel_ns"] / 1e6},
        {"language": "C++", "stage": "A* reverse graph (outer)", "elapsed_ms": astar_cpp["prep"]["reverse_outer_ns"] / 1e6},
        {"language": "C++", "stage": "A* reverse graph (kernel)", "elapsed_ms": astar_cpp["prep"]["reverse_kernel_ns"] / 1e6},
        {"language": "C++", "stage": "A* ALT (outer)", "elapsed_ms": astar_cpp["prep"]["alt_outer_ns"] / 1e6},
        {"language": "C++", "stage": "A* ALT (kernel)", "elapsed_ms": astar_cpp["prep"]["alt_kernel_ns"] / 1e6},
    ])

    def py_astar_runner(case, source, target):
        return run_astar_python(
            case, source, target, astar_baseline, astar_variants, graph, astar_reverse,
            positions, (graph_data["indptr"], graph_data["indices"], graph_data["weights"], graph_data["edge_ids"]),
            h0_scale, projected, plane_scale, alt_tables,
        )

    astar_checked = run_astar_correctness(queries, py_astar_runner, astar_cpp, graph_data)
    print(
        f"A* correctness passed: {astar_checked}; landmarks={landmark_ids}; "
        f"scales H0={h0_scale:.12g}, C++={astar_cpp['h0_scale']:.12g}, "
        f"plane={plane_scale:.12g}, C++={astar_cpp['plane_scale']:.12g}",
        flush=True,
    )
    astar_raw = benchmark_astar(queries, py_astar_runner, astar_cpp)
    astar_qm = astar_query_summary(astar_raw)
    astar_summary = summarize_astar(astar_raw)
    astar_layer, astar_heuristic = analyze_astar(astar_raw, astar_qm, astar_summary)
    astar_cross = astar_cross_language(astar_raw, astar_qm)
    astar_raw.to_csv(run_dir / "astar_raw.csv", index=False, encoding="utf-8-sig")
    astar_qm.to_csv(run_dir / "astar_query_medians.csv", index=False, encoding="utf-8-sig")
    astar_summary.to_csv(run_dir / "astar_summary.csv", index=False, encoding="utf-8-sig")
    astar_layer.to_csv(run_dir / "astar_layer_analysis.csv", index=False, encoding="utf-8-sig")
    astar_heuristic.to_csv(run_dir / "astar_heuristic_analysis.csv", index=False, encoding="utf-8-sig")
    astar_cross.to_csv(run_dir / "astar_cross_language.csv", index=False, encoding="utf-8-sig")

    preprocessing = pd.DataFrame(prep_rows)
    preprocessing.to_csv(run_dir / "preprocessing_times.csv", index=False, encoding="utf-8-sig")
    all_dijkstra_summary = pd.concat([
        dijkstra_py_summary.drop(columns="kernel_median_ms"),
        dijkstra_cpp_summary,
    ], ignore_index=True)
    plot_comparison(all_dijkstra_summary, astar_summary, run_dir)

    metadata = {
        "run_id": run_id,
        "dataset": {
            "repository": "yzengal/RoadNetwork-China-City",
            "distance_archive_url": "https://github.com/yzengal/RoadNetwork-China-City/blob/main/Shenzhen.road-d.tar.gz",
            "coordinate_archive_url": "https://github.com/yzengal/RoadNetwork-China-City/blob/main/Shenzhen.co.tar.gz",
            "graph_policy": GRAPH_POLICY,
            "graph_sha256": graph_data["graph_sha256"],
            "road_archive_sha256": sha256_file(DATA_DIR / "原始" / "Shenzhen.road-d.tar.gz"),
            "coordinate_archive_sha256": sha256_file(DATA_DIR / "原始" / "Shenzhen.co.tar.gz"),
            "road_file_sha256": sha256_file(ROAD_FILE),
            "coordinate_file_sha256": sha256_file(COORD_FILE),
            "nodes": graph_data["n_nodes"],
            "directed_edges": graph_data["n_edges"],
            "zero_weight_edges": graph_data["zero_weight_edges"],
            "scc_count": int(scc_count),
            "largest_scc_nodes": int(scc_sizes[landmark_component]),
            "graph_parse_ms": graph_data["parse_ns"] / 1e6,
        },
        "queries": {
            "file": "stratified_queries_100.json",
            "sha256": query_sha,
            "count": len(queries),
            "seed": RANDOM_SEED,
            "strata": band_counts,
            "same_scc_count": sum(
                scc_labels[int(query["source"])] == scc_labels[int(query["target"])]
                for query in queries
            ),
        },
        "experiment": {
            "rounds": ROUNDS,
            "warmup_queries": WARMUP_COUNT,
            "random_seed": RANDOM_SEED,
            "dijkstra_layers": DIJKSTRA_LAYERS,
            "astar_cases": ASTAR_CASE_ORDER,
            "aggregation": {
                "Dijkstra": "median of five timings per query, then median and Q1-Q3 across 100 query medians",
                "A*": "median and Q1-Q3 across 500 raw timings per configuration and language, matching Astar_pro.ipynb",
                "A*_paired_ratios": "paired raw timing ratios for the same query and round (500 pairs); slower-query counts compare per-query five-round medians",
            },
            "timing": "perf_counter_ns outer; C++ kernel uses library steady_clock; precomputation excluded from per-query latency",
            "dijkstra_correctness_runs": {"Python": py_dijkstra_checked, "C++": cpp_dijkstra_checked},
            "astar_correctness_runs": astar_checked,
            "correctness_passed": True,
            "astar_landmark_ids": [int(value) for value in landmark_ids],
            "h0_scale_python": h0_scale,
            "h0_scale_cpp": astar_cpp["h0_scale"],
            "plane_scale_python": plane_scale,
            "plane_scale_cpp": astar_cpp["plane_scale"],
        },
        "preprocessing_ns": {
            "python_astar": py_prep,
            "cpp_astar": astar_cpp["prep"],
            "dijkstra_python_precheck": dijkstra_precheck_ns,
            "dijkstra_python_reverse_graph": dijkstra_reverse_ns,
            "dijkstra_cpp_graph_create": dijkstra_cpp["create_ns"],
            "astar_cpp_graph_create": astar_cpp["create_ns"],
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "numpy": np.__version__,
            "scipy": __import__("scipy").__version__,
            "pandas": pd.__version__,
            "matplotlib": __import__("matplotlib").__version__,
        },
        "algorithm_files": {
            "dijkstra_baseline_sha256": sha256_file(py_dijkstra_file),
            "dijkstra_variants_sha256": sha256_file(py_dijkstra_variants_file),
            "dijkstra_cpp_source_sha256": sha256_file(cpp_dijkstra_file),
            "dijkstra_cpp_dll_sha256": sha256_file(cpp_dijkstra_dll),
            "astar_baseline_sha256": sha256_file(py_astar_file),
            "astar_variants_sha256": sha256_file(py_astar_variants_file),
            "astar_cpp_source_sha256": sha256_file(cpp_astar_file),
            "astar_cpp_dll_sha256": sha256_file(cpp_astar_dll),
        },
    }
    (run_dir / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=lambda value: value.item() if hasattr(value, "item") else str(value)) + "\n",
        encoding="utf-8",
    )
    write_report(
        run_dir, graph_data, query_data, metadata, all_dijkstra_summary,
        dijkstra_cross, dijkstra_paired, astar_summary, astar_layer,
        astar_heuristic, astar_cross, preprocessing,
    )

    dijkstra_cpp["library"].dijkstra_graph_destroy(dijkstra_cpp["handle"])
    astar_cpp["library"].astar_graph_destroy(astar_cpp["handle"])
    print(f"\nCompleted. Report: {run_dir / '深圳路网_Dijkstra与A星实验报告.md'}", flush=True)
    print(f"Dijkstra raw rows: Python={len(dijkstra_py_raw):,}; C++={len(dijkstra_cpp_raw):,}", flush=True)
    print(f"A* raw rows: {len(astar_raw):,}", flush=True)
    print("Dijkstra summary:")
    print(dijkstra_cross.to_string(index=False))
    print("A* summary:")
    print(astar_summary[["language", "case", "median_ms", "q1_ms", "q3_ms", "mean_expanded_nodes"]].to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--refresh-existing":
        refresh_existing_run(sys.argv[2])
    else:
        main()
