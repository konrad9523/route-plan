"""Shared runner and JSON-ready aggregation for the A3 live comparison demo."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import secrets
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median


INTERFACE_DIR = Path(__file__).resolve().parent
CALLS_DIR = INTERFACE_DIR.parent
A3_DIR = CALLS_DIR.parent
REPO_ROOT = A3_DIR.parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "a3_network_manifest.json"
EXECUTABLE = CALLS_DIR / ".build" / "performance_comparison.exe"
BUILD_SCRIPT = CALLS_DIR / "cpp" / "build_performance_comparison.ps1"
GRAPH_CACHE = CALLS_DIR / ".build" / "graph_cache"
CH_INDEX_CACHE = CALLS_DIR / ".build" / "ch_index"
CH_CACHE_SOURCES = (
    A3_DIR / "05_CH" / "cpp" / "ch_c_api.cpp",
    A3_DIR / "05_CH" / "cpp" / "ch.cpp",
    REPO_ROOT / "workspaces" / "A2_算法" / "algorithms.hpp",
    REPO_ROOT / "workspaces" / "A2_算法" / "graph_types.hpp",
)

NETWORKS = {
    "nanshan": {"label": "南山", "graphml": "nanshan_driving_a1_fixed.graphml"},
    "shenzhen": {"label": "深圳", "graphml": "shenzhen_driving_a1_fixed.graphml"},
    "guangdong": {"label": "广东", "graphml": "guangdong_driving_a1_fixed.graphml"},
}
ALGORITHMS = {
    "dijkstra": {
        "label": "Dijkstra L4", "version": "L4",
        "expanded_count_semantics": "单向搜索确定节点数",
    },
    "astar": {
        "label": "A* L4 + MAX-8", "version": "L4", "heuristic": "MAX", "landmarks": 8,
        "expanded_count_semantics": "单向搜索展开节点数",
    },
    "bidirectional_astar": {
        "label": "双向 A* L4 BAE* + MAX-8", "version": "L4 BAE*",
        "heuristic": "MAX", "landmarks": 8,
        "expanded_count_semantics": "正反向展开状态数之和",
    },
    "bidirectional_dijkstra": {
        "label": "双向 Dijkstra B1", "version": "B1",
        "expanded_count_semantics": "正反向确定节点数之和",
    },
    "ch": {
        "label": "CH", "version": "Contraction Hierarchies",
        "expanded_count_semantics": "CH 层次图展开节点数",
    },
}
_ALGORITHM_ALIASES = {
    "dijkstra": "dijkstra",
    "Dijkstra L4": "dijkstra",
    "astar": "astar",
    "A* L4 MAX-8": "astar",
    "bidirectional_astar": "bidirectional_astar",
    "双向 A* L4 MAX-8": "bidirectional_astar",
    "bidirectional_dijkstra": "bidirectional_dijkstra",
    "双向 Dijkstra B1": "bidirectional_dijkstra",
    "ch": "ch",
    "CH": "ch",
}
_ALGORITHM_ORDER = tuple(ALGORITHMS)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a quantile from no values")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _network_payload(result_dir: Path, network_id: str) -> dict:
    raw_rows = _read_csv(result_dir / f"{network_id}_raw.csv")
    prep_rows = _read_csv(result_dir / f"{network_id}_preprocess.csv")
    if not raw_rows or len(prep_rows) != 1:
        raise ValueError(f"{network_id}: raw timings or preprocessing record is missing")

    normalized = []
    timings = defaultdict(lambda: defaultdict(list))
    expansions = defaultdict(list)
    distances = defaultdict(dict)
    query_map = {}
    for row in raw_rows:
        algorithm = _ALGORITHM_ALIASES.get(row["algorithm"])
        if algorithm is None:
            raise ValueError(f"unsupported algorithm in result file: {row['algorithm']!r}")
        query_id = int(row["query"])
        elapsed_ms = int(row["elapsed_ns"]) / 1_000_000
        normalized_row = {
            "query": query_id,
            "source": int(row["source_index"]),
            "target": int(row["target_index"]),
            "algorithm": algorithm,
            "round": int(row["round"]),
            "elapsed_ms": elapsed_ms,
            "kernel_ms": int(row["kernel_ns"]) / 1_000_000,
            "distance_m": float(row["distance_m"]),
            "expanded_nodes": int(row["expanded_nodes"]),
            "queue_pushes": int(row["queue_pushes"]),
            "scanned_edges": int(row["scanned_edges"]),
        }
        normalized.append(normalized_row)
        timings[algorithm][query_id].append(elapsed_ms)
        expansions[algorithm].append(normalized_row["expanded_nodes"])
        distances[algorithm][query_id] = normalized_row["distance_m"]
        query_map[query_id] = {
            "query": query_id,
            "source": normalized_row["source"],
            "target": normalized_row["target"],
        }

    query_medians = {
        algorithm: {
            query_id: median(repeats) for query_id, repeats in per_query.items()
        }
        for algorithm, per_query in timings.items()
    }
    algorithms_present = [a for a in _ALGORITHM_ORDER if a in timings]
    summary = []
    for algorithm in algorithms_present:
        sample = list(query_medians[algorithm].values())
        reference = query_medians.get("dijkstra", {})
        paired_ratios = [
            reference[q] / query_medians[algorithm][q]
            for q in query_medians[algorithm]
            if q in reference and query_medians[algorithm][q] > 0
        ]
        config = ALGORITHMS[algorithm]
        summary.append({
            "algorithm": algorithm,
            "label": config["label"],
            "version": config["version"],
            "median_ms": median(sample),
            "q1_ms": _quantile(sample, 0.25),
            "q3_ms": _quantile(sample, 0.75),
            "mean_expanded_count": fmean(expansions[algorithm]),
            "expanded_count_semantics": config["expanded_count_semantics"],
            "paired_speedup_vs_dijkstra": median(paired_ratios) if paired_ratios else None,
            "per_query_median_ms": [query_medians[algorithm][q] for q in sorted(query_medians[algorithm])],
        })

    reference_distances = distances.get("dijkstra")
    if reference_distances is None and len(algorithms_present) > 1:
        reference_distances = distances[algorithms_present[0]]
    # The native runner checks every selected result against Dijkstra L4,
    # including when Dijkstra itself was not selected for timed reporting.
    distance_crosschecked = bool(algorithms_present)
    if distance_crosschecked and reference_distances is not None:
        for algorithm in algorithms_present:
            for query_id, distance in distances[algorithm].items():
                if query_id not in reference_distances or abs(distance - reference_distances[query_id]) > max(1e-5, abs(reference_distances[query_id]) * 1e-8):
                    raise ValueError(f"{network_id}: {algorithm} path distance disagrees for query {query_id}")

    prep = prep_rows[0]
    conversion_path = result_dir / "graphml_conversion.csv"
    conversion_ms = None
    if conversion_path.is_file():
        conversion = {row["network"]: row for row in _read_csv(conversion_path)}
        if network_id in conversion:
            conversion_ms = float(conversion[network_id]["graphml_to_binary_ms"])

    graph_meta = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_item = next(item for item in graph_meta["files"] if item["filename"] == NETWORKS[network_id]["graphml"])
    return {
        "network": {
            "id": network_id,
            "label": NETWORKS[network_id]["label"],
            "nodes": int(prep["nodes"]),
            "directed_edges": int(prep["directed_edges"]),
            "graph_sha256": manifest_item["sha256"],
            "query_component_nodes": int(prep["query_component_nodes"]),
        },
        "config": {
            "query_count": len(query_map),
            "rounds": int(prep["rounds"]),
            "landmarks": int(prep["landmarks"]),
            "sample_method": "runtime uniform sampling of unique ordered node pairs from the largest strongly connected component",
            "landmark_method": (
                "deterministic geographic farthest-point selection from the largest strongly connected component"
                if int(prep["landmarks"]) else None
            ),
        },
        "correctness": {
            "route_shape_and_edge_weight_sum": True,
            "selected_algorithm_distances_crosschecked": distance_crosschecked,
        },
        "preprocessing_ms": {
            "query_generation": float(prep["query_generation_ms"]),
            "landmark_selection": float(prep["landmark_selection_ms"]),
            "graphml_to_binary": conversion_ms,
            "binary_load_and_csr": float(prep["binary_load_and_csr_ms"]),
            "dijkstra_graph_init": _number_or_none(prep.get("dijkstra_graph_init_ms")),
            "astar_geometry_reverse_alt8": _number_or_none(prep.get("astar_graph_geometry_reverse_alt_ms")),
            "bidirectional_index_alt8": _number_or_none(prep.get("bidirectional_index_alt_ms")),
            "ch_preprocessing": _number_or_none(prep.get("ch_preprocess_ms")),
            "ch_cache_load": _number_or_none(prep.get("ch_cache_load_ms")),
            "ch_cache_hit": _bool_or_none(prep.get("ch_cache_hit")),
            "ch_setup": _number_or_none(prep.get("ch_setup_ms")),
            "ch_hierarchy_arcs": _integer_or_none(prep.get("ch_hierarchy_arcs")),
            "ch_shortcut_count": _integer_or_none(prep.get("ch_shortcut_count")),
        },
        "algorithms": summary,
        "queries": [query_map[key] for key in sorted(query_map)],
        "raw_runs": normalized,
    }


def _number_or_none(value: str | None):
    return None if value in (None, "") else float(value)


def _integer_or_none(value: str | None):
    return None if value in (None, "") else int(value)


def _bool_or_none(value: str | None):
    return None if value in (None, "") else value == "1"


def build_frontend_payload(result_dir, networks=None) -> dict:
    """Build a JSON-serializable table/chart payload from persisted raw CSVs."""
    result_dir = Path(result_dir)
    network_ids = tuple(networks or NETWORKS)
    unknown = set(network_ids) - NETWORKS.keys()
    if unknown:
        raise ValueError(f"unknown network IDs: {sorted(unknown)}")
    payload = {
        "schema_version": "a3.performance.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timing_semantics": "elapsed_ns around the C++ query call, including path reconstruction and output-buffer copy; graph conversion and preprocessing are reported separately",
        "networks": [_network_payload(result_dir, network_id) for network_id in network_ids],
    }
    return payload


def build_frontend_response(payload: dict) -> dict:
    """Remove benchmark-only raw rows and keep the JSON fields used by the UI."""
    return {
        "schema_version": payload["schema_version"],
        "created_at": payload["created_at"],
        "timing_semantics": payload["timing_semantics"],
        "networks": [
            {
                "network": item["network"],
                "config": item["config"],
                "preprocessing_ms": item["preprocessing_ms"],
                "correctness": item["correctness"],
                "table": [
                    {key: row[key] for key in (
                        "algorithm", "label", "version", "median_ms", "q1_ms", "q3_ms",
                        "mean_expanded_count", "expanded_count_semantics",
                        "paired_speedup_vs_dijkstra",
                    )}
                    for row in item["algorithms"]
                ],
                "chart_data": [
                    {key: row[key] for key in (
                        "algorithm", "label", "median_ms", "q1_ms", "q3_ms",
                        "per_query_median_ms",
                    )}
                    for row in item["algorithms"]
                ],
                "queries": item["queries"],
            }
            for item in payload["networks"]
        ],
    }


def _load_converter():
    converter_path = A3_DIR / "04_双向Astar" / "experiments" / "prepare_graphml.py"
    spec = importlib.util.spec_from_file_location("a3_graphml_converter", converter_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load GraphML converter: {converter_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_binary(network_id: str) -> tuple[Path, float | None, bool]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    item = next(entry for entry in manifest["files"] if entry["filename"] == NETWORKS[network_id]["graphml"])
    graphml = REPO_ROOT / "data" / item["filename"]
    if not graphml.is_file() or graphml.stat().st_size != int(item["size_bytes"]):
        raise FileNotFoundError(f"GraphML is missing or its size differs from the manifest: {graphml}")
    GRAPH_CACHE.mkdir(parents=True, exist_ok=True)
    binary = GRAPH_CACHE / f"{network_id}_{item['sha256'][:12]}.bin"
    metadata = binary.with_suffix(".json")
    cache_hit = binary.is_file() and metadata.is_file()
    conversion_ms = None
    if not cache_hit:
        report = _load_converter().convert(graphml, binary)
        conversion_ms = float(report["conversion_seconds"]) * 1000
    return binary, conversion_ms, cache_hit


def _ch_cache_info(network_id: str) -> tuple[Path, str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    graph = next(item for item in manifest["files"] if item["filename"] == NETWORKS[network_id]["graphml"])
    digest = hashlib.sha256(b"a3-ch-index-cache-v1\0")
    digest.update(graph["sha256"].encode("ascii"))
    for source in CH_CACHE_SOURCES:
        digest.update(source.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        digest.update(source.read_bytes())
    key = digest.hexdigest()
    return CH_INDEX_CACHE / f"{network_id}_{key}.bin", key


def _ensure_executable(build_if_missing: bool) -> None:
    source_files = (
        CALLS_DIR / "cpp" / "performance_comparison.cpp",
        A3_DIR / "01_Dijkstra" / "cpp" / "dijkstra_cpp.cpp",
        A3_DIR / "03_Astar" / "cpp" / "astar_cpp.cpp",
        A3_DIR / "05_CH" / "cpp" / "ch_c_api.cpp",
        A3_DIR / "05_CH" / "cpp" / "ch.cpp",
        A3_DIR / "04_双向Astar" / "cpp" / "bidirectional_astar_received.cpp",
        A3_DIR / "04_双向Astar" / "cpp" / "bidirectional_astar_variants.cpp",
        A3_DIR / "04_双向Astar" / "cpp" / "bidirectional_astar_variants.hpp",
        REPO_ROOT / "workspaces" / "A2_算法" / "algorithms.hpp",
        REPO_ROOT / "workspaces" / "A2_算法" / "graph_types.hpp",
    )
    stale = not EXECUTABLE.is_file() or any(
        path.stat().st_mtime_ns > EXECUTABLE.stat().st_mtime_ns
        for path in source_files if path.is_file()
    )
    if not stale:
        return
    if not build_if_missing:
        raise FileNotFoundError(f"Build or rebuild the native runner first: {BUILD_SCRIPT}")
    shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or shutil.which("pwsh")
    if shell is None:
        raise RuntimeError("PowerShell is required to build the C++ comparison runner")
    subprocess.run([shell, "-NoProfile", "-File", str(BUILD_SCRIPT)], check=True)


def run_comparison(
    network: str,
    *,
    query_count: int = 30,
    algorithms=("dijkstra", "astar", "bidirectional_astar"),
    rounds: int = 1,
    seed: int | None = None,
    result_dir=None,
    build_if_missing: bool = False,
) -> dict:
    """Run one selected network batch; a server can call this without a Notebook."""
    if network not in NETWORKS:
        raise ValueError(f"network must be one of {tuple(NETWORKS)}")
    query_count, rounds = int(query_count), int(rounds)
    if not 1 <= query_count <= 100 or rounds < 1:
        raise ValueError("query_count must be 1..100 and rounds must be positive")
    algorithms = tuple(algorithms)
    if not algorithms or len(set(algorithms)) != len(algorithms) or set(algorithms) - ALGORITHMS.keys():
        raise ValueError(f"algorithms must be unique IDs from {tuple(ALGORITHMS)}")
    seed = secrets.randbits(32) if seed is None else int(seed)
    if not 0 <= seed < 2**64:
        raise ValueError("seed must be an unsigned 64-bit integer")

    _ensure_executable(build_if_missing)
    binary, conversion_ms, binary_cache_hit = _ensure_binary(network)
    ch_cache_path, ch_cache_key = _ch_cache_info(network)
    if result_dir is None:
        with tempfile.TemporaryDirectory(prefix="a3-performance-", dir=CALLS_DIR / ".build") as temp_dir:
            _run_native(binary, network, query_count, rounds, seed, algorithms, Path(temp_dir),
                        ch_cache_path, ch_cache_key)
            payload = build_frontend_payload(Path(temp_dir), networks=(network,))
    else:
        result_path = Path(result_dir)
        result_path.mkdir(parents=True, exist_ok=True)
        _run_native(binary, network, query_count, rounds, seed, algorithms, result_path,
                    ch_cache_path, ch_cache_key)
        payload = build_frontend_payload(result_path, networks=(network,))
    payload["networks"][0]["config"]["seed"] = seed
    payload["networks"][0]["config"]["selected_algorithms"] = list(algorithms)
    payload["networks"][0]["preprocessing_ms"]["graphml_to_binary"] = conversion_ms
    payload["networks"][0]["preprocessing_ms"]["graph_binary_cache_hit"] = binary_cache_hit
    if result_dir is not None:
        (Path(result_dir) / f"{network}_payload.json").write_text(
            json.dumps(payload["networks"][0], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return payload["networks"][0]


def run_comparison_suite(
    *,
    networks=tuple(NETWORKS),
    query_count: int = 30,
    algorithms=("dijkstra", "astar", "bidirectional_astar"),
    rounds: int = 1,
    seed: int | None = None,
    result_dir=None,
    build_if_missing: bool = False,
) -> dict:
    """Run the selected algorithms on the chosen graph scales and return one response."""
    network_ids = tuple(networks)
    if not network_ids or len(set(network_ids)) != len(network_ids):
        raise ValueError("networks must be a non-empty sequence of unique network IDs")
    unknown = set(network_ids) - NETWORKS.keys()
    if unknown:
        raise ValueError(f"unknown network IDs: {sorted(unknown)}")
    seed = secrets.randbits(32) if seed is None else int(seed)

    if result_dir is None:
        with tempfile.TemporaryDirectory(prefix="a3-performance-suite-", dir=CALLS_DIR / ".build") as temp_dir:
            results = [
                run_comparison(
                    network_id, query_count=query_count, algorithms=algorithms,
                    rounds=rounds, seed=seed, result_dir=temp_dir,
                    build_if_missing=build_if_missing,
                )
                for network_id in network_ids
            ]
    else:
        output_dir = Path(result_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results = [
            run_comparison(
                network_id, query_count=query_count, algorithms=algorithms,
                rounds=rounds, seed=seed, result_dir=output_dir,
                build_if_missing=build_if_missing,
            )
            for network_id in network_ids
        ]

    return {
        "schema_version": "a3.performance.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timing_semantics": "elapsed_ns around the C++ query call, including path reconstruction and any interface buffer transfer; graph conversion and preprocessing are separate",
        "networks": results,
    }


def _run_native(binary, network, count, rounds, seed,
                algorithms, output_dir, ch_cache_path, ch_cache_key):
    output_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(EXECUTABLE), str(binary), network, str(count), str(rounds), str(seed),
        ",".join(algorithms),
        str(output_dir / f"{network}_raw.csv"),
        str(output_dir / f"{network}_preprocess.csv"),
        str(ch_cache_path), ch_cache_key,
    ]
    subprocess.run(args, cwd=REPO_ROOT, check=True)
    return output_dir
