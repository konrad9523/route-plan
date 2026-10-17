"""下载城市级路网原始数据（OSM XML，来自 Overpass API）。

为什么不直接用 OSMnx：
  1. 环境里没装 osmnx / geopandas / shapely，安装体积大；
  2. 直接拿原始 OSM XML 可以自己控制建图规则，也便于做数据体检；
  3. 后续要接本项目既有的 Graph/Edge 数据契约，自己解析更可控。

用法：
    python download_city_network.py --city wuhan
输出：
    <outdir>/wuhan_drive.osm     原始 XML（可复用，避免重复下载）
    <outdir>/download_meta.json  下载元信息（时间、查询、字节数、SHA256）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Overpass 查询：按城市名取行政边界，再取边界内所有可作为机动车的道路。
# 用 area 而不是 bbox，避免把周边农村/山区一起框进来导致规模失控。
QUERY_TEMPLATE = """[out:xml][timeout:{timeout}];
area["name:zh"="{city_zh}"]["boundary"="administrative"]["admin_level"="5"]->.a;
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|living_street|service)$"](area.a);
);
(._;>;);
out body;
"""

# 多个镜像，逐个回退
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

CITIES = {
    "wuhan": {"city_zh": "武汉市", "expect": "约 10 万~30 万节点"},
    "dijiao": {"city_zh": "中国地质大学(武汉)", "expect": "校园级，仅作对照"},
}


def fetch(query: str, timeout: int = 600) -> bytes:
    """依次尝试各镜像，返回原始字节。"""

    data = urllib.parse.urlencode({"data": query}).encode()
    last_err: Exception | None = None
    for url in MIRRORS:
        try:
            print(f"  尝试镜像 {url} ...", flush=True)
            req = urllib.request.Request(
                url,
                data=data,
                headers={"User-Agent": "route-plan-course/1.0 (educational)"},
            )
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            dt = time.time() - t0
            print(f"    成功：{len(body):,} 字节，用时 {dt:.1f}s")
            return body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"    失败：{type(exc).__name__}: {exc}")
            last_err = exc
    raise RuntimeError(f"所有镜像均失败，最后一个错误：{last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="wuhan", choices=sorted(CITIES))
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    info = CITIES[args.city]
    # 默认输出在被 Git 忽略的本机 cache；也支持显式数据目录。
    if args.outdir:
        outdir = Path(args.outdir)
    else:
        import _paths  # 同目录
        # data_dir() 要求目录已存在；下载时目录可能还没有，所以直接用候选路径
        outdir = _paths.WORKSPACE_DATA
    outdir.mkdir(parents=True, exist_ok=True)
    osm_path = outdir / f"{args.city}_drive.osm"
    meta_path = outdir / "download_meta.json"

    query = QUERY_TEMPLATE.format(city_zh=info["city_zh"], timeout=args.timeout)
    print(f"城市：{args.city}（{info['city_zh']}），预期规模：{info['expect']}")
    print(f"输出：{osm_path}")

    if osm_path.exists() and osm_path.stat().st_size > 0:
        print(f"  已存在（{osm_path.stat().st_size:,} 字节），跳过下载。"
              f"如需重新下载请先删除该文件。")
        body = osm_path.read_bytes()
        dt = 0.0
    else:
        t0 = time.time()
        body = fetch(query, timeout=args.timeout)
        dt = time.time() - t0
        osm_path.write_bytes(body)

    sha = hashlib.sha256(body).hexdigest().upper()
    meta = {
        "city": args.city,
        "city_zh": info["city_zh"],
        "source": "Overpass API",
        "query": query,
        "bytes": len(body),
        "sha256": sha,
        "download_seconds": round(dt, 1),
        "file": str(osm_path),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成。SHA-256 = {sha}")
    print(f"元信息写入 {meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
