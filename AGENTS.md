# AGENTS.md — rwrops 工程规范

面向人类和 AI agent。**动这个仓库之前，先读完 §2 和 §3。**
违反 §2 或 §3 的改动一律不接受，无论代码多漂亮。

---

## 1. 数据流与边界

```
vanilla/*.xml  ──[rwrops]──▶  dist/  ──[EdgeOne Pages]──▶  rwrops-webhelper
                               result.json                  (React SPA, 独立仓库)
                               metadata.yaml
                               assets/  (内容哈希)
                               index.html
```

- 本仓库只负责**提取**。渲染在 `../rwrops_webhelper`（`VITE_DATA_SOURCE` 指向 `dist/` 或线上 URL）。
- 上游是游戏包（默认 `…/media/packages/vanilla`，720 MB / 1,585 个 XML）。
- 线上数据地址即 `dist/` 的部署结果，不是本仓库的代码。

---

## 2. 门禁：每次改动必须过

```bash
./gate.sh                    # 与上一次输出对比（自动保存 dist/result.prev.json）
./gate.sh /path/golden.json  # 与指定基线对比
```

四关，任一失败即停止排查：

| 关 | 检查 | 失败意味着 |
| --- | --- | --- |
| 1 | `main.py` 退出码 + `result.json` sha256 | 管线挂了 |
| 2 | **连跑两次，字节必须相同** | 非确定性：`os.walk` 顺序、`rglob` 首个命中、`clean_final` 先到先得 |
| 3 | `[gate]` 丢弃计数 | 有东西被丢掉，且必须能解释 |
| 4 | `util/diff.py` 与基线对比 | **`DISAPPEARED` 非空 = 数据丢了，exit 1** |

**硬性要求**

1. 提交前必须 `GATE PASS`。贴出 gate 输出，不要只说"跑过了"。
2. 第 2 关失败**优先修确定性**，不要去调基线。输出不稳定时 diff 没有意义。
3. 第 4 关报 `DATA LOST` 时，**默认当作真丢数据**。确认是「去重/去污染」这类刻意行为，才能在提交信息里说明并接受。
4. 换机器 / 换文件系统 / 加删文件之后，先跑一次门禁再信任何 diff。

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

`gate.sh` 第 3 关的每一项非零都要能说出原因。当前基线（属正常）：

```
[gate] inherit_scoped:        340    按作用域规则解决，不是盲猜
[gate] inherit_ambiguous:       1    真平局（wiesel_spawn.vehicle 同 key 双定义）
[gate] child_dropped_empty:    87    元素不含任何被配置提取的属性（已逐条查清）
[gate] parse_error:             0    必须为 0，非 0 立刻查
```

新增丢弃点时，**必须同时在 `util/gate.py` 里 `bump` 一个理由**。禁止静默 `continue` / `except: pass`。

### 3.5 改动后的人工复核清单

- [ ] `./gate.sh` → `GATE PASS`，且输出贴进提交信息
- [ ] 第 4 关 `DISAPPEARED` 为空，或有明确且已验证的解释
- [ ] 第 3 关计数器全部能解释
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

| 站点 | 目录 | 项目 |
| --- | --- | --- |
| **数据**（`dist/`，供 webhelper 跨域拉取） | `RWR/rwrops/dist` | 见下 |
| **前端**（React SPA） | `RWR/rwrops_webhelper/dist` | `rwropswh` / `pages-fj64cuxx2y1z`（记录在 `.edgeone/project.json`） |

### 5.2 部署

```bash
cd RWR/rwrops
./gate.sh && edgeone pages deploy dist        # 必须先过门禁
```

```bash
cd RWR/rwrops_webhelper
npm run build && edgeone pages deploy dist
```

> ⚠️ **`rwrops/.edgeone/` 里没有 `project.json`**（只有上次部署的 assets 缓存），
> 而 webhelper 有。所以首次从本机部署数据站时，CLI 可能要求重新选择项目 ——
> **确认项目名再回车**，选错会新建一个站点。稳妥做法是先 `edgeone pages link`。

### 5.3 `dist/edgeone.json` 是部署配置，不是构建产物

```json
{ "headers": [{ "source": "/*", "headers": [ Access-Control-Allow-Origin: * ] }],
  "caches":  [{ "source": "/assets/*", "cacheTtl": 604800 }] }
```

- **CORS `*` 是必须的** —— webhelper 在另一个域名跨域拉 `result.json` / `assets/`。
  删掉它前端会直接白屏，且本地开发察觉不到。
- **`/assets/*` 缓存 7 天是安全的**，因为文件名带内容哈希（`xxx-<sha256[:8]>.png`）。
- **`result.json` 刻意不缓存**，所以数据更新后立刻生效，不需要刷 CDN。

### 5.4 部署顺序

数据先、前端后。前端会把 `result.json` 的字段路径写进用户配置（MetaGen），
先发前端而数据还是旧的，用户会拿到指向不存在字段的配置。

### 5.5 回退（部署前必须先做）

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
cd RWR/rwrops && edgeone pages deploy ../_rollback/rwr-static-live   # 数据站
cd RWR/rwrops_webhelper && git stash && npm run build && edgeone pages deploy dist  # 前端
```

前端不需要镜像——它的源码在 git 里，回退就是 checkout 旧提交后重建。

**部署顺序：破坏性变更要「前端先、数据后」。**

`AGENTS.md` §5.4 说数据先，那是对**增量**变更而言（前端会把字段路径写进用户配置）。
但对**破坏性**变更（如 result.json 换形状），旧前端读新数据会直接崩，所以反过来。

前提是两端都装了**过渡垫片**：新前端/新 bot 同时认旧形状（打 warning），
这样顺序任意、数据与前端可各自独立回退。垫片在 schema 2 稳定一段时间后删掉。

### 5.6 线上地址

| 站点 | 地址 | 备注 |
| --- | --- | --- |
| 数据 | `https://rwr-static.079682.xyz` | 线上有效，前端与 bot 都从这里取数 |
| 前端 | `https://rwrops.079682.xyz` | **当前 NXDOMAIN（连 8.8.8.8 也查不到）**，README 里的地址是旧的 |

改前端域名时，记得同步 `rwrops_webhelper/README.md` 和 `scripts/generate-sitemap.js`。

---

## 6. 代码约定

1. **丢弃必须计数。** 任何 `continue` / `return None` / `except` 掩盖数据的地方，加 `gate.bump("<reason>")`，理由用 snake_case。
2. **不要静默 `except Exception: pass`。** 至少 `logger.warning` + 计数。
3. **遍历必须有序。** 新增任何文件遍历/查找，先 `sorted()`。
4. **一个输出。** 不要为了兼容再发一份 JSON；契约变了就改前端。
5. **不要凭直觉改匹配语义。** 先按 §3.3 量。
6. **`config/` 是 git-ignored**（`.gitignore:17` 的 `config/*`，只白名单 `*.example` / `*.dis`），
   但 `config/core.yaml` 是**已跟踪**的，忽略规则不作用于已跟踪文件。
   复制别人的配置进来时（`core.yaml.dis` 之类）要清楚它**不会**被提交：

   ```bash
   git check-ignore -v config/core.yaml   # 无输出 = 已跟踪，正常
   git check-ignore -v config/foo.yaml    # 输出 .gitignore:17 = 会被忽略
   ```
7. Python ≥ 3.14，依赖用 `uv`（`lxml` 已在依赖里，需要更快解析时直接可用）。

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
- ❌ 在 `dist/` 上做手工修改 —— 它是生成物，会被下次运行覆盖。

**不确定时**：跑 §3.1 的工具、给出实测数字，再问。不要猜。

---

## 8. 相关文档

- `CAPTURE_ALGORITHM.md` —— 丢失审计报告、根因分析、实测数据、以及被实测推翻的猜想（§5.5）。
  想理解「为什么现在的做法是这样」就读它。
- `README.md` —— 使用说明。（其仓库链接曾写成 `rwrops-core`，已于本次修正为 `rwrops`；如需再改仓库名，两处一起改。）
