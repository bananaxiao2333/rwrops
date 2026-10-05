# RWROPS 无损提取算法研究报告

> 对象：`RWR/rwrops`（RWROPS — RWR Omni Parser System）
> 数据源：vanilla 包 720 MB / 3,951 个受扫描文件 / 1,585 个 XML 配置
> 全部数字为本次实测，非估算。复现脚本见文末。

---

## 0. 结论摘要

**一句话**：RWROPS 现在的问题不是"慢"，是**静默丢数据**。全量管线只跑 6.9 秒，但实测有 **15.1% 的属性**和 **60.8% 的子元素**从未进入 `result.json`，且**没有任何一处记录了"我丢了什么、为什么丢"**。

**该做什么**：先修 **§5.1 的 6 个 bug（净增约 15 行）**，其中第 1 条（给 `os.walk` 排序）单独就能把 `result.json` 从"每次可能都不一样"变成"可以 diff"——**没有它，后面任何修改都无法验证**。剩下的 74 个未提取属性是**补 `config/core.yaml`** 的体力活，不是算法问题。

**不建议做什么**：§3 的「无损捕获 → 模式归纳 → 声明式投影 → 守恒校验」四层架构是完整方案，但对 5.6 MB XML / 6.9 秒跑完的代码库属于过度设计，**默认不做**；只有 §5.4 的三条判据之一成立时才值得建。留存理由：它解释了"为什么现在的丢失是结构性的"，以及如果真的要做，边界在哪。

另外发现一个**此前没有被识别出来的结构性问题**：`<resources>` / `<vehicles>` / `<weapons>` 这类文件里的 `<vehicle file="x.vehicle"/>` 不是实体定义，而是**引用/补丁**。当前代码把其中 552 条 vehicle 引用、848 条 weapon 引用通过继承"升级"成了真实体，然后按 key 合并——**这些引用真正的语义（每张地图/每个阵营实际启用哪些载具）被彻底抹掉了**。详见 §2.3。

---

## 1. 现状测绘

### 1.1 规模

| 项目 | 实测值 |
|---|---|
| 包体积 | 720 MB |
| 遍历文件数 | 3,951 |
| XML 配置文件（首字节 `<`） | 1,585 |
| XML 总字节 | 5.6 MB |
| XML 元素总数 | 63,981 |
| 解析失败 | 0 |
| 全量管线耗时 | **6.93 s** |
| `dist/result.json` | 3.66 MB |
| `dist/index.html` | 2.49 MB |
| 导出资源 | 1,053 个 |

**关键判断**：5.6 MB XML 跑 6.9 秒，性能根本不是瓶颈。耗时主要在 `index_html.py` 生成 2.5 MB HTML 和拷贝 1,053 个资源文件，与 XML 解析无关。所以本报告把"高效"重新定义为：**不是让 6.9 秒变 3 秒，而是让新增的无损捕获层不构成负担，并让规则迭代从"重扫 720 MB"变成"重放快照（毫秒级）"**。

### 1.2 实体空间 vs 配置覆盖

实际出现的根元素（文件数）：

| 根元素 | 文件数 | 当前是否处理 |
|---|---|---|
| `<weapon>` | 418 | ✅ 实体定义 |
| `<projectile>` | 332 | ✅ |
| `<vehicle>` | 238 | ✅ |
| `<carry_item>` | 116 | ✅ |
| `<character>` | **84** | ❌ 完全未建模 |
| `<carry_items>` | 61 | ✅ 容器（`selector+"s"` 规则） |
| `<resources>` | **60** | ❌ **丢了 1,035 条实体引用** |
| `<visual_item>` | **57** | ❌ 完全未建模 |
| `<call>` | 25 | ✅ |
| `<vehicles>` | 23 | ✅ 容器 |
| `<ai>` | **23** | ❌ |
| `<models>` | 21 | ❌ |
| `<map_config>` | 19 | ✅ |
| `<ui>` | **15** | ❌ |
| `<commands>` | **13** | ❌ |
| `<faction>` | 12 | ✅ |
| `<weapons>` | 11 | ✅ 容器 |
| `<translation>` / `<language>` | 9 / 9 | ✅ |
| `<journal>` 8、`<intro>` 7、`<font_configs>` 3、`<map_legend>` 2、`<squad_config>` 2、`<visual_items>` 2、`<hud>`/`<reward_config>`/`<package>`/`<scene>`/`<calls>`/`<squad_configs>`/`<factions>` 各 1 | 28 | ❌ |

约 **303 个文件（占 XML 总数 19%）所在的整个域，从未被任何规则触碰**，且没有任何地方报告过这件事。

### 1.3 属性/子元素覆盖率（自动发现，无硬编码）

| 实体 | 根属性 覆盖 | 子元素：完整捕获 | 仅扁平化且缺属性 | **完全未引用** |
|---|---|---|---|---|
| `vehicle` | **7 / 27** | 3 | 2 | 5 |
| `weapon` | **2 / 15** | 9 | 3 | 5 |
| `projectile` | 17 / 22 | 4 | 3 | 3 |
| `call` | 10 / 11 | 3 | 0 | 1 |
| `map_config` | 3 / 4 | 8 | 0 | 0 |
| `carry_item` | 8 / 8 | 4 | 0 | 0 |
| `faction` | 11 / 11 | 2 | 0 | 1 |
| `language` / `translation` | 4/4, 0/0 | 0 | 0 | 0 |
| **合计** | **74 个属性未提取（15.1%）** | 33 | 8 | **15（60.8% 未引用）** |

`vehicle` 漏掉 20 个根属性其中包括 `allow_ai_to_use`、`ai_navigation_offset`、`owner`、`existence`、`jams_enemy_radio` 这类明显有语义的字段；`weapon` 漏掉 13 个，包括 `ai_burst_time`、`drop_count_factor_on_death`、`radius`。

子元素层面 `weapon` 的 `<specification>` 只提取了约 8 个属性，实测该元素下有 **37 个属性**未提取——这是全项目最大的单点损失。

---

## 2. 丢数据的三层根因

### 2.1 结构性丢失（整块数据消失，无任何日志）

**(a) 根元素门控过严** — `util/ops.py:35-47`

```python
doc_root = content.find()
if doc_root is not None and doc_root.name == entity_config_obj.selector:
    root_elements = [doc_root]
elif doc_root is not None:
    if container_root == selector + "s":          # ops.py:42
        root_elements = doc_root.find_all(selector, recursive=False)
    else:
        root_elements = []                         # ← 静默清零
```

只认"文档根就是实体"和"文档根正好是实体名复数"两种情况。除此之外一律返回空列表。`<character>`、`<visual_item>` 根本没有配置；`<ai>`、`<ui>`、`<commands>`、`<journal>`、`<intro>` 同理。**19% 的文件在这里被丢弃，且不产生任何日志。**

**(b) 引用被误当定义** — `util/ops.py:42-43`

`<vehicles>`、`<weapons>`、`<carry_items>` 容器里的子元素是**引用**：

```xml
<!-- maps/lobby/all_vehicles.xml -->
<vehicles>
  <vehicle file="jeep.vehicle"/>
  <vehicle file="apc.vehicle"/>
  ...
</vehicles>
```

`<vehicle file="jeep.vehicle"/>` 只有 `file` 属性，没有 `key`。当前流程是：

1. `find_all("vehicle", recursive=False)` 把它当实体定义收下（`ops.py:43`）
2. `@file` → `inherit_from`（`core.yaml`）
3. `resolve_inheritance_chain` 去磁盘找 `jeep.vehicle`，把**真实载具定义整个合并进来**（`ops.py:287-321`）
4. 合并后有了 `key`，通过 `must_have_attr` 校验（`ops.py:83-91`）
5. `clean_final` 按 key 与真正的定义合并（`main.py:36-46`）

结果：**引用被"洗"成了定义**。23 个 `<vehicles>` 容器文件贡献了 **552 条 vehicle 引用**，另有 **848 条 weapon 引用**（11 个 `<weapons>`）、**784 条 carry_item 引用**（61 个 `<carry_items>`）、**439 条 projectile 引用**、**22 条 achievement 引用**。

这些引用的真实语义是「**某张地图 / 某个阵营实际启用了哪些实体**」——这正是 `maps/map14/all_vehicles.xml` 存在的唯一理由（文件里还有注释：`if you add something here, remember to add it in common.resources or specific faction resources too!`）。现在这个维度**完全消失**：`result.json` 里分不清"世界上有 jeep"和"map14 上有 jeep"。

**(c) `<resources>` 整体不可见** — 60 个文件，1,035 条引用

```xml
<!-- factions/common.resources -->
<resources clear_calls="1" clear_vehicles="1" clear_weapons="1">
  <weapon key="medikit.weapon"/>
  <carry_item enabled="0" key="vest1.carry_item"/>
  ...
</resources>
```

`resources` 是「**补丁 / 覆盖**」语义：`clear_weapons="1"` 表示清空，`enabled="0"` 表示禁用。它和 `<vehicles>` 的引用语义还不同（一个用 `key=`，一个用 `file=`，后者还要经过继承解析才知道指向谁）。整套机制在当前模型里**没有对应概念**。

### 2.2 解析期丢失（数据在内存里被丢掉）

**(d) 子元素匹配是递归的** — `util/ops.py:258`、`util/ops.py:276`

```python
child_elements = element.find_all(child_config.selector)   # 默认 recursive=True
```

`find_all` 搜的是**所有后代**，不是直接子节点。`<turret>` 只要出现在 `visual` 里也会被算作顶层 turret。反向地，`is_array: false` 时取 `child_elements[0]`（`ops.py:276`）——"文档序第一个"，**不保证是直接子节点**，也不保证是正确的那一个。

**(e) `/` 路径提取会丢多样性，且匹配范围错误** — `util/ops.py:445-490`

```python
found_elements = elem.find_all(part)      # ops.py:483 —— 又是递归搜索
...
return values[0] if values else None      # ops.py:476 —— 只取第一个
```

`extract_nested_value(element, "physics/@offset")` 里的 `find_all("physics")` 会匹配任意深度的 `physics`（包括嵌套在别的子树里的），然后**只返回第一个**。路径命中多个元素时，其余全部静默丢弃。

**(f) 「唯一性」约束丢弃整个实体** — `util/ops.py:109-135`

```python
if value in unique_values[key]:
    logger.warning(f"Duplicate value '{value}' found for {entity}.{target}, discarding entity")
    return None          # ← 整个实体被丢，不只是重复的那个属性
```

`unique: true` 命中重复时，**整个实体的所有其他非重复字段一起消失**，只留一行 warning。而且 `unique_values` 以 `(entity_name, target)` 为键，在所有根元素之间共享——跨文件的偶然重复会误伤。

**(g) 整文件解析异常被吞** — `main.py:134-135`

```python
except Exception:
    logger.warning(f"Error when parsing: {item}")
```

单个文件解析失败 = 该文件所有数据消失，只留一行 warning，无计数对账。本次实测 0 失败，但这是**没有防御**，不是**没有风险**。

**(h) `derive_fields` 静默跳过** — `util/ops.py:94-101`

```python
try:
    resolved = df.pattern.format(**entity_data)
except KeyError:
    pass          # 模板变量缺失 → 静默跳过
```

派生字段生成失败不留痕。另外一个隐患：`if entity_data is not None:`（`ops.py:68`）这个判断在 `apply_uniqueness_constraints` 之后，但上面的 `derive_fields` 分支里 `entity_data` 永不为 None，恒真——是死条件，不影响正确性但说明这层控制流已经没人梳理过了。

### 2.3 继承链丢失（最难发现的一类）

**(i) 基类文件靠文件名在 720 MB 里线性搜，取"第一个命中"** — `util/ops.py:324-346`

```python
for file_path in package_path.rglob(filename):
    if file_path.is_file():
        return str(file_path)          # ← 第一个命中，顺序由 os.walk 决定
```

实测：47 个 `inherit_from` 值里有 **4 个是歧义的**：

| 基类文件名 | 磁盘上的副本数 |
|---|---|
| `vehicle_base.vehicle` | **3** |
| `tank_2.vehicle` | 2 |
| `tank.vehicle` | 2 |
| `tank_1.vehicle` | 2 |

**当前行为是抛硬币**：选哪个取决于 `os.walk` 的目录序，也就是取决于文件系统。合并进来的父类可能是错的，而且**完全静默**。更要命的是 `package_path` 与 `plugin_paths` 同时存在时，mod 覆盖原版是本项目存在的意义，而现在的优先级是"谁先被 walk 到"——这是 mod 覆盖语义被破坏。

（补充：实测 `rglob` 单次查询只要 0.1 ms，因为 `vehicles/` 目录在遍历序里靠前。所以这里的**性能不是问题，正确性才是**。本报告不拿这点做性能文章。）

**(j) 缓存键用文件名而非路径** — `util/ops.py:351`

```python
cache_key = f"{base_file}:{entity_selector}"
```

两个不同目录下的同名 `tank.vehicle` 会**命中同一个缓存条目**，第二个拿到的是第一个的数据。这与 (i) 叠加，错误会被放大。

**(k) 环检测靠"截断"而不是"报错"** — `util/ops.py:301-304`

```python
if base_file in visited_files:
    logger.warning(f"Circular inheritance detected: ...")
    return entity_data          # ← 返回不完整的数据，继续往下走
```

菱形继承（A→B→D，A→C→D）里 D 会被误判为环并截断。正确做法是记录"已完成的节点"而不是"路径上见过的节点"。

**(l) 基类找不到时照常输出半成品** — `util/ops.py:318-321`

只 warning，不标记、不剔除。下游无法区分"这个实体天生没有这个字段"和"父类没找到所以这个字段丢了"。

### 2.4 收尾期丢失

**(m) `clean_final` 的 key 冲突合并是"先到先得"** — `main.py:36-44`

```python
for k2, v2 in item.items():
    if isinstance(v2, list) and isinstance(existing.get(k2), list):
        ...  # 列表去重追加
    elif k2 not in existing:
        existing[k2] = v2      # ← 标量：先到的赢，后到的整个丢弃
```

两个实体 key 相同时，**后者的所有标量字段被无声丢弃**，且"谁是后者"由 `os.walk` 顺序决定。再加上 (b) 里引用被洗成定义，`vehicles/all_vehicles.xml` 和 `vehicles/jeep.vehicle` 的合并结果**不可复现**。

**(n) 资源导出以"字符串引用集"为闸门** — `main.py:264-266`

```python
if rel_posix not in refs and res_path.name not in refs and asset_name not in refs:
    skipped += 1
    continue
```

只导出**在已提取数据里出现过**的资源。提取本身就丢数据，所以引用了但没被提取到的资源永远导不出来——**丢失会沿流水线传播**。另外 `rel_path_map` 的 basename → 路径映射也是先到先得（`main.py:270-274`），同名资源会指向错误的路径。

**(o) 编码嗅探不可靠** — `util/file_utils.py:13-20`

```python
r = file.read(size)              # size=5，只读 5 字节
f_charinfo = chardet.detect(r)   # 用 5 字节猜整个文件的编码
encoding = f_charinfo['encoding']   # 可能是 None → 落到 locale 编码
...
open(path, 'r', encoding=encoding, errors="replace")   # 猜错 → 字符被替换成 ?
```

用 5 字节做编码检测在统计上不可靠。`errors="replace"` 会把猜错的字符变成 `?`，而**没有任何地方计数过替换发生了多少次**。非 ASCII 的 `name`、`description` 字段有静默损坏风险。

**(p) 目录被遍历两遍，文件被打开两遍**

`file_utils.py:36-38` 先完整 walk 一遍只为算进度条总数，`41` 再 walk 一遍。`main.py:96-101` 用 `file_reader(path, size=5)` 嗅探（打开 + 读 5 字节），随后 `main.py:130` 再 `file_reader(Path(item))` 打开同一个文件读全文。3,951 个文件各多开一次。

**(q) 非确定性** — `os.walk` 不排序、`rglob` 取首个、`clean_final` 保留首个。三处叠加意味着**同样的输入不一定产生同样的 `result.json`**，于是 diff 失去意义——而 diff 恰恰是发现"这次重构有没有丢数据"的唯一手段。这是最隐蔽也最致命的一条。

### 2.5 AS 解析器的丢失点（`util/as_parser.py`）

| 位置 | 问题 |
|---|---|
| `as_parser.py:45` | 命令块最多收集 80 行（`min(i + 80, len(lines))`），超长 `if` 块的动作被截断 |
| `as_parser.py:25` | 只匹配 `checkCommand(message, "x")` 这一种写法，变体全部漏掉 |
| `as_parser.py:36-41` | 权限判定回溯最多 30 行，超出就默认 `admin` |
| 全文 | 纯正则 + 手写花括号配平，注释和字符串里的 `{}`、`"` 会污染解析 |

`item_delivery_configurator_invasion.as` 实测解析出 33 个类别 / 857 条目，但没有**任何机制**告诉你真实数量是多少——又是一个无法对账的黑箱。

---

## 3. 完整方案：LCP 四层模型（**默认不做**，见 §5.4）

> ⚠️ 这一节是"如果真要把丢失变成可证明的保证，完整形态长什么样"。**它不是推荐路径**。
> 立即可做的在 §5.1。保留这一节是因为它解释了 §2 那些丢失为什么是结构性的，
> 以及真要动手时边界在哪。

**L**ossless **C**apture & **P**rojection。核心是把当前的单一 pass 拆成四层，层与层之间用**可验证的中间产物**连接。

```
                      ┌──────────────────────────────────────┐
   XML 文件 ────────▶ │ L1  CAPTURE  无损捕获                 │
   (1,585 个)         │     解析一次，捕获一切，永不丢弃        │
                      └──────────────┬───────────────────────┘
                                     │  capture.db (≈6 MB)
                                     │  ← 超集：任何投影都能重算
                      ┌──────────────┴───────────────────────┐
                      │ L2  INDUCE   模式归纳                 │
                      │     从数据反推 schema，不靠人写白名单   │
                      └──────────────┬───────────────────────┘
                                     │  schema.json + core.yaml.draft
                      ┌──────────────┴───────────────────────┐
                      │ L3  PROJECT  声明式投影               │
                      │     纯函数：project(capture, rules)   │
                      └──────────────┬───────────────────────┘
                                     │  result.json / assets/ / index.html
                      ┌──────────────┴───────────────────────┐
                      │ L4  PROVE    守恒校验                 │
                      │     每次丢弃都有理由，无理由即失败      │
                      └──────────────┬───────────────────────┘
                                     ▼  ledger.json（构建闸门）
```

### L1 — Capture（无损捕获）

**不变式：capture 是所有可能投影的超集。** 丢失从此只是"投影属性"，改规则不用重扫 XML。

对每个 XML 文件，用 `lxml.etree.iterparse` 流式解析（C 实现，常驻内存 O(深度) 而非 O(文件)），每个元素产出一行记录：

| 字段 | 说明 |
|---|---|
| `doc_id` | 文件 sha256 前 16 位（内容寻址 → 天然支持增量重扫） |
| `node_path` | 结构路径 `0/2/1`：从文档根开始的孩子序号链。**无字符串歧义**，可寻址 |
| `parent_path` | 父节点结构路径 |
| `tag` | 元素名 |
| `ordinal` | 同名兄弟间的序号 → 无需路径字符串就能区分重复子元素 |
| `depth` | 深度 |
| `attrs` | **全部属性**的 JSON（不筛） |
| `text` | 文本内容（不筛） |

存储用 SQLite（`documents` / `nodes` / `attrs` 三表，`(tag, doc_id)` 建索引）。规模估算：63,981 元素 × ~100 B ≈ **6.4 MB**，相对 720 MB 的包可以忽略。

同时建立两个全局索引（这正是修掉 §2.3 的关键）：

- `basename → [doc_id...]`：解析 `inherit_from` 用，**O(1)**，且**歧义是显式可查的**
- `key → doc_id`：解析实体互相引用用

**L1 不包含任何 selector、白名单、`must_have_attr` 或唯一性过滤。** 只要在 XML 里，就在 capture 里。

### L2 — Induce（模式归纳）

**替代 `coverage_check.py` 的硬编码 glob。** 从 capture 统计归纳，而不是从配置推断：

对每个 `(root_tag, node_path 签名)` 统计：
- **出现次数**（多少文档里有）
- **属性频次表** —— 哪些属性 100% 出现（必填），哪些 3% 出现（可选/特例）
- **基数**：相对父节点是 1:1 还是 1:N → **自动判定 `is_array`**（现在这个字段是人手猜的）
- **类型推断**：按值分布判定 `int`/`float`/`vector2`/`vector3`/`bool`/枚举/字符串，带置信度
- **枚举值域**：为 `class`、`type`、`state` 这类字段自动列出所有取值

**实体类型自动发现**：一个标签若满足"有 `key`/`name`、出现次数 > N、且存在 1:1 的 owner 关系"，就候选为实体类型。这能自动捞出 `<visual_item>`(57 文件)、`<character>`(84 文件)、`<squad_config>` 等当前完全不可见的域。

**产出** `schema.json`（完整宇宙 + 统计），再据此生成一份 `core.yaml.draft` 超集。人的工作从"发现字段"降级为"命名 + 裁剪"。**游戏更新加了一个属性时，schema diff 会自动把它标出来**——这是"不容易丢失"在日常运维上的落地方式。

### L3 — Project（声明式投影）

规则仍是 YAML（**对现有 `core.yaml` 向后兼容**），但匹配语义修正如下：

**(1) 按标签匹配，不按文档根匹配。** 任何 `tag == selector` 的元素都是候选实体，并记录其最近的容器祖先。这一条单独就能救回 `<resources>`、`<faction>` 里的实体，且不再依赖 `selector + "s"` 这个脆弱的猜测规则。

**(2) 显式建模三种节点角色**（这是修 §2.1(b)(c) 的关键）：

| 角色 | 例子 | 语义 |
|---|---|---|
| `definition` | `<vehicle key="jeep" ...>` 根文件 | 完整定义 |
| `container` | `<vehicles>`、`<weapons>` | 一组引用，带作用域（哪张地图） |
| `patch` | `<resources clear_weapons="1">`、`<faction>` 子节点 | 覆盖：启用/禁用/改字段 |

投影输出也相应变成**分层的**，而不是一张扁平表：

```
definitions:  {vehicle: {jeep: {...}}}
scopes:       {map14: {vehicles: [jeep, apc, ...]}}     ← 现在完全丢失的维度
patches:      {faction:green: {weapon: {medikit: {enabled: true}}}}
```

`enabled` 状态在最后一层解析（definition ⊕ patch），而不是像现在这样靠继承把引用洗成定义。

**(3) 子元素用直接子节点匹配。** `child::tag` 为默认，当前的递归 `find_all` 行为改为显式 `deep: true` 的 opt-in。修掉 turret/visual 跨层污染。

**(4) `/` 路径基于 `node_path` 逐级直接子节点导航，不用 `find_all`。** 且**命中多个元素时返回列表，绝不 `values[0]`**。

**(5) 继承在图上解析，不在文件名上：**

- 用 L1 的 `basename → [doc_id]` 索引，**消除 `rglob` 线性搜索**
- 优先级**显式且确定**：`package_path` 顺序即优先级；包内按 manifest 顺序。**歧义（实测 4/47）直接报错，不再抛硬币**
- 合并 = 对 DAG 做拓扑折叠，而不是递归下降；每个字段记录**来源**（来自哪个基类）
- **环 → 硬失败并打印环路径**，不再静默截断
- **基类缺失 → 实体标记 `inherit_unresolved`**，下游能区分"没有这个字段"和"父类没找到"

**(6) 确定性。** 文档按 `(package_index, 相对路径字节序)` 排序，节点按文档序。`os.walk` 顺序、`rglob` 首个命中、`clean_final` 先到先得三处非确定性全部消除。**这是让 diff 重新有意义的前提。**

### L4 — Prove（守恒校验 / Loss Ledger）

**这一层是"不容易丢失"从愿望变成保证的地方。** 每次投影产出 `dist/ledger.json`：

```json
{
  "invariant": "captured == projected + dropped ; every drop has a reason",
  "entities": {
    "vehicle": {
      "captured": 238, "projected": 238, "dropped": 0,
      "attrs": {
        "ai_driver_turns_to_target": {"captured": 12, "projected": 0,
                                      "reason": "not_in_schema", "severity": "info"}
      },
      "children": {
        "sky_diving": {"captured": 4, "projected": 0, "reason": "not_in_schema"}
      }
    },
    "weapon": {
      "captured": 418, "projected": 431, "dropped": -13,
      "note": "projected > captured: container stubs promoted via inheritance"
    }
  },
  "files": {"walked": 3951, "classified": 3951, "parsed": 1585, "parse_errors": 0},
  "encoding_replacements": {"common.resources": 2}
}
```

**固定理由词表**（每个丢弃必须落入其中之一）：

| reason | 含义 | 今天的行为 |
|---|---|---|
| `not_in_schema` | 没有规则覆盖 | 静默消失 |
| `schema_stale` | 有规则但路径在数据里不存在 | 静默消失 |
| `uniqueness_filter` | `unique` 重复 → 实体被丢 | 只有 warning |
| `must_have_filter` | 缺必需属性 | 静默 `continue` |
| `key_collision_merge` | key 冲突，标量被覆盖 | 静默且顺序相关 |
| `inherit_unresolved` | 基类未找到 → 半成品 | 只有 warning |
| `inherit_ambiguous` | 基类名命中多个文件 | **今天完全检测不到** |
| `inherit_cycle` | 环被截断 | 只有 warning |
| `parse_error` | 文件解析失败 | 一行 warning，文件消失 |
| `encoding_replaced` | 编码嗅探导致字符被替换 | **今天完全检测不到** |

**构建闸门**：`inherit_ambiguous` / `key_collision_merge` / `parse_error` / `encoding_replaced` 默认 `severity: error`，出现即 **exit code ≠ 0**。`not_in_schema` 默认 `info`（不建模的东西本来就不会提取），但**必须列出并计数**——因为"我知道我丢了 74 个属性"和"我不知道我丢了什么"是完全不同的两件事。

**对账表**：`walked == classified == parsed + parse_errors`，以及 `Σ capture 元素 == capture.db 行数`。任何一处不平即失败。

---

## 4. 效率账（全部为实测）

### 4.1 已实测的收益

| 环节 | 现状 | 新方案 | 实测依据 |
|---|---|---|---|
| XML 解析 | BeautifulSoup 建整棵树 **0.63 s** | `lxml.iterparse` 流式 **0.05 s** | **12.6×**（1,585 文件 / 63,981 元素） |
| 目录遍历 | `os.walk` **两遍**（一遍只为进度条总数） | 一遍 | `file_utils.py:36-38` + `41` |
| 文件读取 | 每个文件打开两次 + 5 字节猜编码 | 一次读入，从头字节嗅探 | `main.py:96` + `main.py:130` |
| 基类解析 | 每次 `rglob` 线性搜 | 一次建索引，O(1) 查询 | 索引构建 0.01 s，47 次查询 <1 ms |
| 规则迭代 | 改一条规则 → 重扫 720 MB / 6.9 s | 重放 capture（不碰 XML） | capture ≈ 6 MB |
| 增量重扫 | 每次全量 | 内容寻址，只重解析变更文件 | `doc_id = sha256` |

### 4.2 需要说清的一点

**当前全量管线只要 6.93 秒，性能不是痛点。** 本方案的价值不在于把 6.9 s 变成 3 s，而在于：

1. **规则迭代从秒级降到毫秒级**（重放 6 MB 快照 vs 重扫 720 MB）——这才是日常开发真正卡手的地方
2. **新增的无损捕获层几乎不增加成本**：12.6× 的解析加速足以覆盖 capture 层的开销，净成本接近零
3. **确定性带来的 diff 能力**，是发现回归的唯一手段——这一项无法用秒数衡量

如果只想要性能，改 `lxml` 就够了（一行 import）。**如果目标是"不丢数据"，必须做 L4。**

---

## 5. 该做什么：最小修复集

**先自我推翻一句**：上面 §3 的"四层架构 + 五阶段迁移"是按"完整方案"写的。按 ponytail 的标准审一遍，它对 5.6 MB XML、6.9 秒跑完的代码库是**过度设计**。真正的病不是"缺少捕获层"，是**六个具体 bug** + 一个"配置从来没补全"的事实。

### 5.1 必修 —— 不修则无法验证任何东西（净增约 15 行）

| # | 位置 | 问题 | 修法 |
|---|---|---|---|
| 1 | `util/file_utils.py:36-45` | `os.walk` 不排序 → 输出随文件系统变化 | `dirs.sort(); files.sort()` —— **2 行，也是所有 diff 的前提** |
| 2 | `util/ops.py:338` | `rglob` 取第一个命中，47 个基类名里 4 个歧义 | 收集全部命中：`>1` 就 `logger.error` 并按 `sorted()` 取定 —— **3 行，比建索引更省**（实测单次 `rglob` 仅 0.1 ms，索引是纯 YAGNI） |
| 3 | `util/ops.py:351` | 缓存键用文件名不带路径，同名基类互相污染 | 解析出 `base_path` 后再查/写缓存 |
| 4 | `main.py:134` | `except Exception: warning` 吞掉整个文件 | 加计数器，收尾打印 `parsed / failed` —— **3 行** |
| 5 | `main.py:36-44` | `clean_final` 标量"先到先得" | 有了 #1 之后行为至少可复现；再补一个冲突计数 |
| 6 | `util/index_html.py` / `main.py` | 无 | — |

第 1 条单独就值回票价：**它把 `result.json` 从"每次可能都不一样"变成"可以 diff"**。没有它，后面所有修改都无法验证。

### 5.2 逐项修 —— 会改变输出，必须一个个开、一个个对比

| # | 位置 | 问题 | 修法 | 风险 |
|---|---|---|---|---|
| 7 | `util/ops.py:258` | 子元素 `find_all` 是**递归**的 | 加 `deep: bool = False` 配置位，逐对切换 | **不能一刀切**，见下 |
| 8 | `util/ops.py:483` | `/` 路径导航也是递归的 | 同上 | 低 |
| 9 | `util/ops.py:476` | `values[0]` 只取第一个 | 命中多个时返回列表 | 改变 JSON 形状，需下游配合 |
| 10 | `util/ops.py:109-135` | `unique` 重复丢弃**整个实体** | 降级为"丢弃该字段 + 记数" | 输出变多，需确认 |

**第 7 条我实测过，结论是不能一刀切：**

```
parent                child                recursive  direct  extra(nested)
vehicle               turret                     192     109      83   ← 污染
soldier               item_class_existence       614       0     614   ← 一刀切会毁数据
soldier               model                      218     135      83
achievement           level                      108      48      60
（其余 70 对 recursive == direct，无差异）
```

`vehicle → turret` 多出的 **83 个，正好等于 `character_slot → turret` 的 83 个**——`character_slot` 里的炮塔被塞进了 `vehicle.turrets`。这是坐实的串层污染。

但 `soldier → item_class_existence` 是 **614 → 0**：该元素**只**出现在嵌套位置。全局改 `recursive=False` 会反向毁掉 614 条数据。所以正确做法是新加一个**默认直接的 `deep` 开关**，只对 `vehicle/turret`、`soldier/model`、`achievement/level` 这三对打开 `deep: true`。约 10 行。

### 5.3 不是算法问题，别用算法解决

- **74 个未提取属性** = 去 `config/core.yaml` 里补规则。`util/coverage_check.py` 已经把清单列好了（它唯一的毛病是硬编码了 10 个实体类型和固定 glob，改成从 `result.json` + 实际扫描对比即可，不用重写成"模式归纳层"）。
- **`<resources>` / `<vehicles>` 的引用语义**（§2.1b/c）= 一个**建模决策**：要不要在输出里保留"哪张地图有哪些载具"。要，就加一个 `scopes.json`；不要，就当引用不存在。这跟提取算法无关。
- **AS 解析器的 80 行截断**（`as_parser.py:45`）= 把 `80` 改大或改成配平到块尾。**1 行。**

### 5.4 什么时候才真的需要 capture 层

只有这三种情况之一成立，才值得建 L1：

1. 规则迭代的频率高到"重扫 6.9 秒"确实卡手（现在不是）；
2. 需要**回溯**——比如三个月后发现某字段当年提取错了，想从快照重算而不是从磁盘重扫；
3. 需要**多套投影并存**（比如同时输出给 webhelper 和另一个消费端）。

否则 `result.json` 本身就是投影结果，再存一份超集只是多一个要同步的东西。

---

## 6. 取舍

| 决策 | 代价 | 建议 |
|---|---|---|
| 只修 §5.1 的 6 条 | 输出仍会变（去除非确定性），但变得**可复现** | **先做这个**，一天内能完成，立刻能 diff |
| `deep` 开关（§5.2 #7） | 输出**减少** 83+83+60 条嵌套误匹配 | 逐对开启并对比 |
| 补 `core.yaml` 规则 | 74 个属性一次性补完很枯燥 | 按 `coverage_check.py` 的清单分批，不急 |
| 建 capture 层 | 多一个 ≈6 MB 的中间产物要维护和同步 | 按 §5.4 的三条判据决定，**默认不做** |
| `inherit_ambiguous` 直接设 error | 实测 4/47 会立刻失败 | 先 `error` 观察一轮；这 4 个若已有隐式约定再降级 |

## 7. 一句话总结

RWROPS 现在的提取逻辑**看起来**是配置驱动的，**实际上**是靠一串默认放行、静默 `continue`、`except: pass`、`values[0]`、`rglob` 首个命中和"先到先得"撑起来的——每一步单独看都合理，合起来的效果是**你无法回答"这次 `result.json` 比上次少了什么"**。

**先修的是"让输出可复现"（`os.walk` 排序，2 行），然后才是"让丢失可见"（解析失败计数、基类歧义报错）。** 至于把白名单写得更全——那是作业量，不是设计问题；`coverage_check.py` 已经把 74 个漏掉的属性列好了。

LCP 四层模型（§3）能把丢失变成一条构建时会失败的断言，但那是这个代码库当前不需要的保证。**先花一天做完 §5.1，再决定要不要买那份保险。**

---

## 附：本次使用的探测脚本

两个无过滤的全包扫描脚本，报告里所有数字都出自它们（均为 untracked，未提交）：

```bash
uv run python -m util._probe_universe   # 文件分类 / 根元素频率 / 属性·元素宇宙
uv run python -m util._probe_cost        # 覆盖率分类学 + BeautifulSoup vs iterparse 基准
```

第三个（递归 vs 直接子节点对比，§5.2 #7 的数据来源）临时放在 `/tmp/_recursive.py`，需要长期保留的话建议一并挪进 `util/`。
