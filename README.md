# china-coord-transform

> WGS-84 ⇄ GCJ-02 ⇄ BD-09 + 五/七参数 + 矢量文件批量转换。
> 一个 ClawHub / OpenClaw 兼容的 skill，纯 Python（核心），可选 `pyshp`。

## ⚠️ 重要免责声明

**方法 1（通用 GCJ-02 公式）是反编译的混淆算法，不是国家测绘局公布的任何"标准"，不保证精度，不保证长期有效。**

- **存在系统性偏移**：在中国大陆绝大多数地区单点偏差 5–15m，边缘地区可达 30m+。
- **不应**用于：地籍测量、房产测绘、地形图修测、应急救援坐标、案件证据坐标、政府申报材料坐标、学术论文里的"真实"位置描述。
- **可以**用于：可视化、面向 C 端的"大致位置"展示、POI 标签、产品演示、UI 位置指示、自媒体内容等**非测绘场景**。
- **必须**得到接近真实 WGS-84 的坐标（< 1m）时，请用方法 2 / 方法 3，并使用**你自己**的高精度控制点（RTK、全站仪、CORS）。国家禁止公开"标准"GCJ-02 转换工具用于将 GCJ-02 转回 WGS-84——本 skill 的方法 1 **也是反编译的近似**，不是官方实现，使用者请自行评估合规风险。

**总结：方法 1 是工具，不是真相。** 涉及准确位置的，请用你自己的控制点重做（方法 2 / 方法 3）。

---

## 四种方法

### 方法 1：通用 GCJ-02 偏移公式（默认）

适合"我只要大概位置"——把高德/腾讯 GCJ-02 转 WGS-84、把 WGS-84 加偏移给高德底图。中国大陆全境可用，**不保证精度**。

椭球体：Krasovsky 1940（`a = 6378245.0`，`f = 1/298.3`）。对经纬度 `(lng, lat)`，相对参考中心 `(105°E, 35°N)` 计算两个三角函数偏移 `dlat` 和 `dlng`，再用克拉索夫斯基椭球的子午圈/卯酉圈半径把弧度偏移转成度。

GCJ-02 → WGS-84 用固定点迭代法，参考 qgis-geohey-toolbox 实现，迭代至 1e-6 度（≈10cm 级别）退出。

支持：`wgs84 ↔ gcj02`，`gcj02 ↔ bd09`，`wgs84 ↔ bd09`（级联）。

### 方法 2：基于控制点的局部仿射/多项式

当方法 1 误差不能满足需求时，使用本方法：

1. 用户提供 3+ 对已知控制点（src GCJ-02 lon/lat 和 dst WGS-84 lon/lat）
2. 求解一个 2D 仿射变换 `wgs = A · src + b`（6 个参数）
3. 对区域内任意点应用该仿射

`fit_polynomial` 是 6 系数二次多项式（含 x²、y²、xy 项），需要 ≥ 6 个控制点；处理大区域非线性畸变。

**关键：控制点必须是你自己采集的（RTK、全站仪、像控点），不能是网上"在线转换"出来的 GCJ-02 → WGS-84 数据——那些数据本身就是方法 1 算出来的，会把方法 1 的误差传染进来。**

### 方法 3：五参数 / 七参数 Helmert（测绘级）

经典大地测量方法。

**2D 四参数（`Helmert2D4`）**：2 个平移 + 1 个旋转 + 1 个尺度，适用于投影平面坐标（UTM、Gauss-Krüger 等）的相似变换。

**2D 五参数（`Helmert2D5`）**：2 个平移 + 1 个旋转 + 2 个尺度（各向异性），中国测绘界常说的"五参数"——本 skill 已实现模型和 JSON 序列化，但 `cli fit` 目前只支持四参数，五参数请直接在 Python 中调用 `helmert.Helmert2D5(tx, ty, rotation_rad, scale_x, scale_y)`。

**3D 七参数（`Helmert3D7`，Bursa-Wolf）**：3 个平移 + 3 个旋转 + 1 个尺度，用于 WGS-84 ↔ CGCS2000、北京 54、西安 80 等椭球体之间转换。流程：lat/lon → ECEF → 应用 7 参数 → 反算 lat/lon。

`fit_helmert_2d_4param` 用线性最小二乘（`a = s·cosθ, b = s·sinθ` 消元），闭式解；要求 ≥ 2 个控制点（≥ 3 推荐）。

### 方法 4：矢量文件批量转换

把整个 shapefile 一次性转——比如一个城市的道路网、POI 集、行政区划面。

- **GeoJSON**：标准库支持，直接可用
- **Shapefile**：需要 `pip install pyshp`（纯 Python，可选）

支持的几何类型：Point / MultiPoint / LineString / MultiLineString / Polygon / MultiPolygon。

**注意：SHP 写入时不会自动复制 .prj / .cpg 等 sidecar 文件**，需要的话自己 copy 一下。

## 快速上手

### Python 库

```python
# 方法 1：通用公式（注意：精度有限）
from transform import wgs2gcj, gcj2wgs, gcj2bd, bd2gcj, wgs2bd, bd2wgs, convert

# 天安门：高德（GCJ-02）→ WGS-84
wgs_lon, wgs_lat = gcj2wgs(116.397594, 39.904949)
# → (116.391353, 39.903548) — 与谷歌地球参考 (116.391222, 39.903468) 偏差 ~14m

# 通用 dispatcher
convert(116.391222, 39.903468, "wgs84", "bd09")
```

```python
# 方法 2：控制点仿射
from affine import fit_affine
controls = [
    (121.4701, 31.2300, 121.463857, 31.228597),  # 你的 (gcj_lon, gcj_lat, wgs_lon, wgs_lat)
    (121.4801, 31.2300, 121.473857, 31.228597),
    # ... 至少 3 对，建议 6+ 对均匀分布
]
params = fit_affine(controls)
new_lon, new_lat = params.apply(gcj_lon, gcj_lat)
```

```python
# 方法 3：五参数 / 七参数
from helmert import (
    Helmert2D4, Helmert2D5, Helmert3D7,
    fit_helmert_2d_4param, fit_helmert_3d_7param,
    geodetic_to_ecef, ecef_to_geodetic,
)

# 2D 四参数（直接给参数）
params4 = Helmert2D4(tx=1234.5, ty=-678.9, rotation_rad=0.001, scale=-5e-6)
X, Y = params4.apply(src_x, src_y)

# 2D 四参数（从控制点拟合）
params4_fit = fit_helmert_2d_4param(controls)

# 2D 五参数（直接给参数）
params5 = Helmert2D5(tx=1.2, ty=3.4, rotation_rad=0.0001, scale_x=1e-6, scale_y=2e-6)

# 3D 七参数
params7 = Helmert3D7(dx=1.5, dy=-2.0, dz=0.8,
                      rx_arcsec=0.5, ry_arcsec=-0.3, rz_arcsec=0.1,
                      scale_ppm=-0.5)
lon2, lat2, h2 = params7.apply_geodetic(lon, lat, h)

# 3D 七参数：从 geodetic 控制点拟合（>= 3 个）
params7_fit = fit_helmert_3d_7param(geodetic_controls)
stats = helmert_3d_residual_stats(params7_fit, geodetic_controls)
# 在 5 个城市 + 不同高度的控制点上，无噪声时 max residual < 1mm

# 3D 七参数求逆
params7_inv = params7.invert()  # 闭式解析，round-trip 误差 < 1mm
```

```python
# 方法 4：矢量文件
from vector import convert_geojson_file, convert_shp_file
from transform import gcj2wgs

# GeoJSON（标准库）
convert_geojson_file("in.geojson", "out.geojson", gcj2wgs)

# Shapefile（需要 pip install pyshp）
convert_shp_file("in.shp", "out.shp", gcj2wgs)
```

### CLI

```bash
# 单点
python cli.py convert --from gcj02 --to wgs84 --lon 116.397594 --lat 39.904949
# → 116.3913529,39.9035477

# 批量 CSV
python cli.py batch --from bd09 --to wgs84 --input examples/points.csv --output out.csv

# 拟合方法 2 / 3 的参数
python cli.py fit --controls examples/controls.csv --model affine --output affine.json
python cli.py fit --controls examples/controls.csv --model helmert-4param --output helmert.json
python cli.py batch --from gcj02 --to wgs84 --input in.csv --output out.csv --params affine.json

# 矢量文件
python cli.py vector --input in.geojson --output out.geojson --from gcj02 --to wgs84
python cli.py vector --input in.shp --output out.shp --from bd09 --to wgs84
python cli.py vector --input in.geojson --output out.geojson --params affine.json
```

## 数学原理

### 方法 1

```
参考中心: (lon0, lat0) = (105, 35)
dlat = transform_lat(lon - lon0, lat - lat0)
dlng = transform_lng(lon - lon0, lat - lat0)
radlat = lat · π / 180
magic = sin(radlat); magic = 1 - ee · magic²
sqrt_magic = √magic
dlat = (dlat · 180) / ((a·(1-ee))/(magic·sqrt_magic) · π)
dlng = (dlng · 180) / (a/sqrt_magic · cos(radlat) · π)

gcj_lon = lon + dlng
gcj_lat = lat + dlat
```

GCJ-02 → WGS-84 迭代：`w_{k+1} = w_k - (wgs2gcj(w_k) - g_0)`，直到 |Δ| < 1e-6°。

### 方法 2

每对控制点 → 2D 仿射方程组 → 6x6 最小二乘（纯 Python Gauss-Jordan）。

### 方法 3

2D 四参数（设 a = s·cosθ, b = s·sinθ）：
```
X = tx + a·x - b·y
Y = ty + b·x + a·y
```
关于 (tx, ty, a, b) **线性**，所以是普通最小二乘。

3D 七参数（Bursa-Wolf）：
```
[X']   [dx]   [ 1   -rz  ry ] [X]
[Y'] = [dy] + [ rz  1   -rx ] [Y]   (rz/rx/ry in radians)
[Z']   [dz]   [-ry  rx  1   ] [Z]
```
流程：geodetic (lon, lat, h) → ECEF (X, Y, Z) → 应用 7 参数 → 反算 geodetic。

## 已知限制

- **方法 1**：不保证精度，绝对不能用于测绘；边缘地区 30m+ 误差；不是官方实现。
- **方法 2 / 3**：依赖控制点本身的质量；区域 > 100 km² 不推荐仿射；七参数对椭球体定义敏感。
- 只做地理坐标（lat/lon），不支持高程或投影坐标（除非你先把投影坐标转成经纬度再用方法 2/3）。
- 输出是十进制度。

## 验证

skill 自带一个天安门对照测试（**仅一个样本，不构成精度声明**）：

```text
GCJ-02 : 116.397594, 39.904949   (高德地图坐标拾取)
WGS-84 : 116.391353, 39.903548   (方法 1 转换结果)
Ref    : 116.391222, 39.903468   (谷歌地球实际值)
distance (Google→converted): 14.29 m
```

拟合精度（**方法 2 / 3**，用 6 对控制点 + 完美仿射的合成数据）：max residual < 1e-7°（约 0.01mm）。

## 引用

```text
Coordinate conversion based on qgis-geohey-toolbox (GeoHey, GPL v2)
and the public GCJ-02 obfuscation algorithm. Not for surveying use.
```

## 许可

MIT-0（与 ClawHub 默认协议一致）。

## 致谢

- GCJ-02 算法来自中国国家测绘局 2002 年公开规范（反编译实现）
- BD-09 算法来自百度地图开发者文档
- 原始 Python 实现来自 [qgis-geohey-toolbox](https://github.com/GeoHey-Team/qgis-geohey-toolbox) (sshuair)
- Bursa-Wolf 七参数参考 IERS Conventions
