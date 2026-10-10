# AGENTS.md — rwrops 工程规范

面向人类和 AI agent。**动这个仓库之前，先读完 §2 和 §3。**
违反 §2 或 §3 的改动一律不接受，无论代码多漂亮。

---

## 1. 数据流与边界

```
media/packages/*  ──[rwrops]──▶  dist/  ──[EdgeOne Pages]──▶  rwrops-webhelper
                                  packages/<id>/result.json   (React SPA, 独立仓库)
                                  packages/<id>/metadata.yaml
                                  packages/<id>/assets.json
                                  packages.json   (包索引)
                                  assets/         (全局内容哈希池)
                                  index.html      (包选择落地页)
```

- 本仓库只负责**提取**。渲染在 `../rwrops_webhelper`（`VITE_DATA_SOURCE` 指向 `dist/` 或线上 URL）。
- 上游是游戏包根目录 `…/media/packages`（2.4 GB / 22 个顶层包 / 约 1,968 个可解析文件）。
- **每个顶层包一个数据集**，不是一份合并数据。见 §1.1。
- 线上数据地址即 `dist/` 的部署结果，不是本仓库的代码。

### 1.1 包 = VFS 覆盖层，不是目录

`classic/` 自己有 103 个文件，`ww2_invasion/` 有 28 个——单看目录会以为它们是两个小包。
实际上它们是**覆盖层**：游戏把 base 包和 mod 一起挂载，顶层定义赢。单独解析一个覆盖层
得到 100 来条记录，然后管它叫「classic 包的数据」，既没用又误导。

所以每个包的层栈是（`util/packages.py`）：

```
layers(P) = [ 声明的 base 包, 按名排序 ]
          + [ P/packages/<dep> 覆盖, 按名排序 ]
          + [ P 自己的树，排除 P/packages ]
```

`packages/` 子目录有两种含义，靠**同名顶层包是否存在**区分：

| 形态 | 含义 |
| --- | --- |
| `classic/packages/vanilla/`，且顶层有 `vanilla/` | 对该包的**补丁**。键相对 `classic/packages/vanilla/` 计算，因此能覆盖到 base 的键 |
| `ww2_base/packages/ww2_undead/`，顶层没有 `ww2_undead/` | 该包**自带**的独立子包，像普通层一样贡献文件 |

没有 `packages/` 子目录的包叠在 `default_base`（`vanilla`）上，除非它自己就是 base。
这对 `pvp` / `teddy_hunt` / `camera_mod` 是对的，对 WW2 的几个组件包无害（它们只会通过
`ww2_base` 被使用）。

合并规则是**按包内相对路径去重，后一层赢**，丢弃数记在 `[gate] layer_overridden`。
`parse_paths` 传给解析器时是**反序**的（mod 在前），这样 `inherit_from` 优先取覆盖版本。

---

## 2. 门禁：每次改动必须过

```bash
./gate.sh                    # 与 .gate/ 里每个包的基线对比（通过后自动刷新基线）
./gate.sh /path/to/basedir   # 与 <basedir>/<包名>.json 对比
```

四关，任一失败即停止排查：

| 关 | 检查 | 失败意味着 |
| --- | --- | --- |
| 1 | `main.py` 退出码 + 各包 `result.json` 的合并 sha256 | 管线挂了 |
| 2 | **连跑两次，全部包字节必须相同** | 非确定性：`os.walk` 顺序、层序遍历、`find_file_in_package_paths` 平局 |
| 3 | `[gate]` 丢弃计数（**按包分别报**） | 有东西被丢掉，且必须能解释 |
| 4 | `util/diff.py` 逐包与基线对比 | **`DISAPPEARED` 非空 = 数据丢了，exit 1** |

基线在仓库根的 `.gate/<包名>.json`，不在 `dist/` 里：`dist/` 下的东西全都会上传到 CDN。
`main.py` 每次运行会清空 `dist/`（保留 `.edgeone` / `edgeone.json` / `.env` / `.gitignore` / `.cursor`），
所以基线不能放那儿。

**硬性要求**

1. 提交前必须 `GATE PASS`。贴出 gate 输出，不要只说"跑过了"。
2. 第 2 关失败**优先修确定性**，不要去调基线。输出不稳定时 diff 没有意义。
3. 第 4 关报 `DATA LOST` 时，**默认当作真丢数据**。确认是「去重/去污染」这类刻意行为，才能在提交信息里说明并接受。
4. 换机器 / 换文件系统 / 加删文件之后，先跑一次门禁再信任何 diff。
5. 禁止手改 `dist/`——它是生成物，下次运行会覆盖。

---

## 3. 必做的分析检查（确保没少东西）

### 3.1 工具

```bash
uv run python -m util.diff 旧.json 新.json     # 差异裁决：CHANGED / DISAPPEARED / APPEARED
uv run python -m util.coverage_check           # config 声明 vs XML 实际存在（缺哪些属性）
uv run python -m util._probe_universe          # 全包无过滤扫描：文件分类、根元素、属性宇宙
uv run python -m util._probe_cost              # 覆盖率分类学 + 解析基准
```

`util/diff.py` 的判定是**与顺序无关**的（列表重排不会淹没真实变化），并把差异分成三类：

- `CHANGED` — 同字段不同值
- `DISAPPEARED` — **字段消失 = 丢数据，exit 1**
- `APPEARED` — 新字段

### 3.2 「identical」不是「改对了」的证据

**这是本仓库最容易犯的错，已经踩过两次。**

改动可能在真实数据上**根本没有效果**（`deep` 开关、`/` 路径直接子节点，两次都是零影响），
此时门禁显示 `identical`，看起来"通过"，实际什么都没验证。

所以：**任何行为类改动，先证明它被加载/生效，再看 diff。**

```bash
# 例：确认配置真的读到了
uv run python -c "
import yaml; from util.classes import Config
cfg = Config(CONFIGFILE='core.yaml', **yaml.safe_load(open('config/core.yaml')))
print(cfg.entities['vehicle'].children['turrets'].deep)   # 期望 False
"
```

推论：**如果 diff 是 identical，先假设改动没生效**，验证后再决定是否保留。
零影响的改动只有在「消除潜在错误」时才值得留，且必须在提交信息里写明实测依据。

### 3.3 改动匹配/遍历语义前，先做小样本对比

不要直接改 `find_all` 的递归性、路径导航、selector 门控。先量：

```bash
# 递归 vs 直接子节点，逐对统计（本项目用过两次，脚本见提交历史 / §5.2 of CAPTURE_ALGORITHM.md）
```

已知反例，别再犯：

| 直觉 | 实测 |
| --- | --- |
| `recursive=False` 更正确，一刀切 | `soldier → item_class_existence` 会从 614 掉到 **0**（该元素只在嵌套位置）。**不能一刀切**，必须逐对 opt-in |
| `vehicle → turret` 有 83 个串层污染 | 污染真实存在，但**从未进过输出**——解析成 `{}` 被 `if child_data:` 挡住了 |
| `/` 路径递归会取错父节点 | 理论成立，实测 15,295 次匹配**零差异** |

**结论：静态读代码估出来的"丢失量"会大幅高估。一切以实测为准。**

### 3.4 计数器必须能解释

`gate.sh` 第 3 关的每一项非零都要能说出原因。计数器**按包分别报告**（`[gate][vanilla] …`）——
22 个包累计成一块没法解释。`vanilla` 包（= 单包模式的等价物）的基线：

```
[gate][vanilla] inherit_scoped:        340    按作用域规则解决，不是盲猜
[gate][vanilla] inherit_ambiguous:       1    真平局（wiesel_spawn.vehicle 同 key 双定义）
[gate][vanilla] child_dropped_empty:    87    元素不含任何被配置提取的属性（已逐条查清）
[gate][vanilla] entity_empty:            1
[gate][vanilla] parse_error:             0    必须为 0，非 0 立刻查
[gate][vanilla] derive_missing:          4    派生字段指向的文件不存在 → 写 null，**不是丢字段**
                                              （lobby 无 mapview_frame；lobby/map17/map20 无 mask）
[gate][vanilla] derive_extra_match:      7    一个 glob 匹配到多张 mask，只取第一个
                                              （map8/14/15/18/19/1_2/21 各有多张）
```

> **`derive_fields` 的值是包内相对路径，不是拍平名。** 它同时是 `assets.json` 的键空间，
> 前端就是拿这个值去索引里查图片的。历史上这里做 `.replace("/", "_")`，只有当文件**存在**时
> 才被 `main.py` 的 `rel_path_map` 兜回路径；文件不存在（3 张图无 mask）时拍平名直接漏进输出，
> 前端 404。现在：pattern 走 glob（mask 是 `{key}_mask*.png`），只接受真实存在的文件，
> 匹配不到写 `null` —— 字段集保持统一，`util/diff.py` 也能区分「显式空」和「解析器退化」。

覆盖层包另有三个理由：

```
layer_overridden       后一层覆盖了前一层的同路径文件——这是覆盖语义，不是丢数据
layer_bundled_package  包自带了一个顶层不存在的子包（ww2_base/packages/ww2_undead）
layer_base_missing     default_base 不在 packages 根下（不该出现，出现就是配置错了）
```

新增丢弃点时，**必须同时在 `util/gate.py` 里 `bump` 一个理由**。禁止静默 `continue` / `except: pass`。

### 3.5 改动后的人工复核清单

- [ ] `./gate.sh` → `GATE PASS`，且输出贴进提交信息
- [ ] 第 4 关 `DISAPPEARED` 为空，或有明确且已验证的解释
- [ ] 第 3 关计数器全部能解释
- [ ] 多包改动 → 确认 `vanilla` 包的输出**逐字节**等于改动前（它是单包语义的对照组）
- [ ] 装配了 `config/core.yaml` 的改动 → 跑 `util.coverage_check` 看覆盖有没有倒退
- [ ] 涉及匹配语义 → 已做 §3.3 的小样本对比
- [ ] 行为类改动 → 已按 §3.2 证明生效

---

## 4. 数据模型约定

**平铺，不聚合。** 这是刻意的，不是没做完。

`config/core.yaml` 的 `sort.enable: false` → 走 `main.py` 的平铺分支：每条记录独立存在，定义、`<vehicles>` 引用、`<resources>` 补丁**互不吞并**。

原因：`clean_final`（聚合分支）会按 `key` 合并，标量"先到先得"，实测丢掉 **65 个标量值**、**167 次合并**，且结果依赖文件遍历顺序。同时它把引用"洗"成定义，抹掉了「哪张地图/哪个阵营启用了哪些载具」这个维度。

| | 聚合 | 平铺 |
| --- | --- | --- |
| vehicle / projectile / carry_item | 323 / 289 / 576 | **379 / 331 / 622** |
| faction / language / call | 5 / 10 / 35 | **15 / 21 / 37** |
| key 冲突丢标量 | 65 | **0** |

**除非有明确理由，不要把 `sort.enable` 改回 `true`。** 要排序就在投影层加，不要在提取层合并。

### 基类解析：作用域相对

`vehicle_base.vehicle` 在包里存在 **3 份且内容不同**（`vehicles/`、`maps/map19/`、`maps/map21/`）。
解析规则（`util/ops.py:find_file_in_package_paths`）：

1. 引用方**自己目录**里的副本
2. 否则**最靠近包根**的（规范位置）
3. 字典序兜底

禁止退回 `rglob` 取首个命中 —— 那等于让结果取决于文件系统顺序。

---

## 5. 部署到 EdgeOne Pages

CLI 已安装：`edgeone`（v1.6.13，`edgeone whoami` 应显示 `banana.xiao@qq.com`）。

### 5.1 两个站点

| 站点 | 部署目录 | 项目名 | 项目 ID | 线上地址 |
| --- | --- | --- | --- | --- |
| **数据** | `RWR/rwrops/dist` | `rwrops` | `makers-yfee59lv76jg` | `https://rwr-static.079682.xyz`（自定义域名） |
| **前端** | `RWR/rwrops_webhelper/dist` | `rwropswh` | `pages-fj64cuxx2y1z` | `https://rwrops.b.rwr-infra.uk`（自定义域名；`rwropswh.edgeone.dev` 401） |

两个项目都已有 `.edgeone/project.json` 记录绑定。

### 5.2 部署

```bash
cd RWR/rwrops
./gate.sh && edgeone makers deploy dist       # 必须先过门禁
```

```bash
cd RWR/rwrops_webhelper
npm run build && edgeone makers deploy dist
```

> ### ⚠️ 必须用 `edgeone makers deploy`，不要用 `edgeone pages deploy`
>
> `edgeone pages deploy` 是**已弃用的别名**：CLI 只打一行
> `"edgeone pages" is deprecated. Use "edgeone makers" instead.`，然后照样上传、
> 照样打印 `Deploy Success` 和一个 Deployment ID —— **但不会提升到 Production**。
> 线上域名继续返回旧内容。
>
> 2026-10-07 实测：连续三次 `edgeone pages deploy` 全部报成功，线上
> `metadata.yaml` 的 `language` 计数始终是旧值（23 而非 21）；同一条命令换成
> `edgeone makers deploy` 后立即生效。
>
> **验证手法**：别信 `Deploy Success`，去比字节。
> ```bash
> curl -s "https://rwr-static.079682.xyz/metadata.yaml?x=$(date +%s%N)" \
>   | diff - dist/metadata.yaml && echo CURRENT
> ```

> ### ⚠️ 绝对不要用 `--name` 去"试"项目名
>
> `edgeone makers deploy --name <x>` **在项目不存在时会直接新建一个项目**，不会询问。
> 猜项目名 = 凭空多一个站点，而且 **CLI 没有删除项目的命令**，只能去控制台手工删。
>
> 项目名已写在 `.edgeone/project.json`（已提交）。若文件丢失，去
> <https://console.tencentcloud.com/edgeone/pages> 查，不要靠试探。

### 5.3 `dist/edgeone.json` 是部署配置，不是构建产物

```json
{ "headers": [{ "source": "/*", "headers": [ Access-Control-Allow-Origin: * ] }],
  "caches":  [{ "source": "/assets/*", "cacheTtl": 604800 }] }
```

- **CORS `*` 是必须的** —— webhelper 在另一个域名跨包拉 `result.json` / `assets/`。
  删掉它前端会直接白屏，且本地开发察觉不到。
- **`/assets/*` 缓存 7 天是安全的**，因为文件名带内容哈希（`xxx-<sha256[:8]>.png`）。
- **数据文件刻意不缓存**，所以数据更新后立刻生效，不需要刷 CDN。

### 5.4 部署体积

站点是整体上传，所以 `dist/` 的**每个字节都会上传**：

| 部分 | 量级 | 说明 |
| --- | --- | --- |
| `assets/` | ~620 MB / 1,874 文件 | 全局内容哈希池。22 个包共 21,900 次引用去重到 1,874 个文件 |
| ├ 其中地图 `objects.svg` | ~276 MB / 49 文件 | 每张地图的对象布局覆盖层，`map_config.objects_svg` 指向它。最大的 12.1 MB（< 25 MB 单文件上限）。SVG 是文本，边缘压缩后约为原体积 1/3 |
| `packages/*/result.json` | ~90 MB | 每包 4–5 MB |
| `packages/*/index.html` | ~66 MB | 每包约 3 MB，内联了该包全部表格 |
| `packages.json` + `metadata.yaml` + 落地页 | < 100 KB | 包选择器的数据 |

整站约 **881 MB**（EdgeOne 免费版：单文件 25 MB / 单项目 20,000 文件 / 站点总容量 5 GB，均在限内）。
`objects.svg` 占了大头——它原先被 `classify()` 当配置文件跳过，导致每张地图的 objects 层都是坏图。
若要砍体积，先量再砍，别默默跳过。

`generate_index_html: false` 可以砍掉那 66 MB——线上真正用的是 webhelper 前端，
`index.html` 只是离线可读的兜底。改部署体积前先量。

### 5.5 部署顺序

**增量变更**：数据先、前端后。前端会把 `result.json` 的字段路径写进用户配置（MetaGen），
先发前端而数据还是旧的，用户会拿到指向不存在字段的配置。

**破坏性变更**（如这次把根 `result.json` 换成 `packages/<id>/result.json`）：**前端先、数据后**。
旧前端读新数据会直接崩。两端都装了垫片，所以顺序任意、可各自独立回退：

- 前端 `dataSource.js`：拿不到 `packages.json` 就退回旧的单数据集路径（打 warning）。
- bot `loader.py`：认旧的裸 `result.json` 形状（打 warning）。

### 5.6 回退（部署前必须先做）

EdgeOne Makers 是**整体覆盖上传，没有版本历史**，CLI 也没有回退子命令（只有 init/dev/link/deploy）。
所以**回退的唯一凭据是部署前自己留的副本**。

**部署前：**

```bash
# 1. 记录并镜像线上数据站（脚本见下）
python3 RWR/rwrops/tools/mirror_live.py https://rwr-static.079682.xyz \
        /Users/bananaxiao/Documents/RWR/_rollback/rwr-static-live

# 2. 验证镜像指纹等于线上
shasum -a 256 _rollback/rwr-static-live/result.json
curl -sS https://rwr-static.079682.xyz/result.json | shasum -a 256
```

**回退：**

```bash
cd RWR/rwrops && edgeone makers deploy ../_rollback/rwr-static-live   # 数据站
cd RWR/rwrops_webhelper && git stash && npm run build && edgeone makers deploy dist  # 前端
```

前端不需要镜像——它的源码在 git 里，回退就是 checkout 旧提交后重建。

### 5.7 域名现状

前端可公开访问的域名是 **`https://rwrops.b.rwr-infra.uk`**（EdgeOne 自定义域名，指向
`rwropswh` 项目，实测 200）。另外两个都不是它：

- `rwrops.079682.xyz` —— **死的**（NXDOMAIN），README 里写的那个
- `rwropswh.edgeone.dev` —— EdgeOne 默认域名，返回 **401**（站点访问鉴权开着），`eo_token` 也进不去

改域名时记得同步 `rwrops_webhelper/README.md` 和 `scripts/generate-sitemap.js`
（后者目前仍写着 `rwrops.079682.xyz`）。

---

## 6. 代码约定

1. **管线注入的元字段一律 `_` 前缀。** 配置能提取的字段名都是普通标识符，core.yaml 里没有任何以 `_`
   开头的 target，所以 `_` 前缀**结构上不可能与实体字段冲突**。
   这不是洁癖：`_id`/`_source` 原本叫 `id`/`source`，而 `language` 规则会提取 `@id`（语言代码），
   被覆盖后**线上语言切换直接失效**。新增任何注入字段前先查：
   `grep -n 'target: "_' config/core.yaml` 应为空。
2. **丢弃必须计数。** 任何 `continue` / `return None` / `except` 掩盖数据的地方，加 `gate.bump("<reason>")`，理由用 snake_case。
3. **不要静默 `except Exception: pass`。** 至少 `logger.warning` + 计数。
4. **遍历必须有序。** 新增任何文件遍历/查找，先 `sorted()`。
5. **一个输出。** 不要为了兼容再发一份 JSON；契约变了就改前端。
6. **不要凭直觉改匹配语义。** 先按 §3.3 量。
7. **`config/` 是 git-ignored**（`.gitignore:17` 的 `config/*`，只白名单 `*.example` / `*.dis`），
   但 `config/core.yaml` 是**已跟踪**的，忽略规则不作用于已跟踪文件。
   复制别人的配置进来时（`core.yaml.dis` 之类）要清楚它**不会**被提交：

   ```bash
   git check-ignore -v config/core.yaml   # 无输出 = 已跟踪，正常
   git check-ignore -v config/foo.yaml    # 输出 .gitignore:17 = 会被忽略
   ```
8. Python ≥ 3.14，依赖用 `uv`（`lxml` 已在依赖里，需要更快解析时直接可用）。
9. **路径相对化必须取「最深根」，不能取首次匹配。** `parse_paths` 是 mod-first，包的自身目录
   排在它的 `packages/<dep>` 覆盖挂载**之前**，所以裸 `relative_to()` 会先命中外层目录，把覆盖
   文件键成 `packages/vanilla/maps/map11/map.png` —— 没有任何记录引用这个键，文件随后被 `refs`
   过滤掉，整张图**静默消失**（`classic` 的 10 张 `map.png` 就这么丢的，前端表现为地图缩略图空）。
   一律用 `util/ops.relative_to_roots()`：它返回最短相对路径，也就是文件真正所在的那个根。

---

## 7. Agent 红线

**必须做**

- 动手前读完 §2、§3。
- 每次改动后跑 `./gate.sh`，并把输出贴给用户。
- 改匹配语义前先做小样本实测（§3.3）。
- 行为类改动先证明生效（§3.2）。
- 提交信息里写清：改了什么、门禁结果、diff 里 `DISAPPEARED` 的解释。
- 发现文档与代码不符时**报告**，不要照文档写代码。

**禁止做**

- ❌ 跳过门禁直接提交，或把 `GATE FAIL` 说成通过。
- ❌ 为了让 gate 变绿而调基线 / 改 golden 文件。
- ❌ 用「代码看起来对」代替实测，尤其是匹配语义。
- ❌ 静默丢数据：`except: pass`、无计数的 `continue`、无理由的 `return None`。
- ❌ 把用户既有的未提交改动一起提交。`git status` 先看清楚哪个文件是谁改的。
- ❌ 未经确认 `git push`（本地提交可以，推送不行）。
- ❌ 用 `edgeone makers deploy --name <猜的>` 试探项目名 —— 项目不存在时它会**直接新建**，
  而 CLI 没有删除命令。项目名看 `.edgeone/project.json`（§5.2）。
- ❌ 在 `dist/` 上做手工修改 —— 它是生成物，会被下次运行覆盖。

**不确定时**：跑 §3.1 的工具、给出实测数字，再问。不要猜。

---

## 8. 相关文档

- `CAPTURE_ALGORITHM.md` —— 丢失审计报告、根因分析、实测数据、以及被实测推翻的猜想（§5.5）。
  想理解「为什么现在的做法是这样」就读它。
- `README.md` —— 使用说明。（其仓库链接曾写成 `rwrops-core`，已于本次修正为 `rwrops`；如需再改仓库名，两处一起改。）
