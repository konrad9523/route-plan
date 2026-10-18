"""Runtime facade for the A3 Python/C++ Dijkstra and A* implementations.

The notebook remains an experiment harness. Applications can construct one
RoutePlanner at startup, then call ``plan`` for each pair of dense graph node IDs.
Pickle input must be a trusted project-generated graph file.
"""

from __future__ import annotations

import ctypes as ct
import hashlib
import importlib.util
import json
import math
import pickle
import re
import threading
from collections.abc import Mapping
from operator import index
from pathlib import Path
from time import perf_counter_ns
from xml.etree import ElementTree as ET

import numpy as np


CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parents[3]
A2_DIR = REPO_ROOT / "workspaces" / "A2_算法" / "01_实现清单"


def _load_module(name: str, path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"算法文件不存在：{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载算法文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIJKSTRA_BASELINE = _load_module("a3_dijkstra_baseline", A2_DIR / "dijkstra.py")
ASTAR_BASELINE = _load_module("a3_astar_baseline", A2_DIR / "astar.py")
DIJKSTRA = _load_module("a3_dijkstra_variants", CODE_DIR / "dijkstra_variants.py")
ASTAR = _load_module("a3_astar_variants", CODE_DIR / "astar_variants.py")
ROUTE_OUTPUT = _load_module("a3_route_output", CODE_DIR / "route_output.py")


_DIJKSTRA_CPP_IDS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "B1": 5}
_ASTAR_CPP_IDS = {
    "L0": 0,
    "L0-CachedScale": 1,
    "L1": 2,
    "L2": 3,
    "L3": 4,
    "L4": 5,
    "L5": 6,
    "B1": 7,
}
_ASTAR_HEURISTIC_CPP_IDS = {
    "H0": 0,
    "PLANE": 1,
    "ALT": 2,
    "MAX": 3,
    "MAX_PLANE": 4,
}
_DIJKSTRA_CPP_STATUS = {
    0: "OK",
    1: "INVALID_ARGUMENT",
    2: "INVALID_GRAPH",
    3: "INVALID_QUERY",
    4: "BUFFER_TOO_SMALL",
    5: "INTERNAL_ERROR",
}
_ASTAR_CPP_STATUS = {
    0: "OK",
    1: "INVALID_ARGUMENT",
    2: "INVALID_GRAPH",
    3: "INVALID_QUERY",
    4: "BUFFER_TOO_SMALL",
    5: "PREPARATION_REQUIRED",
    6: "INTERNAL_ERROR",
}
_I64_P = ct.POINTER(ct.c_int64)
_DOUBLE_P = ct.POINTER(ct.c_double)
_U64_P = ct.POINTER(ct.c_uint64)
_MAXSPEED_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(km/h|kmh|kph|mph)?\s*$", re.I)


def _parse_osm_maxspeed_kmh(value):
    if isinstance(value, bool) or value is None:
        return None
    match = _MAXSPEED_RE.fullmatch(str(value))
    if match is None:
        return None
    speed = float(match.group(1))
    if match.group(2) and match.group(2).lower() == "mph":
        speed *= 1.609344
    return speed if math.isfinite(speed) and speed > 0 else None


def _load_osm_maxspeed_overrides(graphml_path: Path, edge_records) -> dict[int, float]:
    """Match GraphML edge order to edge IDs, validating each directed endpoint pair."""
    key_names = {}
    overrides = {}
    matched = 0
    for event, element in ET.iterparse(graphml_path, events=("start", "end")):
        kind = element.tag.rsplit("}", 1)[-1]
        if event == "start" and kind == "key":
            key_names[element.attrib["id"]] = element.attrib.get("attr.name", "")
        elif event == "end" and kind == "edge":
            pair = (int(element.attrib["source"]), int(element.attrib["target"]))
            if matched >= len(edge_records):
                raise ValueError("GraphML 边数多于 graph_v2.pkl")
            record = edge_records[matched]
            expected = ((int(record["from_node"]), int(record["to_node"]))
                        if isinstance(record, Mapping)
                        else (int(record[0]), int(record[1])))
            if pair != expected:
                raise ValueError(
                    f"GraphML 第 {matched} 条有向边与 edge_id={matched} 端点不一致"
                )
            edge_id = matched
            matched += 1
            source_tags = next((data.text for data in element
                                if data.tag.rsplit("}", 1)[-1] == "data"
                                and key_names.get(data.attrib.get("key")) == "source_tags"), None)
            if source_tags:
                try:
                    tags = json.loads(source_tags)
                except json.JSONDecodeError:
                    tags = None
                if isinstance(tags, dict):
                    speed = _parse_osm_maxspeed_kmh(tags.get("maxspeed"))
                    if speed is not None:
                        overrides[edge_id] = speed
            element.clear()

    if matched != len(edge_records):
        raise ValueError("GraphML 边数少于 graph_v2.pkl")
    return overrides


def _default_cpp_path(algorithm: str) -> Path:
    build_dir = CODE_DIR / ".build"
    if algorithm == "dijkstra":
        return build_dir / "dijkstra_cpp.dll"
    source = CODE_DIR / "astar_cpp.cpp"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    flags = ("/std:c++17", "/O2", "/EHsc", "/LD", "/DNDEBUG")
    build_key = hashlib.sha256(
        (source_hash + "|".join(flags)).encode("utf-8")
    ).hexdigest()[:12]
    return build_dir / "astar_cpp" / f"astar_cpp_{build_key}.dll"


def _node_id(value, name: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 必须是图中的整数节点 ID")
    try:
        result = index(value)
    except TypeError as exc:
        raise ValueError(f"{name} 必须是图中的整数节点 ID") from exc
    return result


class RoutePlanner:
    """Load/preprocess one graph once and expose a uniform per-query interface.

    ``graph_data`` is the dictionary stored in graph_v2.pkl. A backend may use
    ``RoutePlanner.from_pickle(path)`` at startup and reuse the instance for all
    requests. ``plan`` returns a JSON-serializable route dictionary.

    ``version`` selects the experiment layer (L0-L5/B1); ``language`` selects
    the Python or C++ implementation. A* accepts H0, PLANE, ALT, MAX, or
    MAX_PLANE; ALT-based requests prepare landmarks once and reuse the tables.
    """

    def __init__(self, graph_data: Mapping, *, cpp_libraries: Mapping | None = None,
                 max_landmarks: int = 16):
        if not isinstance(graph_data, Mapping):
            raise TypeError("graph_data 必须是 graph_v2.pkl 中的映射对象")

        self.n_nodes = int(graph_data["n_nodes"])
        self.indptr = np.ascontiguousarray(graph_data["indptr"], dtype=np.int64)
        self.indices = np.ascontiguousarray(graph_data["indices"], dtype=np.int64)
        self.weights = np.ascontiguousarray(graph_data["weights"], dtype=np.float64)
        self.edge_ids = np.ascontiguousarray(graph_data["edge_ids"], dtype=np.int64)
        self.lons = np.ascontiguousarray(graph_data["lon"], dtype=np.float64)
        self.lats = np.ascontiguousarray(graph_data["lat"], dtype=np.float64)
        self.edge_records = graph_data["edges"]
        self.n_edges = len(self.edge_records)
        speed_overrides = graph_data.get("edge_speed_overrides", {})
        if not isinstance(speed_overrides, Mapping):
            raise TypeError("edge_speed_overrides 必须是 edge_id 到速度的映射")
        self.edge_speed_overrides = {}
        for edge_id, speed in speed_overrides.items():
            edge_id = _node_id(edge_id, "edge_id")
            speed = float(speed)
            if edge_id >= self.n_edges or not math.isfinite(speed) or speed <= 0:
                raise ValueError("OSM maxspeed 覆盖项的 edge_id 或速度不合法")
            self.edge_speed_overrides[edge_id] = speed
        self._validate_graph_data()

        self.csr = (self.indptr, self.indices, self.weights, self.edge_ids)
        self.csr_dict = {
            "n_nodes": self.n_nodes,
            "indptr": self.indptr,
            "indices": self.indices,
            "weights": self.weights,
            "edge_ids": self.edge_ids,
        }
        self.graph = {node: [] for node in range(self.n_nodes)}
        for node in range(self.n_nodes):
            self.graph[node] = [
                (int(self.indices[i]), float(self.weights[i]), int(self.edge_ids[i]))
                for i in range(int(self.indptr[node]), int(self.indptr[node + 1]))
            ]
        self.positions = {
            node: (float(self.lons[node]), float(self.lats[node]))
            for node in range(self.n_nodes)
        }

        self.max_landmarks = min(_node_id(max_landmarks, "max_landmarks"), self.n_nodes)
        if self.max_landmarks < 0:
            raise ValueError("max_landmarks 不能为负数")

        self._reverse_graph = None
        self._astar_ready = False
        self._h0_scale = None
        self._projected = None
        self._plane_scale = None
        self._landmark_ids = None
        self._python_alt = None
        self._prep_lock = threading.RLock()
        self._cpp_init_lock = threading.Lock()
        self._cpp_runtimes = {}
        self._closed = False

        supplied = cpp_libraries or {}
        self._cpp_paths = {
            name: Path(supplied[name]) if supplied.get(name) is not None
            else _default_cpp_path(name)
            for name in ("dijkstra", "astar")
        }

    @classmethod
    def from_pickle(cls, path, *, source_graphml=None, **kwargs) -> "RoutePlanner":
        """Load a trusted graph pickle and matching OSM maxspeed tags, if present.

        The Wuhan GraphML file is auto-detected beside graph_v2.pkl; other paths
        can be supplied explicitly with source_graphml.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"路网文件不存在：{path}")
        with path.open("rb") as stream:
            graph_data = dict(pickle.load(stream))
        if source_graphml is None:
            candidate = path.with_name("wuhan_distance_v2.graphml")
            source_graphml = candidate if candidate.is_file() else None
        if source_graphml is not None:
            source_graphml = Path(source_graphml)
            if not source_graphml.is_file():
                raise FileNotFoundError(f"OSM 道路属性文件不存在：{source_graphml}")
            existing_overrides = graph_data.get("edge_speed_overrides", {})
            if not isinstance(existing_overrides, Mapping):
                raise TypeError("edge_speed_overrides 必须是 edge_id 到速度的映射")
            graph_data["edge_speed_overrides"] = {
                **existing_overrides,
                **_load_osm_maxspeed_overrides(source_graphml, graph_data["edges"]),
            }
        return cls(graph_data, **kwargs)

    def _validate_graph_data(self) -> None:
        n, m = self.n_nodes, self.n_edges
        if n <= 0 or m < 0:
            raise ValueError("路网节点数必须大于零，边数不能为负数")
        if self.indptr.shape != (n + 1,) or self.indices.shape != (m,):
            raise ValueError("CSR indptr/indices 长度与节点数、边数不匹配")
        if self.weights.shape != (m,) or self.edge_ids.shape != (m,):
            raise ValueError("CSR weights/edge_ids 长度与边数不匹配")
        if self.lons.shape != (n,) or self.lats.shape != (n,):
            raise ValueError("经纬度数组长度与节点数不匹配")
        if int(self.indptr[0]) != 0 or int(self.indptr[-1]) != m:
            raise ValueError("CSR indptr 起止位置不合法")
        if np.any(self.indptr[1:] < self.indptr[:-1]):
            raise ValueError("CSR indptr 必须单调不减")
        if m and (np.min(self.indices) < 0 or np.max(self.indices) >= n):
            raise ValueError("CSR 邻接节点编号越界")
        if not np.all(np.isfinite(self.weights)) or np.any(self.weights < 0):
            raise ValueError("边权必须为有限非负数")
        if not np.all(np.isfinite(self.lons)) or not np.all(np.isfinite(self.lats)):
            raise ValueError("节点经纬度必须为有限数值")
        if m and not np.array_equal(np.sort(self.edge_ids), np.arange(m)):
            raise ValueError("edge_id 必须与边表索引一一对应")

        for u in range(n):
            for i in range(int(self.indptr[u]), int(self.indptr[u + 1])):
                v, eid = int(self.indices[i]), int(self.edge_ids[i])
                record = self.edge_records[eid]
                if isinstance(record, Mapping):
                    edge_u = int(record["from_node"])
                    edge_v = int(record["to_node"])
                    edge_length = float(record["length_m"])
                else:
                    edge_u, edge_v, edge_length = int(record[0]), int(record[1]), float(record[2])
                if edge_u != u or edge_v != v or not math.isclose(
                    edge_length, float(self.weights[i]), rel_tol=1e-10, abs_tol=1e-5
                ):
                    raise ValueError(f"edge_id={eid} 与 CSR 方向或边权不匹配")

    def _get_reverse_graph(self):
        if self._reverse_graph is None:
            with self._prep_lock:
                if self._reverse_graph is None:
                    self._reverse_graph = ASTAR.build_reverse_graph(self.graph)
        return self._reverse_graph

    def _prepare_astar(self) -> None:
        if self._astar_ready:
            return
        with self._prep_lock:
            if self._astar_ready:
                return
            ASTAR.prevalidate_graph(self.graph, self.positions)
            self._h0_scale = ASTAR.estimate_heuristic_scale(self.graph, self.positions)
            self._projected = ASTAR.project_coordinates(self.positions)
            self._plane_scale = ASTAR.estimate_plane_scale(self.graph, self._projected)
            self._astar_ready = True

    def _select_landmarks(self):
        if self.max_landmarks < 1:
            raise ValueError("ALT/MAX 启发式需要 max_landmarks 大于零")
        if self._landmark_ids is None:
            self._prepare_astar()
            self._landmark_ids = tuple(ASTAR.select_landmarks(
                self.positions, range(self.n_nodes), self.max_landmarks
            ))
        return self._landmark_ids

    def _ensure_python_alt(self, landmark_count: int):
        if not 1 <= landmark_count <= self.max_landmarks:
            raise ValueError(f"landmark_count 必须在 1 到 {self.max_landmarks} 之间")
        with self._prep_lock:
            if self._python_alt is None:
                self._python_alt = ASTAR.prepare_landmarks(
                    self.graph, self._select_landmarks()
                )
            return self._python_alt

    @staticmethod
    def _normalize_astar_version(version: str) -> str:
        if not isinstance(version, str):
            raise ValueError("A* version 必须是字符串")
        normalized = version.strip().upper().replace("_", "-")
        if normalized in {"L0-CACHEDSCALE", "L0-CACHED-SCALE", "L0C"}:
            return "L0-CachedScale"
        allowed = {"L0", "L1", "L2", "L3", "L4", "L5", "B1"}
        if normalized not in allowed:
            raise ValueError(f"不支持的 A* 版本：{version!r}")
        return normalized

    def _cpp_runtime(self, algorithm: str):
        if self._closed:
            raise RuntimeError("RoutePlanner 已关闭")
        runtime = self._cpp_runtimes.get(algorithm)
        if runtime is not None:
            return runtime
        with self._cpp_init_lock:
            runtime = self._cpp_runtimes.get(algorithm)
            if runtime is not None:
                return runtime
            path = self._cpp_paths[algorithm]
            if not path.is_file():
                raise FileNotFoundError(
                    f"找不到 {algorithm} C++ 动态库：{path}；"
                    "请先编译对应 cpp 文件或传入 cpp_libraries 路径"
                )
            if ct.sizeof(ct.c_void_p) != 8:
                raise RuntimeError("当前 Python 必须为 64 位以匹配 C++ 动态库")
            try:
                lib = ct.CDLL(str(path))
            except OSError as exc:
                raise RuntimeError(f"无法加载 C++ 动态库：{path}") from exc
            runtime = (self._create_cpp_dijkstra(lib) if algorithm == "dijkstra"
                       else self._create_cpp_astar(lib))
            runtime["library_path"] = path
            runtime["call_lock"] = threading.Lock()
            self._cpp_runtimes[algorithm] = runtime
            return runtime

    def _create_cpp_dijkstra(self, lib):
        lib.dijkstra_graph_create.argtypes = [
            ct.c_int64, ct.c_int64, _I64_P, _I64_P, _DOUBLE_P, _I64_P,
            ct.POINTER(ct.c_int32),
        ]
        lib.dijkstra_graph_create.restype = ct.c_void_p
        lib.dijkstra_graph_destroy.argtypes = [ct.c_void_p]
        lib.dijkstra_graph_destroy.restype = None
        lib.dijkstra_run.argtypes = [
            ct.c_void_p, ct.c_int32, ct.c_int64, ct.c_int64,
            _I64_P, ct.c_int64, _I64_P, ct.c_int64,
            ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64), _DOUBLE_P,
            _U64_P, _U64_P,
        ]
        lib.dijkstra_run.restype = ct.c_int32
        error = ct.c_int32()
        handle = lib.dijkstra_graph_create(
            self.n_nodes, self.n_edges, self.indptr.ctypes.data_as(_I64_P),
            self.indices.ctypes.data_as(_I64_P), self.weights.ctypes.data_as(_DOUBLE_P),
            self.edge_ids.ctypes.data_as(_I64_P), ct.byref(error),
        )
        if not handle or error.value != 0:
            raise RuntimeError(
                f"C++ Dijkstra 图初始化失败："
                f"{_DIJKSTRA_CPP_STATUS.get(error.value, error.value)}"
            )
        return {
            "lib": lib,
            "handle": handle,
            "node_buffer": np.empty(self.n_nodes, dtype=np.int64),
            "edge_buffer": np.empty(self.n_nodes, dtype=np.int64),
        }

    def _create_cpp_astar(self, lib):
        lib.astar_graph_create.argtypes = [
            ct.c_int64, ct.c_int64, _I64_P, _I64_P, _DOUBLE_P, _I64_P,
            _DOUBLE_P, _DOUBLE_P, ct.POINTER(ct.c_int32),
        ]
        lib.astar_graph_create.restype = ct.c_void_p
        lib.astar_graph_destroy.argtypes = [ct.c_void_p]
        lib.astar_graph_destroy.restype = None
        lib.astar_prepare_geometry.argtypes = [ct.c_void_p, _DOUBLE_P, _DOUBLE_P, _U64_P]
        lib.astar_prepare_geometry.restype = ct.c_int32
        lib.astar_prepare_reverse.argtypes = [ct.c_void_p, _U64_P]
        lib.astar_prepare_reverse.restype = ct.c_int32
        lib.astar_prepare_alt.argtypes = [ct.c_void_p, ct.c_int32, _I64_P, _U64_P]
        lib.astar_prepare_alt.restype = ct.c_int32
        lib.astar_run.argtypes = [
            ct.c_void_p, ct.c_int32, ct.c_int32, ct.c_int32,
            ct.c_int64, ct.c_int64, _I64_P, ct.c_int64, _I64_P, ct.c_int64,
            ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64), _DOUBLE_P,
            _U64_P, _U64_P, _U64_P, _U64_P, _U64_P,
        ]
        lib.astar_run.restype = ct.c_int32
        error = ct.c_int32()
        handle = lib.astar_graph_create(
            self.n_nodes, self.n_edges, self.indptr.ctypes.data_as(_I64_P),
            self.indices.ctypes.data_as(_I64_P), self.weights.ctypes.data_as(_DOUBLE_P),
            self.edge_ids.ctypes.data_as(_I64_P), self.lons.ctypes.data_as(_DOUBLE_P),
            self.lats.ctypes.data_as(_DOUBLE_P), ct.byref(error),
        )
        if not handle or error.value != 0:
            raise RuntimeError(
                f"C++ A* 图初始化失败："
                f"{_ASTAR_CPP_STATUS.get(error.value, error.value)}"
            )
        elapsed = ct.c_uint64()
        haversine_scale, plane_scale = ct.c_double(), ct.c_double()
        for operation, args in (
            (lib.astar_prepare_geometry, (handle, ct.byref(haversine_scale), ct.byref(plane_scale), ct.byref(elapsed))),
            (lib.astar_prepare_reverse, (handle, ct.byref(elapsed))),
        ):
            status = operation(*args)
            if status != 0:
                lib.astar_graph_destroy(handle)
                raise RuntimeError(
                    f"C++ A* 预处理失败：{_ASTAR_CPP_STATUS.get(status, status)}"
                )
        return {
            "lib": lib,
            "handle": handle,
            "node_buffer": np.empty(self.n_nodes, dtype=np.int64),
            "edge_buffer": np.empty(self.n_nodes, dtype=np.int64),
            "alt_ready": False,
        }

    def _ensure_cpp_alt(self, runtime) -> None:
        if runtime["alt_ready"]:
            return
        if self.max_landmarks < 1:
            raise ValueError("ALT/MAX 启发式需要 max_landmarks 大于零")
        landmark_ids = np.ascontiguousarray(self._select_landmarks(), dtype=np.int64)
        elapsed = ct.c_uint64()
        status = runtime["lib"].astar_prepare_alt(
            runtime["handle"], len(landmark_ids),
            landmark_ids.ctypes.data_as(_I64_P), ct.byref(elapsed),
        )
        if status != 0:
            raise RuntimeError(
                f"C++ A* ALT 预处理失败：{_ASTAR_CPP_STATUS.get(status, status)}"
            )
        runtime["alt_ready"] = True

    def _run_cpp(self, algorithm: str, version: str, heuristic: str,
                 landmark_count: int, source: int, target: int):
        runtime = self._cpp_runtime(algorithm)
        with runtime["call_lock"]:
            if algorithm == "astar" and heuristic in {"ALT", "MAX", "MAX_PLANE"}:
                self._ensure_cpp_alt(runtime)
            lib = runtime["lib"]
            nodes = runtime["node_buffer"]
            edges = runtime["edge_buffer"]
            node_count, edge_count = ct.c_int64(), ct.c_int64()
            distance = ct.c_double()
            if algorithm == "dijkstra":
                algorithm_id = _DIJKSTRA_CPP_IDS.get(version)
                if algorithm_id is None:
                    raise ValueError(f"C++ Dijkstra 不支持版本：{version}")
                settled, elapsed = ct.c_uint64(), ct.c_uint64()
                status = lib.dijkstra_run(
                    runtime["handle"], algorithm_id, source, target,
                    nodes.ctypes.data_as(_I64_P), nodes.size,
                    edges.ctypes.data_as(_I64_P), edges.size,
                    ct.byref(node_count), ct.byref(edge_count), ct.byref(distance),
                    ct.byref(settled), ct.byref(elapsed),
                )
                metrics = {"expanded_nodes": int(settled.value), "kernel_ns": int(elapsed.value)}
            else:
                version_id = _ASTAR_CPP_IDS.get(version)
                heuristic_id = _ASTAR_HEURISTIC_CPP_IDS.get(heuristic)
                if version_id is None:
                    raise ValueError(f"C++ A* 不支持版本：{version}")
                if heuristic_id is None:
                    raise ValueError(f"C++ A* 不支持启发式：{heuristic}")
                expanded, pushed, scanned, h_evals, elapsed = [ct.c_uint64() for _ in range(5)]
                status = lib.astar_run(
                    runtime["handle"], version_id, heuristic_id, landmark_count,
                    source, target, nodes.ctypes.data_as(_I64_P), nodes.size,
                    edges.ctypes.data_as(_I64_P), edges.size,
                    ct.byref(node_count), ct.byref(edge_count), ct.byref(distance),
                    ct.byref(expanded), ct.byref(pushed), ct.byref(scanned),
                    ct.byref(h_evals), ct.byref(elapsed),
                )
                metrics = {
                    "expanded_nodes": int(expanded.value),
                    "queue_pushes": int(pushed.value),
                    "scanned_edges": int(scanned.value),
                    "heuristic_evaluations": int(h_evals.value),
                    "kernel_ns": int(elapsed.value),
                }
            if status != 0:
                status_names = (
                    _DIJKSTRA_CPP_STATUS if algorithm == "dijkstra"
                    else _ASTAR_CPP_STATUS
                )
                raise RuntimeError(
                    f"C++ {algorithm} 查询失败：{status_names.get(status, status)}；"
                    f"{source}->{target}"
                )
            if not (0 <= node_count.value <= nodes.size and 0 <= edge_count.value <= edges.size):
                raise RuntimeError("C++ 返回的路径长度超过输出缓冲区")
            result = (
                nodes[:node_count.value].tolist(),
                edges[:edge_count.value].tolist(),
                float(distance.value),
                metrics["expanded_nodes"],
            )
            return result, metrics

    def _run_python(self, algorithm: str, version: str, heuristic: str,
                    landmark_count: int, source: int, target: int):
        if algorithm == "dijkstra":
            if version == "L0":
                result = DIJKSTRA_BASELINE.dijkstra(self.graph, source, target)
            elif version in {"L1", "L2", "L3"}:
                result = getattr(DIJKSTRA, f"dijkstra_{version.lower()}")(
                    self.graph, source, target
                )
            elif version == "L4":
                result = DIJKSTRA.dijkstra_l4(self.csr_dict, source, target)
            elif version == "B1":
                result = DIJKSTRA.dijkstra_b1(
                    self.graph, self._get_reverse_graph(), source, target
                )
            else:
                raise ValueError(f"Python Dijkstra 不支持版本：{version}")
            return result, {}

        self._prepare_astar()
        if version == "L0" and heuristic == "H0":
            result = ASTAR_BASELINE.astar(self.graph, self.positions, source, target)
            return result, {}
        alt = None
        if heuristic in {"ALT", "MAX", "MAX_PLANE"}:
            alt = self._ensure_python_alt(landmark_count)
        stats = {}
        if version == "B1":
            result = ASTAR.bidirectional_astar(
                self.graph, self._get_reverse_graph(), self.positions, source, target,
                heuristic=heuristic, heuristic_scale=self._h0_scale,
                projected=self._projected, plane_scale=self._plane_scale,
                alt=alt, landmark_count=landmark_count, stats=stats,
            )
        else:
            result = ASTAR.run_astar(
                version, self.graph, self.positions, source, target,
                heuristic=heuristic, heuristic_scale=self._h0_scale,
                projected=self._projected, plane_scale=self._plane_scale,
                csr=self.csr, alt=alt, landmark_count=landmark_count,
                stats=stats,
            )
        return result, {
            "queue_pushes": stats.get("pushed_count"),
            "scanned_edges": stats.get("scanned_edges"),
            "heuristic_evaluations": stats.get("heuristic_evaluations"),
        }

    def plan(self, source, target, *, algorithm: str = "dijkstra",
             version: str = "L4", language: str = "python",
             heuristic: str = "H0", landmark_count: int = 16) -> dict:
        """Plan one shortest-distance route and return JSON-ready route data.

        Node IDs must belong to the graph used to construct this planner. For a
        browser map, serve those same IDs from its node-list endpoint.
        """
        if self._closed:
            raise RuntimeError("RoutePlanner 已关闭")
        source, target = _node_id(source, "source"), _node_id(target, "target")
        if not (0 <= source < self.n_nodes and 0 <= target < self.n_nodes):
            raise ValueError(f"起终点节点编号越界：{source}->{target}")
        if not isinstance(algorithm, str) or algorithm.lower() not in {"dijkstra", "astar"}:
            raise ValueError("algorithm 必须是 'dijkstra' 或 'astar'")
        algorithm = algorithm.lower()
        if not isinstance(language, str) or language.lower() not in {"python", "cpp"}:
            raise ValueError("language 必须是 'python' 或 'cpp'")
        language = language.lower()
        if algorithm == "dijkstra":
            version = version.strip().upper() if isinstance(version, str) else version
            if version not in {"L0", "L1", "L2", "L3", "L4", "B1"}:
                raise ValueError(f"不支持的 Dijkstra 版本：{version!r}")
            heuristic = "H0"
            landmark_count = 0
        else:
            version = self._normalize_astar_version(version)
            if not isinstance(heuristic, str):
                raise ValueError("heuristic 必须是字符串")
            heuristic = heuristic.upper()
            if heuristic not in _ASTAR_HEURISTIC_CPP_IDS:
                raise ValueError(f"不支持的 A* 启发式：{heuristic!r}")
            landmark_count = _node_id(landmark_count, "landmark_count")
            if version in {"L0", "L0-CachedScale"} and heuristic != "H0":
                raise ValueError("A* 基线版本只支持 H0")
            if heuristic in {"ALT", "MAX", "MAX_PLANE"} and not (
                1 <= landmark_count <= self.max_landmarks
            ):
                raise ValueError(f"landmark_count 必须在 1 到 {self.max_landmarks} 之间")

        if language == "cpp":
            runtime = self._cpp_runtime(algorithm)
            if algorithm == "astar" and heuristic in {"ALT", "MAX", "MAX_PLANE"}:
                self._select_landmarks()
                with runtime["call_lock"]:
                    self._ensure_cpp_alt(runtime)
        else:
            if algorithm == "dijkstra" and version == "B1":
                self._get_reverse_graph()
            elif algorithm == "astar":
                if version != "L0":
                    self._prepare_astar()
                if heuristic in {"ALT", "MAX", "MAX_PLANE"}:
                    self._ensure_python_alt(landmark_count)
                if version == "B1":
                    self._get_reverse_graph()

        started = perf_counter_ns()
        if language == "cpp":
            result, metrics = self._run_cpp(
                algorithm, version, heuristic, landmark_count, source, target
            )
        else:
            result, metrics = self._run_python(
                algorithm, version, heuristic, landmark_count, source, target
            )
        planning_ms = (perf_counter_ns() - started) / 1e6
        output = ROUTE_OUTPUT.build_route_output(
            result, self.edge_records, source, target, algorithm=algorithm,
            planning_ms=planning_ms, edge_speed_overrides=self.edge_speed_overrides,
        )
        output["version"] = version
        output["language"] = language
        output["heuristic"] = heuristic if algorithm == "astar" else None
        output["geometry"] = [list(self.positions[node]) for node in output["node_ids"]]
        output["geometry_source"] = "node_coordinates"
        output["stats"] = {
            "expanded_states": output["expanded_nodes"],
            "queue_pushes": metrics.get("queue_pushes"),
            "planning_ms": planning_ms,
        }
        for key in ("scanned_edges", "heuristic_evaluations", "kernel_ns"):
            if key in metrics:
                output["stats"]["kernel_ms" if key == "kernel_ns" else key] = (
                    metrics[key] / 1e6 if key == "kernel_ns" else metrics[key]
                )
        return output

    def close(self) -> None:
        """Release persistent native graph handles; safe to call more than once."""
        if self._closed:
            return
        with self._cpp_init_lock:
            for algorithm, runtime in self._cpp_runtimes.items():
                with runtime["call_lock"]:
                    destroy = runtime["lib"].dijkstra_graph_destroy if algorithm == "dijkstra" \
                        else runtime["lib"].astar_graph_destroy
                    destroy(runtime["handle"])
            self._cpp_runtimes.clear()
            self._closed = True

    def __enter__(self) -> "RoutePlanner":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
