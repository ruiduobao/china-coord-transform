---
name: china-coord-transform
description: 在中国常用的三种坐标系之间转换 —— WGS-84（GPS / 谷歌地球）、GCJ-02（火星坐标系，高德/腾讯）、BD-09（百度坐标系）。提供 4 种方法：通用 GCJ-02 偏移公式（中国大陆全境，约 ±10m 误差）、基于控制点反算的局部仿射/多项式（亚米级精度）、五参数/七参数 Helmert（测绘级）、以及矢量文件（GeoJSON / Shapefile）批量转换。**重要：方法 1 输出存在系统性偏移，仅可用于非测绘用途，正式测绘请用方法 2/3。**
version: 1.1.1
metadata:
  openclaw:
    emoji: "🗺️"
    requires:
      bins:
        - python
    primaryEnv: ""
    envVars: []
    homepage: https://github.com/ruiduobao/china-coord-transform
---

# China Coord Transform

> WGS-84 ⇄ GCJ-02 ⇄ BD-09 + 五/七参数 + 矢量文件批量转换。
> 一个 ClawHub / OpenClaw 兼容的 skill，纯 Python（核心），可选 `pyshp`。

## ⚠️ 免责声明 / 重要提示

**本 skill 的方法 1（通用 GCJ-02 公式）是**反编译**的混淆算法，不是国家测绘局公布的任何"标准"，不保证精度，不保证长期有效。**

- **方法 1 输出存在系统性偏移**：在中国大陆绝大多数地区单点偏差 5–15m，边缘地区可达 30m 以上；坐标转换过程中**会**累积误差，**不要**用作正式测绘、放线、确权、罚款、执法、新闻报道、警情定位等任何需要法律或事实效力的场景。
- **方法 1 不应**用于：地籍测量、房产测绘、地形图修测、应急救援坐标、案件证据坐标、政府申报材料坐标、学术论文里的"真实"位置描述。
- **可以**用于：可视化、用户端的"大致位置"展示、POI 标签、产品演示、UI 上的位置指示、自媒体内容、面向 C 端的"我附近有什么"功能等**非测绘场景**。
- 如果你**必须**得到接近真实 WGS-84 的坐标（< 1m），请用方法 2（控制点仿射）或方法 3（五/七参数），并使用你**自己的**高精度控制点（RTK、全站仪、CORS）。国家禁止公开"标准"GCJ-02 转换工具用于将 GCJ-02 转回 WGS-84——本 skill 的方法 1 **也是反编译的近似**，不是官方实现，使用者请自行评估合规风险。

**总结：方法 1 是工具，不是真相。** 涉及准确位置的，请用你自己的控制点重做（方法 2 / 方法 3）。

## 四种方法

### 方法 1：通用 GCJ-02 偏移公式（默认）

适合"我只要大概位置"——把高德/腾讯 GCJ-02 转 WGS-84、把 WGS-84 加偏移给高德底图。中国大陆全境可用，单点误差 5–15m，**不保证精度**。

支持：`wgs84 ↔ gcj02`，`gcj02 ↔ bd09`，`wgs84 ↔ bd09`。

### 方法 2：控制点反算仿射/多项式（亚米级）

用户提供 3+ 对已知控制点 → 最小二乘反算 2D 仿射（或 6 系数多项式）→ 区域内任意点应用。需要**你自己的**控制点（不能是网上的"在线转换"数据），精度看控制点本身。**这就是你在博客里说的"选取一系列均匀分布的控制点反算出转换的参数"**。

### 方法 3：五参数 / 七参数 Helmert（测绘级）

经典大地测量方法。`fit --model helmert-4param` 支持 2D 平面四参数（2 平移 + 1 旋转 + 1 缩放）；`helmert.Helmert3D7` 是 3D Bursa-Wolf 七参数（用于 WGS-84 ↔ CGCS2000 之类的椭球体转换，先做 lat/lon → ECEF → 应用 7 参数 → 反算 lat/lon）。已有参数可以直接通过 JSON 文件喂进来。

### 方法 4：矢量文件批量转换（GeoJSON / Shapefile）

把整个 shapefile 一次性转——比如一个城市的道路网、POI 集、行政区划面，**用方法 2 / 3 的拟合参数或直接用方法 1 都能批处理**。`.shp` 需要 `pip install pyshp`（纯 Python，可选）。

## 快速使用（Python）

```python
# 方法 1：通用公式（注意：精度有限，不用于测绘）
from transform import wgs2gcj, gcj2wgs, gcj2bd, bd2gcj, wgs2bd, bd2wgs
wgs_lon, wgs_lat = gcj2wgs(116.397594, 39.904949)
# → (116.391353, 39.903548) — 与谷歌地球偏差 ~14m，不保证精度

# 方法 2：控制点仿射
from affine import fit_affine
controls = [(gcj_lon1, gcj_lat1, wgs_lon1, wgs_lat1), ...]  # 你的控制点
params = fit_affine(controls)

# 方法 3：五参数 / 七参数
from helmert import Helmert2D4, Helmert3D7, fit_helmert_2d_4param
params4 = fit_helmert_2d_4param(controls)         # 2D 四参数
# 或直接给 7 参数：params7 = Helmert3D7(dx=..., dy=..., dz=..., rx_arcsec=..., ...)

# 方法 4：矢量文件
from vector import convert_geojson_file, convert_shp_file
from transform import gcj2wgs
convert_geojson_file("in.geojson", "out.geojson", gcj2wgs)
convert_shp_file("in.shp", "out.shp", gcj2wgs)   # 需要 pyshp
```

## 快速使用（CLI）

```bash
# 单点（方法 1）
python cli.py convert --from gcj02 --to wgs84 --lon 116.397594 --lat 39.904949

# 批量 CSV
python cli.py batch --from bd09 --to wgs84 --input in.csv --output out.csv

# 拟合方法 2 / 3 的参数
python cli.py fit --controls controls.csv --model affine --output params.json
python cli.py fit --controls controls.csv --model helmert-4param --output helmert.json
python cli.py batch --from gcj02 --to wgs84 --input in.csv --output out.csv --params params.json

# 矢量文件（方法 4）
python cli.py vector --input in.geojson --output out.geojson --from gcj02 --to wgs84
python cli.py vector --input in.shp --output out.shp --from bd09 --to wgs84
python cli.py vector --input in.geojson --output out.geojson --params params.json
```

## 文件清单

| 文件 | 用途 |
| --- | --- |
| `SKILL.md` | 本文件 |
| `transform.py` | 方法 1：通用 GCJ-02 公式；6 个互转函数 + dispatcher |
| `affine.py` | 方法 2：控制点反算仿射（纯 Python 6x6 求解器，无 numpy 依赖） |
| `helmert.py` | 方法 3：2D 4/5 参数 + 3D 7 参数 Helmert |
| `vector.py` | 方法 4：GeoJSON / Shapefile 批量转换（GeoJSON 用标准库，SHP 需 pyshp） |
| `cli.py` | CLI：convert / batch / fit / vector |
| `examples/points.csv` | 8 个示例点 |
| `examples/controls.csv` | 6 个控制点（用于 fit） |
| `README.md` | 详细文档与数学原理 |
| `LICENSE` | MIT-0 |

## 验证数据（仍然适用，但不保证代表真实场景）

```text
GCJ-02 : 116.397594, 39.904949   (高德地图坐标拾取)
WGS-84 : 116.391353, 39.903548   (方法 1 转换结果)
Ref    : 116.391222, 39.903468   (谷歌地球实际值)
distance (Google→converted): 14.29 m
```

这只是 1 个点的样本，**不能**用来声称方法 1 整体精度。**请用方法 2/3 在你自己的控制点集上评估精度**。

## 引用

> Coordinate conversion based on qgis-geohey-toolbox (GeoHey, GPL v2)
> and the public GCJ-02 obfuscation algorithm. Not for surveying use.

## 许可

MIT-0（与 ClawHub 默认协议一致）。
