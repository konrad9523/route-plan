"""A3 C++ single-route backends used by the A4 navigation service."""

from __future__ import annotations

import ctypes as ct
import hashlib
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
A3_ROOT = ROOT / "a3-runtime" / "workspaces" / "A3_性能"
A2_ROOT = ROOT / "a3-runtime" / "workspaces" / "A2_算法"
BUILD_DIR = ROOT / ".a3-route-build"
LOCK = threading.RLock()
BACKENDS: dict[str, "A3RouteBackend"] = {}

I64_P = ct.POINTER(ct.c_int64)
U64_P = ct.POINTER(ct.c_uint64)
DOUBLE_P = ct.POINTER(ct.c_double)

SOURCES = {
    "dijkstra": (A3_ROOT / "01_Dijkstra" / "cpp" / "dijkstra_cpp.cpp",),
    "astar": (A3_ROOT / "03_Astar" / "cpp" / "astar_cpp.cpp",),
    "ch": (
        A3_ROOT / "05_CH" / "cpp" / "ch_c_api.cpp",
        A3_ROOT / "05_CH" / "cpp" / "ch.cpp",
        A2_ROOT / "algorithms.hpp",
        A2_ROOT / "graph_types.hpp",
    ),
}
DLLS = {name: BUILD_DIR / f"{name}_cpp.dll" for name in SOURCES}


def _native_path(path: Path) -> str:
    """Pass a UTF-8 path to the CH C ABI."""
    return str(path)


def _compile_dll(name: str) -> Path:
    target = DLLS[name]
    sources = SOURCES[name]
    # The CH C ABI is shipped as a prebuilt runtime asset. Its source tree
    # may be newer than the copied DLL after packaging, but the runtime must
    # still be able to load the verified asset and its prepared cache.
    if name == "ch" and target.is_file():
        return target
    if target.is_file() and all(target.stat().st_mtime_ns >= source.stat().st_mtime_ns for source in sources):
        return target
    raise RuntimeError(f"A3 C++ {name} DLL 不存在或已过期：{target}；请先重新构建桌面包")


def _configure_dijkstra(library) -> None:
    library.dijkstra_graph_create.argtypes = [ct.c_int64, ct.c_int64, I64_P, I64_P, DOUBLE_P, I64_P, ct.POINTER(ct.c_int32)]
    library.dijkstra_graph_create.restype = ct.c_void_p
    library.dijkstra_graph_destroy.argtypes = [ct.c_void_p]
    library.dijkstra_graph_destroy.restype = None
    library.dijkstra_run.argtypes = [
        ct.c_void_p, ct.c_int32, ct.c_int64, ct.c_int64, I64_P, ct.c_int64,
        I64_P, ct.c_int64, ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64),
        DOUBLE_P, U64_P, U64_P, I64_P, ct.c_int64, ct.POINTER(ct.c_int64),
    ]
    library.dijkstra_run.restype = ct.c_int32


def _configure_astar(library) -> None:
    library.astar_graph_create.argtypes = [ct.c_int64, ct.c_int64, I64_P, I64_P, DOUBLE_P, I64_P, DOUBLE_P, DOUBLE_P, ct.POINTER(ct.c_int32)]
    library.astar_graph_create.restype = ct.c_void_p
    library.astar_graph_destroy.argtypes = [ct.c_void_p]
    library.astar_graph_destroy.restype = None
    library.astar_prepare_geometry.argtypes = [ct.c_void_p, DOUBLE_P, DOUBLE_P, U64_P]
    library.astar_prepare_geometry.restype = ct.c_int32
    library.astar_prepare_reverse.argtypes = [ct.c_void_p, U64_P]
    library.astar_prepare_reverse.restype = ct.c_int32
    library.astar_run.argtypes = [
        ct.c_void_p, ct.c_int32, ct.c_int32, ct.c_int32, ct.c_int64, ct.c_int64,
        I64_P, ct.c_int64, I64_P, ct.c_int64, ct.POINTER(ct.c_int64),
        ct.POINTER(ct.c_int64), DOUBLE_P, U64_P, U64_P, U64_P, U64_P, U64_P,
        I64_P, ct.c_int64, ct.POINTER(ct.c_int64),
    ]
    library.astar_run.restype = ct.c_int32


def _configure_ch(library) -> None:
    library.ch_graph_create_cached.argtypes = [
        ct.c_int64, ct.c_int64, I64_P, I64_P, DOUBLE_P, I64_P,
        ct.c_char_p, ct.c_char_p, ct.POINTER(ct.c_int32), U64_P, U64_P,
        ct.POINTER(ct.c_int32), ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64),
    ]
    library.ch_graph_create_cached.restype = ct.c_void_p
    library.ch_last_error.argtypes = []
    library.ch_last_error.restype = ct.c_char_p
    library.ch_graph_destroy.argtypes = [ct.c_void_p]
    library.ch_graph_destroy.restype = None
    library.ch_run.argtypes = [
        ct.c_void_p, ct.c_int64, ct.c_int64, I64_P, ct.c_int64, I64_P,
        ct.c_int64, ct.POINTER(ct.c_int64), ct.POINTER(ct.c_int64), DOUBLE_P,
        U64_P, U64_P, U64_P, I64_P, ct.c_int64, ct.POINTER(ct.c_int64),
    ]
    library.ch_run.restype = ct.c_int32


class A3RouteBackend:
    """One SQLite graph with lazy, persistent A3 C++ algorithm handles."""

    def __init__(self, dataset: str, database: Path):
        self.dataset = dataset
        self.database = database
        self.node_ids: list[str] = []
        self.node_index: dict[str, int] = {}
        self.coordinates: dict[str, tuple[float, float]] = {}
        self.edge_meta: dict[int, dict] = {}
        self.indptr: np.ndarray
        self.indices: np.ndarray
        self.weights: np.ndarray
        self.edge_ids: np.ndarray
        self.lons: np.ndarray
        self.lats: np.ndarray
        self.handles: dict[str, tuple[object, object]] = {}
        self.loaded_ms = 0.0
        self.preprocess_ms: dict[str, float] = {}
        self.query_lock = threading.RLock()
        self._load_graph()

    def _load_graph(self) -> None:
        started = time.perf_counter()
        with sqlite3.connect(self.database) as connection:
            all_node_rows = connection.execute("SELECT node_id, lon, lat FROM nodes ORDER BY rowid").fetchall()
            edge_data = list(connection.execute(
                "SELECT edge_id, source, target, length_m, highway, name FROM edges ORDER BY edge_id"
            ))
        # SQLite also keeps disconnected OSM nodes. They cannot be selected by
        # edge snapping and only make the native indexes larger, so compact the
        # runtime graph to nodes that occur in at least one directed edge.
        active_ids = {str(row[1]) for row in edge_data} | {str(row[2]) for row in edge_data}
        node_rows = [row for row in all_node_rows if str(row[0]) in active_ids]
        self.node_ids = [str(row[0]) for row in node_rows]
        self.node_index = {node_id: index for index, node_id in enumerate(self.node_ids)}
        self.lons = np.ascontiguousarray([float(row[1]) for row in node_rows], dtype=np.float64)
        self.lats = np.ascontiguousarray([float(row[2]) for row in node_rows], dtype=np.float64)
        self.coordinates = {node_id: (float(row[2]), float(row[1])) for node_id, row in zip(self.node_ids, node_rows)}

        node_count, edge_count = len(self.node_ids), len(edge_data)
        counts = np.zeros(node_count, dtype=np.int64)
        source_indices = np.empty(edge_count, dtype=np.int64)
        target_indices = np.empty(edge_count, dtype=np.int64)
        weights = np.empty(edge_count, dtype=np.float64)
        edge_ids = np.empty(edge_count, dtype=np.int64)
        for row_index, (edge_id, source, target, length, highway, name) in enumerate(edge_data):
            source_index = self.node_index[str(source)]
            target_index = self.node_index[str(target)]
            source_indices[row_index] = source_index
            target_indices[row_index] = target_index
            weights[row_index] = float(length or 0.0)
            edge_ids[row_index] = int(edge_id)
            counts[source_index] += 1
            self.edge_meta[int(edge_id)] = {"distance": float(length or 0.0), "highway": highway or "", "name": name or "OSM 道路"}
        self.indptr = np.empty(node_count + 1, dtype=np.int64)
        self.indptr[0] = 0
        np.cumsum(counts, out=self.indptr[1:])
        cursor = self.indptr[:-1].copy()
        self.indices = np.empty(edge_count, dtype=np.int64)
        self.weights = np.empty(edge_count, dtype=np.float64)
        self.edge_ids = np.empty(edge_count, dtype=np.int64)
        for row_index in range(edge_count):
            position = cursor[source_indices[row_index]]
            self.indices[position] = target_indices[row_index]
            self.weights[position] = weights[row_index]
            self.edge_ids[position] = edge_ids[row_index]
            cursor[source_indices[row_index]] += 1
        self.loaded_ms = (time.perf_counter() - started) * 1000

    def _arrays(self):
        return (self.indptr.ctypes.data_as(I64_P), self.indices.ctypes.data_as(I64_P), self.weights.ctypes.data_as(DOUBLE_P), self.edge_ids.ctypes.data_as(I64_P))

    def _init_dijkstra(self):
        if "dijkstra" in self.handles:
            return self.handles["dijkstra"]
        library = ct.CDLL(str(_compile_dll("dijkstra")))
        _configure_dijkstra(library)
        error = ct.c_int32()
        handle = library.dijkstra_graph_create(len(self.node_ids), len(self.edge_meta), *self._arrays(), ct.byref(error))
        if not handle or error.value != 0:
            raise RuntimeError(f"A3 C++ Dijkstra 图初始化失败：状态码 {error.value}")
        self.handles["dijkstra"] = (library, handle)
        return library, handle

    def _init_astar(self):
        if "astar" in self.handles:
            return self.handles["astar"]
        library = ct.CDLL(str(_compile_dll("astar")))
        _configure_astar(library)
        error = ct.c_int32()
        handle = library.astar_graph_create(
            len(self.node_ids), len(self.edge_meta), *self._arrays(),
            self.lons.ctypes.data_as(DOUBLE_P), self.lats.ctypes.data_as(DOUBLE_P), ct.byref(error)
        )
        if not handle or error.value != 0:
            raise RuntimeError(f"A3 C++ A* 图初始化失败：状态码 {error.value}")
        prepared = ct.c_uint64()
        hscale, pscale = ct.c_double(), ct.c_double()
        for function, args in (
            (library.astar_prepare_geometry, (handle, ct.byref(hscale), ct.byref(pscale), ct.byref(prepared))),
            (library.astar_prepare_reverse, (handle, ct.byref(prepared))),
        ):
            if function(*args) != 0:
                raise RuntimeError("A3 C++ A* 预处理失败")
        self.preprocess_ms["astar"] = prepared.value / 1_000_000
        self.handles["astar"] = (library, handle)
        return library, handle

    def _init_ch(self):
        if "ch" in self.handles:
            return self.handles["ch"]
        library = ct.CDLL(str(_compile_dll("ch")))
        _configure_ch(library)
        stat = self.database.stat()
        # The same SQLite dataset is copied into the portable desktop package,
        # so its absolute path and copy timestamp must not affect cache hits.
        # Node/edge counts are also stored in the binary cache and checked by
        # the C++ loader.
        cache_key = hashlib.sha256(
            f"a4-ch-v2:{self.dataset}:{stat.st_size}:{len(self.node_ids)}:{len(self.edge_meta)}".encode()
        ).hexdigest()
        # The CH C API accepts char* and constructs std::filesystem::path from
        # it. Keep this cache filename ASCII so Windows code-page conversion
        # cannot fail when the project itself lives under a Chinese path.
        # The shipped legacy DLL receives a narrow char* path. Keep its
        # runtime cache in an ASCII temp directory so Chinese project paths
        # cannot break cache loading on Windows.
        cache_root = Path(os.environ.get("G4_CH_CACHE_DIR", os.environ.get("TEMP", "."))) / "G4RouteCache"
        cache_path = cache_root / f"g4-{self.dataset}-ch.cache"
        if not cache_path.is_file() and os.environ.get("G4_CH_BUILD") != "1":
            raise RuntimeError("CH 缓存未生成；请先执行离线 CH 预处理（G4_CH_BUILD=1），网页请求不会现场构建大型索引")
        error = ct.c_int32()
        preprocess_ns, cache_load_ns = ct.c_uint64(), ct.c_uint64()
        cache_hit = ct.c_int32()
        hierarchy_arcs, shortcuts = ct.c_int64(), ct.c_int64()
        handle = library.ch_graph_create_cached(
            len(self.node_ids), len(self.edge_meta), *self._arrays(), _native_path(cache_path).encode(), cache_key.encode(),
            ct.byref(error), ct.byref(preprocess_ns), ct.byref(cache_load_ns), ct.byref(cache_hit),
            ct.byref(hierarchy_arcs), ct.byref(shortcuts),
        )
        if not handle or error.value != 0:
            detail = library.ch_last_error().decode("utf-8", errors="replace")
            raise RuntimeError(f"A3 C++ CH 初始化失败：状态码 {error.value} {detail}")
        self.preprocess_ms["ch"] = (preprocess_ns.value + cache_load_ns.value) / 1_000_000
        self.handles["ch"] = (library, handle)
        return library, handle

    def plan(self, start: str, target: str, algorithm: str) -> dict:
        source, goal = self.node_index[str(start)], self.node_index[str(target)]
        nodes = np.empty(len(self.node_ids), dtype=np.int64)
        edges = np.empty(len(self.node_ids), dtype=np.int64)
        trace = np.empty(len(self.node_ids), dtype=np.int64)
        node_count, edge_count = ct.c_int64(), ct.c_int64()
        trace_count = ct.c_int64()
        distance = ct.c_double()
        expanded, pushed, scanned, evaluations, elapsed = [ct.c_uint64() for _ in range(5)]
        started = time.perf_counter()
        with self.query_lock:
            if algorithm == "Dijkstra":
                library, handle = self._init_dijkstra()
                status = library.dijkstra_run(handle, 4, source, goal, nodes.ctypes.data_as(I64_P), nodes.size, edges.ctypes.data_as(I64_P), edges.size, ct.byref(node_count), ct.byref(edge_count), ct.byref(distance), ct.byref(expanded), ct.byref(elapsed), trace.ctypes.data_as(I64_P), trace.size, ct.byref(trace_count))
                version = "A3 C++ Dijkstra L4"
            elif algorithm == "A*":
                library, handle = self._init_astar()
                status = library.astar_run(handle, 5, 0, 0, source, goal, nodes.ctypes.data_as(I64_P), nodes.size, edges.ctypes.data_as(I64_P), edges.size, ct.byref(node_count), ct.byref(edge_count), ct.byref(distance), ct.byref(expanded), ct.byref(pushed), ct.byref(scanned), ct.byref(evaluations), ct.byref(elapsed), trace.ctypes.data_as(I64_P), trace.size, ct.byref(trace_count))
                version = "A3 C++ A* L4 H0"
            elif algorithm == "双向 A*":
                library, handle = self._init_astar()
                status = library.astar_run(handle, 7, 0, 0, source, goal, nodes.ctypes.data_as(I64_P), nodes.size, edges.ctypes.data_as(I64_P), edges.size, ct.byref(node_count), ct.byref(edge_count), ct.byref(distance), ct.byref(expanded), ct.byref(pushed), ct.byref(scanned), ct.byref(evaluations), ct.byref(elapsed), trace.ctypes.data_as(I64_P), trace.size, ct.byref(trace_count))
                version = "A3 C++ 双向 A* B1 H0"
            elif algorithm == "CH":
                library, handle = self._init_ch()
                status = library.ch_run(handle, source, goal, nodes.ctypes.data_as(I64_P), nodes.size, edges.ctypes.data_as(I64_P), edges.size, ct.byref(node_count), ct.byref(edge_count), ct.byref(distance), ct.byref(expanded), ct.byref(pushed), ct.byref(elapsed), trace.ctypes.data_as(I64_P), trace.size, ct.byref(trace_count))
                version = "A3 C++ CH"
            else:
                raise ValueError(f"不支持的 A3 算法：{algorithm}")
        if status != 0:
            raise RuntimeError(f"A3 C++ {algorithm} 查询失败：状态码 {status}")
        path = [self.node_ids[index] for index in nodes[:node_count.value].tolist()]
        edge_path = [self.edge_meta[int(edge_id)] for edge_id in edges[:edge_count.value].tolist()]
        trace_nodes = [self.node_ids[index] for index in trace[:trace_count.value].tolist()]
        snapshots = []
        expanded_ids: set[str] = set()
        frontier_ids: dict[str, None] = {}
        for offset in range(0, len(trace_nodes), 25):
            group = trace_nodes[offset:offset + 25]
            expanded_ids.update(group)
            for node_id in expanded_ids:
                frontier_ids.pop(node_id, None)
            # The native ABI returns the exact expansion order, while keeping
            # the live priority queue would make the trace ABI much larger.
            # Reconstruct the visible search boundary from outgoing graph
            # neighbors so the original expanded/current/frontier animation
            # remains meaningful without changing the route result.
            for node_id in group:
                node_index = self.node_index.get(node_id)
                if node_index is None:
                    continue
                begin, end = self.indptr[node_index], self.indptr[node_index + 1]
                for neighbor_index in self.indices[begin:end].tolist():
                    neighbor_id = self.node_ids[int(neighbor_index)]
                    if neighbor_id not in expanded_ids:
                        frontier_ids.setdefault(neighbor_id, None)
            visible_frontier = list(frontier_ids)[:160]
            snapshots.append({
                "current": group[-1],
                "expandedDelta": group,
                "frontier": visible_frontier,
                "frontierCount": len(frontier_ids),
            })
        return {
            "path": path, "edges": edge_path, "snapshots": snapshots,
            "expanded": int(expanded.value), "algorithm_version": version,
            "backend": "a3-cpp", "kernel_ms": elapsed.value / 1_000_000,
            "server_search_ms": (time.perf_counter() - started) * 1000,
            "preprocess_ms": self.preprocess_ms.get("ch", self.preprocess_ms.get("astar", 0.0)),
        }

    def close(self) -> None:
        for algorithm, (library, handle) in self.handles.items():
            destroy = "ch_graph_destroy" if algorithm == "ch" else f"{algorithm}_graph_destroy"
            getattr(library, destroy)(handle)
        self.handles.clear()


def get_backend(dataset: str, database: Path) -> A3RouteBackend:
    with LOCK:
        if dataset not in BACKENDS:
            BACKENDS[dataset] = A3RouteBackend(dataset, database)
        return BACKENDS[dataset]


def close_backends() -> None:
    with LOCK:
        for backend in BACKENDS.values():
            backend.close()
        BACKENDS.clear()
