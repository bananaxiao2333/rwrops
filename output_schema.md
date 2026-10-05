# result.json 数据结构参考文档

> **本文档是 rwrops 输出的唯一契约。** 消费者（webhelper / rwrops-bot / 其他）一律以本文为准；
> 不要在别处再抄一份——历史上 `output_schema.md` 曾存在两份副本，靠人手同步。

- 当前版本：**schema 2**
- 生成方：`rwrops/main.py`（`SCHEMA_VERSION`）
- 各实体字段清单见下文 §1 起；**字段本身未变**，变的是外层信封与记录身份。

---

## 顶层结构

```json
{
  "schema": 2,
  "counts": { "vehicle": 379, "weapon": 432, "carry_item": 622, ... },
  "records": [
    {
      "id": "vehicle:radio_jammer.vehicle@maps/map13/radio_jammer.vehicle",
      "type": "vehicle",
      "key": "radio_jammer.vehicle",
      "source": "maps/map13/radio_jammer.vehicle",
      ...实体字段
    }
  ]
}
```

### 为什么是平铺数组，不是 `{type: {key: 实体}}`

旧的 `{type: {key: 实体}}` 形状**装不下现在的数据**：实测 2,063 条记录里有 **295 条的 `(type, key)` 重复**
（`vehicle.radio_jammer.vehicle` 出现 **5 次**，`faction.Neutral` 4 次），因为同一个 key 可以定义在多个文件里。
字典里一个 key 只能有一个值，所以那 295 条必然互相覆盖，且不报错。

平铺是唯一无损的形状。**分组是消费者的选择，不是数据的属性**——需要 `{type: {key: ...}}` 就在客户端归组（见下）。

### 每条记录的身份字段

| 字段 | 说明 |
| --- | --- |
| `_id` | **全局唯一、跨运行稳定**，形如 `type:key@source`。用它做引用/跳转/去重，不要用 `key` |
| `type` | 实体类型名，与 `counts` 的键一致 |
| `key` | 实体 key，**可能缺失**（如 `<vehicles>` 里的引用），也不能当唯一标识 |
| `_source` | 包内**相对**路径（如 `vehicles/jeep.vehicle`）。绝不写绝对路径 |

> 元字段一律 `_` 前缀。配置里能提取的字段名都是普通标识符，core.yaml 中没有任何以 `_` 开头的
> target，所以 `_` 前缀**结构上不可能与实体字段冲突**。这不是风格洁癖：这两个字段本来叫
> `id`/`source`，而 `language` 规则会提取 `@id`（语言代码 `en`），被覆盖后前端语言切换直接失效。

`id` 稳定意味着它不随文件遍历顺序变化，可以安全地存进用户配置或外部链接。

### 注意事项

- **`schema` 必须检查。** 遇到不认识的版本请直接报错，不要猜着读——静默读错比崩溃难查得多。
- **没有时间戳。** 构建时间在 `metadata.yaml` 的 `timestamp`（消费者本就会拉这个文件）。
  `result.json` 刻意保持逐字节可复现，门禁依赖这一点。
- **同一 `key` 的多条记录是正常的**，它们来自不同文件，代表不同的定义/引用/补丁。
  聚合会让信息消失，不要聚合。

### 消费者适配示例

平铺 → 应用常见的 `{type: {key: 实体}}` 视图，约 8 行：

```js
// JS
function index(records) {
  const out = {};
  for (const r of records) {
    const t = r.type ?? "unknown";
    (out[t] ??= {})[r.key ?? r.id] ??= r;   // 同 key 取第一条；要全部就改成数组
  }
  return out;
}
const raw = await (await fetch(url)).json();
if (raw.schema !== 2) throw new Error(`unsupported schema ${raw.schema}`);
const data = index(raw.records);
```

```python
# Python
def index(records):
    out = {}
    for r in records:
        out.setdefault(r.get("type", "unknown"), {}).setdefault(r.get("key") or r.get("id"), r)
    return out

raw = httpx.get(url).json()
if raw["schema"] != 2:
    raise RuntimeError(f"unsupported schema {raw['schema']}")
data = index(raw["records"])
```

---

## 1. vehicle — 载具（379 条）

### 字段清单

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `key` | string | `@key` | 唯一标识，如 `"humvee.vehicle"` |
| `name` | string | `@name` | 显示名称 |
| `inherit_from` | string | `@file` | 继承自哪个基础载具 |
| `respawn_time` | float | `@respawn_time` | 重生冷却时间 |
| `unsteerable_ttl` | float | `@time_to_live_unsteerable` | 失控存活时间 |
| `map_index` | int | `@map_view_atlas_index` | 地图图集索引 |
| `min_fuel` | float | `@minimum_fill_requirement` | 最小加油量 |
| `max_speed` | float | `control/@max_speed` | 最大速度 |
| `acceleration` | float | `control/@acceleration` | 加速度 |
| `max_reverse_speed` | float | `control/@max_reverse_speed` | 最大倒车速度 |
| `min_health_to_steer` | float | `control/@min_health_to_steer` | 可操控最低血量 |
| `max_rotation` | float | `control/@max_rotation` | 最大旋转速度 |
| `max_water_depth` | float | `control/@max_water_depth` | 最大涉水深度 |
| `steer_smoothening` | float | `control/@steer_smoothening` | 转向平滑度 |
| `max_health` | float | `physics/@max_health` | 最大血量 |
| `blast_damage_threshold` | float | `physics/@blast_damage_threshold` | 爆炸伤害阈值 |
| `mass` | float | `physics/@mass` | 质量 |
| `broken_mass` | float | `physics/@broken_mass` | 损毁后质量 |
| `remove_collision_threshold` | float | `physics/@remove_collision_threshold` | 移除碰撞阈值 |
| `extent` | vec3 | `physics/@extent` | 包围盒大小 |
| `offset` | vec3 | `physics/@offset` | 位置偏移 |
| `top_offset` | vec3 | `physics/@top_offset` | 顶部偏移 |
| `collision_model_pos` | vec3 | `physics/@collision_model_pos` | 碰撞模型位置 |
| `collision_model_extent` | vec3 | `physics/@collision_model_extent` | 碰撞模型大小 |
| `visual_offset` | vec3 | `physics/@visual_offset` | 视觉偏移 |
| `friction_offset` | float | `physics/@friction_offset` | 摩擦力偏移 |
| `drag_offset` | float | `physics/@drag_offset` | 阻力偏移 |

### 子结构

**tags** — 标签列表
```json
[ { "name": "metal_heavy" }, { "name": "light_combat" } ]
```

**tire_sets** — 轮胎组
```json
[ { "offset": [0.96, 0.0, 1.568], "radius": 0.48 } ]
```

**turrets** — 炮塔
```json
[{
  "offset": [0.0, 1.88, -0.36],
  "weapon_key": "humvee_mg.weapon",
  "weapon_offset": [0.0, 0.4, 1.4],
  "weapon_recoil": 0.0,
  "max_rotation_step": 0.0002,
  "rotation": 0.0,
  "rotation_range": 360.0,
  "aim_shoot_threshold": 0.5
}]
```

**visuals** — 视觉模型
```json
[{
  "class": "chassis",       // 部件类型: chassis / tire / turret
  "key": "",                // 可选，如 "broken"
  "mesh": "humvee_body.mesh",
  "texture": "humvee.png"
}]
```

**character_slots** — 乘员槽位
```json
[{
  "type": "driver",
  "position": [0.0, 0.8, 0.4],
  "rotation": 0.0,
  "exit_rotation": 0.0,
  "hiding": 0.3,
  "attached_on_turret": 0,
  "seat_position": [0.0, 0.0, 0.0],
  "enter_position": [0.0, 0.0, 0.0],
  "animation_key": "",
  "animation_id": 0,
  "marker_offset": [0.0, 0.0, 0.4],
  "allow_weapon": 1,
  "weapon_slots": [{"allowed_weapon": "..."}],
  "turrets": [{"index": 0}]
}]
```

**rev_sounds / sounds / effects / events** — 音效与事件
```json
// rev_sounds
[{ "filename": "...", "low_pitch": 0.5, "high_pitch": 2.0, "volume": 0.5 }]

// sounds
[{ "key": "engine", "filename": "engine_loop.wav" }]

// effects
[{ "event_key": "...", "type": "...", "size": 1.0, "ref": "...", "layer": 0, "offset": [0,0,0] }]

// events
[{
  "key": "destroyed",
  "trigger": { "class": "timer", "value": 3.0 },
  "result": { "class": "spawn", "instance_key": "explosion.projectile" }
}]
```

### 完整示例

```json
{
  "key": "humvee.vehicle",
  "name": "Humvee",
  "inherit_from": "vehicle_base.vehicle",
  "tags": [{ "name": "metal_heavy" }, { "name": "light_combat" }],
  "max_speed": 22.0,
  "acceleration": 6.6,
  "max_health": 4.2,
  "mass": 4.5,
  "extent": [2.08, 0.0, 4.0],
  "tire_sets": [{ "offset": [0.96,0.0,1.568], "radius": 0.48 }],
  "turrets": [{ "offset": [0.0,1.88,-0.36], "weapon_key": "humvee_mg.weapon" }],
  "visuals": [
    { "class": "chassis", "mesh": "humvee_body.mesh", "texture": "humvee.png" },
    { "class": "chassis", "key": "broken", "mesh": "humvee_body_broken.mesh", "texture": "humvee_broken.png" }
  ],
  "character_slots": [{ "type": "driver", "position": [0.0,0.8,0.4], "hiding": 0.3 }],
  "type": "vehicle"
}
```

---

## 2. weapon — 武器（427 条）

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 唯一标识 |
| `name` | string | 显示名称，来自 `specification/@name` |
| `inherit_from` | string | 继承关系 |
| `class` | int | 武器分类 ID |
| `description` | string | 描述文本（取 #text） |
| `retrigger_time` | float | 射速间隔（秒） |
| `accuracy_factor` | float | 精度因子 |
| `sustained_fire_grow_step` | float | 后坐力增长步进 |
| `sustained_fire_diminish_rate` | float | 后坐力衰减速率 |
| `magazine_size` | int | 弹匣容量 |
| `can_shoot_standing` | bool | 可站立射击 |
| `suppressed` | bool | 是否消音 |
| `reload_one_at_a_time` | bool | 逐发装填 |
| `sight_range_modifier` | float | 瞄准范围修正 |
| `projectile_speed` | float | 弹头速度 |
| `projectiles_per_shot` | int | 每发弹丸数 |
| `model_filename` | string | 模型文件 |
| `hud_icon_filename` | string | 图标文件 |
| `inventory_price` | float | 价格 |
| `inventory_encumbrance` | float | 负重 |
| `weak_hand_hold_offset` | float | 弱手持握偏移 |
| `projectile_file` | string | 关联弹头文件 |
| `projectile_result_class` | string | 弹头命中效果分类 |
| `projectile_result_kill_probability` | float | 击杀概率 |
| `projectile_result_kill_decay_start_time` | float | 击杀衰减开始 |
| `projectile_result_kill_decay_end_time` | float | 击杀衰减结束 |

### 子结构

**animations** — 动画列表
```json
[{ "key": "recoil", "ref": 27 },
 { "key": "reload", "animation_key": "reloading, aa-12" },
 { "key": "reload", "animation_key": "reloading, ar2, prone", "stance_key": "prone" }]
```

**sounds** — 音效
```json
[{ "key": "fire", "fileref": "aa-12_shot.wav", "pitch_variety": 0.05, "volume": 0.7, "class": "" }]
```

**stances** — 各姿态精度
```json
[{ "state_key": "standing", "accuracy": 0.85 },
 { "state_key": "crouching", "accuracy": 0.85 },
 { "state_key": "prone", "accuracy": 0.85 },
 { "state_key": "running", "accuracy": 0.6 },
 { "state_key": "crouch_moving", "accuracy": 0.6 },
 { "state_key": "prone_moving", "accuracy": 0.3 },
 { "state_key": "over_wall", "accuracy": 0.85 }]
```

**capacities** — 解锁条件
```json
[{ "value": 100, "source": "rank", "source_value": 0.0 }]
```

**commonness** — 刷新权重
```json
{ "value": 0.3, "can_respawn_with": true, "in_stock": true }
```

**modifiers** — 属性修饰器
```json
[{ "class": "damage", "value": 1.0 }]
```

### 完整示例

```json
{
  "key": "aa-12.weapon",
  "inherit_from": "base_primary_rare.weapon",
  "name": "AA-12",
  "class": 0,
  "magazine_size": 20,
  "retrigger_time": 0.25,
  "accuracy_factor": 0.9,
  "projectile_speed": 95.0,
  "projectiles_per_shot": 3,
  "can_shoot_standing": true,
  "suppressed": false,
  "inventory_price": 150.0,
  "inventory_encumbrance": 10.0,
  "hud_icon_filename": "hud_aa-12.png",
  "projectile_file": "bullet.projectile",
  "stances": [
    { "state_key": "standing", "accuracy": 0.85 },
    { "state_key": "prone", "accuracy": 0.85 },
    { "state_key": "running", "accuracy": 0.6 }
  ],
  "sounds": [
    { "key": "fire", "fileref": "aa-12_shot.wav", "volume": 0.7 }
  ],
  "type": "weapon"
}
```

---

## 3. projectile — 弹头/投掷物（287 条）

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 唯一标识 |
| `name` | string | 显示名（扁平化自 `@name`） |
| `inherit_from` | string | 继承关系 |
| `class` | string | 弹头分类（grenade / bullet 等） |
| `slot` | int | 槽位 |
| `radius` | float | 爆炸/效果半径 |
| `drop_count_factor_on_death` | float | 死亡掉落系数 |
| `result_class` | string | 命中后效果类型（扁平化） |
| `result_key` | string | 命中后产生的弹头 key |
| `tags` | array | 标签列表 |

### 完整示例

```json
{
  "key": "frag_grenade.projectile",
  "inherit_from": "grenade_base.projectile",
  "name": "Frag Grenade",
  "class": "grenade",
  "slot": 0,
  "radius": 18.0,
  "result_class": "spawn",
  "result_key": "frag_grenade_explosion.projectile",
  "tags": [{ "name": "explosive" }],
  "type": "projectile"
}
```

---

## 4. carry_item — 可持有物品（537 条）

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 唯一标识 |
| `name` | string | 显示名（扁平化自 `@name`） |
| `inherit_from` | string | 继承关系 |
| `slot` | int | 槽位类型 |
| `transform_on_consume` | string | 使用后变成什么物品 |
| `time_to_live_out_in_the_open` | float | 掉落野外存活时间 |
| `player_death_drop_owner_lock_time` | float | 死亡掉落锁定时间 |
| `hud_icon_filename` | string | 图标（扁平化） |
| `inventory_price` | float | 价格（扁平化） |
| `inventory_encumbrance` | float | 负重（扁平化） |
| `model_mesh` | string | 模型（扁平化） |
| `commonness_value` | float | 刷新权重（扁平化） |
| `commonness_in_stock` | int | 初始库存（扁平化） |
| `commonness_can_respawn_with` | int | 重生携带（扁平化） |

### 子结构

**capacities** — 解锁条件
```json
[{ "value": 100, "source": "rank", "source_value": 0.0 }]
```

**modifiers** — 属性修饰器
```json
[{ "class": "heal", "value": 25.0 },
 { "class": "heal", "value": 25.0, "input_character_state": "bleeding", "output_character_state": "healthy" }]
```

### 完整示例

```json
{
  "key": "health_pack.carry_item",
  "inherit_from": "base_consumable.carry_item",
  "name": "Health Pack",
  "slot": 3,
  "transform_on_consume": "used_bandage.carry_item",
  "hud_icon_filename": "hud_health_pack.png",
  "model_mesh": "health_pack.mesh",
  "inventory_price": 100.0,
  "inventory_encumbrance": 2.0,
  "modifiers": [{ "class": "heal", "value": 25.0 }],
  "type": "carry_item"
}
```

---

## 5. call — 无线电呼叫（31 条）

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 唯一标识 |
| `name` | string | 呼叫名称 |
| `initiation_comment1` | string | 发起台词 1 |
| `initiation_comment2` | string | 发起台词 2 |
| `acknowledge_comment` | string | 确认台词 |
| `launch_comment` | string | 执行台词 |
| `notify_metagame` | int | 是否通知全局 |
| `match_skinpack` | string | 皮肤包匹配 |

### 子结构

**rounds** — 部署波次（数组）
```json
[{
  "instances": 1,                   // 生成数量
  "instance_class": "vehicle",      // 生成物类型
  "instance_key": "humvee_gl.vehicle", // 生成物 key
  "instance_spread": [2.0, 0.0, 2.0],  // 散布范围 (vec3)
  "common_spread": [0.0, 0.0, 0.0],
  "launch_time": 10.0,              // 发射延迟
  "spawn_time": 17.0,               // 生成延迟
  "horizontal_offset_at_spawn": 0.0,
  "vertical_offset_at_spawn": 50.0,
  "initial_speed_to_target": 0.0,
  "avoid_objects": 1,
  "effects": [{ "class": "launch", "ref": "ShadowAirplaneFlyby", "shadow": 1 }],
  "sounds": [{ "class": "launch", "fileref": "plane_flyby.wav" }]
}]
```

**hud_icon** — 图标
```json
{ "filename": "hud_humveedrop.png" }
```

**capacities** — 解锁条件
```json
[{ "value": 0, "source": "rank", "source_value": 0.0 },
 { "value": 100, "source": "rank", "source_value": 0.4 }]
```

**inventory** — 价格负重
```json
{ "encumbrance": 0.0, "price": 400.0 }
```

### 完整示例

```json
{
  "key": "gps.call",
  "name": "Satellite spotting",
  "initiation_comment1": "Observation mission",
  "initiation_comment2": "Scanning area for strategic targets.",
  "acknowledge_comment": "Scanning area, open your maps, soldiers!",
  "notify_metagame": 1,
  "rounds": [{ "launch_time": 5.0, "spawn_time": 25.0 }],
  "hud_icon": { "filename": "hud_laptop_gps.png" },
  "capacities": [{ "value": 0, "source": "rank", "source_value": 0.0 }],
  "inventory": { "encumbrance": 0.0, "price": 1.0 },
  "type": "call"
}
```

---

## 6. achievement — 成就（21 条）

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 唯一标识（取自 `@name`） |
| `name` | string | 成就名 |
| `no_level_title` | string | 未解锁时的称号 |
| `include_in_alltime_stats` | int | 是否计入统计 |
| `external_file` | string | 外部引用文件（如果有） |

### 子结构

**levels** — 等级进度
```json
[{
  "steam_achievement_id": "ACH_DESTROYER_LVL1",
  "notification": { "image": "hud_...png", "sound": "achievement1.wav" },
  "rank": { "title": "Rookie destroyer", "image": "hud_...png" }
}]
```

**criteria_list** — 达成条件（数组，需同时满足）
```json
[{
  "class": "vehicle_destroy",
  "owner": "enemy",
  "stealth": 0,
  "description": "* destroy %target_count vehicles",
  "tag": "",
  "soldier_group": "",
  "vehicles": [
    { "tag": "apc" },
    { "key": "humvee.vehicle" }
  ],
  "level_thresholds": [
    { "value": 5 },   // LVL1 需要 5
    { "value": 10 },  // LVL2 需要 10
    { "value": 20 }   // LVL3 需要 20
  ]
}]
```

### 条件类型参考

| `class` 值 | 含义 |
|-----------|------|
| `vehicle_destroy` | 摧毁特定载具 |
| `kill` | 击杀 |
| `kill_stab` | 刀杀 |
| `kill_shoot` | 射杀 |
| `kill_blast` | 爆炸击杀 |
| `kill_drive_over` | 碾压击杀 |
| `death` | 死亡次数 |
| `vehicle_spot` | 发现目标 |
| `shot_fired` | 射击次数 |
| `unwound` | 治疗次数 |
| `custom_stat` | 自定义统计（看 `tag` 字段） |

### 完整示例

```json
{
  "key": "destroyer",
  "name": "destroyer",
  "no_level_title": "not much of a destroyer",
  "levels": [
    {
      "steam_achievement_id": "ACH_DESTROYER_LVL1",
      "notification": { "image": "hud_...bronze.png", "sound": "achievement1.wav" },
      "rank": { "title": "Rookie destroyer", "image": "hud_...bronze_pin.png" }
    },
    {
      "steam_achievement_id": "ACH_DESTROYER_LVL2",
      "rank": { "title": "Master destroyer", "image": "hud_...silver_pin.png" }
    },
    {
      "steam_achievement_id": "ACH_DESTROYER_LVL3",
      "rank": { "title": "Elite destroyer", "image": "hud_...gold_pin.png" }
    }
  ],
  "criteria_list": [{
    "class": "vehicle_destroy",
    "owner": "enemy",
    "description": "* destroy %target_count vehicles",
    "vehicles": [
      { "tag": "apc" }, { "key": "humvee.vehicle" },
      { "tag": "tank" }, { "key": "tank2.vehicle" }
    ],
    "level_thresholds": [{ "value": 5 }, { "value": 10 }, { "value": 20 }]
  }],
  "type": "achievement"
}
```

---

## 7. faction — 阵营（5 条）

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 唯一标识（取自 `@name`） |
| `name` | string | 阵营名 |
| `color` | vec3 | 阵营颜色 RGB，如 `[0.5, 0.35, 0.1]` |
| `firstnames_file` | string | 名字库文件 |
| `lastnames_file` | string | 姓氏库文件 |
| `chat_icon` | string | 聊天图标 |
| `chat_icon_supporter` | string | 支持者图标 |
| `chat_icon_commander` | string | 指挥官图标 |
| `campaign_icon` | string | 战役胜利图标 |
| `radio_queue_size` | int | 无线电队列大小 |
| `supporter_high_skinpack_xp` | float | 支持者皮肤包 XP 阈值 |

### 子结构

**ranks** — 军衔树（24 级）
```json
[
  { "xp": 0.0,   "name": "Private",             "hud_icon": { "filename": "hud_rank0.png" } },
  { "xp": 0.05,  "name": "Private 1st Class",    "hud_icon": { "filename": "hud_rank1.png" } },
  { "xp": 0.1,   "name": "Corporal",             "hud_icon": { "filename": "hud_rank2.png" } },
  { "xp": 0.2,   "name": "Sergeant",             "hud_icon": { "filename": "hud_rank3.png" } },
  ...
  { "xp": 1000,  "name": "President",            "hud_icon": { "filename": "hud_rank17.png" } }
]
```

**soldiers** — 士兵模板
```json
[{
  "name": "default",
  "spawn_score": 0.0,
  "squad_size_xp_cap": 0.0,
  "firstnames_file": "",
  "lastnames_file": "",
  "character_file": "default_male.character",
  "ai_file": "default.ai",
  "models": [                          // 模型引用
    { "file": "brown_default.models" },
    { "file": "common_bonus.models" }
  ],
  "resources": [                       // 资源引用
    { "file": "brown_primaries.resources" },
    { "file": "brown_default.resources" },
    {                                   // 或内联重写
      "clear_weapons": 0, "clear_vehicles": 0,
      "item_overrides": [{ "key": "camouflage_suit.carry_item", "enabled": 1 }]
    }
  ],
  "item_existence": [                  // 装备概率
    { "class": "weapon", "slot": 1, "probability": 0.4 },
    { "class": "carry_item", "slot": 1, "probability": 0.02 }
  ],
  "attribute_configs": [               // 属性配置
    {
      "class": "rp",
      "attributes": [{ "weight": 0.3, "min": 0.0, "max": 0.3 }]
    },
    {
      "class": "xp",
      "attributes": [{ "weight": 0.7, "min": 0.0, "max": 1.0 }]
    }
  ]
}]
```

### 完整示例

```json
{
  "key": "Brownpants",
  "name": "Brownpants",
  "color": [0.5, 0.35, 0.1],
  "firstnames_file": "russian_firstnames.txt",
  "lastnames_file": "russian_lastnames.txt",
  "chat_icon": "chat_icon_soldier_brown.png",
  "radio_queue_size": 3,
  "ranks": [
    { "xp": 0.0, "name": "Private", "hud_icon": {"filename":"hud_rank0.png"} },
    { "xp": 0.05, "name": "Private 1st Class", "hud_icon": {"filename":"hud_rank1.png"} },
    { "xp": 0.1, "name": "Corporal", "hud_icon": {"filename":"hud_rank2.png"} },
    { "xp": 0.2, "name": "Sergeant", "hud_icon": {"filename":"hud_rank3.png"} },
    { "xp": 0.3, "name": "Staff Sergeant", "hud_icon": {"filename":"hud_rank4.png"} },
    { "xp": 0.4, "name": "Staff Sergeant 1st Class", "hud_icon": {"filename":"hud_rank5.png"} },
    { "xp": 0.6, "name": "2nd Lieutenant", "hud_icon": {"filename":"hud_rank6.png"} },
    { "xp": 0.8, "name": "Lieutenant", "hud_icon": {"filename":"hud_rank7.png"} },
    { "xp": 1.0, "name": "Captain", "hud_icon": {"filename":"hud_rank8.png"} },
    { "xp": 1.2, "name": "Major", "hud_icon": {"filename":"hud_rank9.png"} },
    { "xp": 1.4, "name": "Lieutenant Colonel", "hud_icon": {"filename":"hud_rank10.png"} },
    { "xp": 2.0, "name": "Colonel", "hud_icon": {"filename":"hud_rank11.png"} },
    { "xp": 5.0, "name": "Brigadier General", "hud_icon": {"filename":"hud_rank12.png"} },
    { "xp": 10.0, "name": "Major General", "hud_icon": {"filename":"hud_rank13.png"} },
    { "xp": 20.0, "name": "Lieutenant General", "hud_icon": {"filename":"hud_rank14.png"} },
    { "xp": 50.0, "name": "General", "hud_icon": {"filename":"hud_rank15.png"} },
    { "xp": 100.0, "name": "General of the Army", "hud_icon": {"filename":"hud_rank16.png"} },
    { "xp": 200.0, "name": "General of the Army (II)", "hud_icon": {"filename":"hud_rank16_2.png"} },
    { "xp": 300.0, "name": "General of the Army (III)", "hud_icon": {"filename":"hud_rank16_3.png"} },
    { "xp": 400.0, "name": "General of the Army (IV)", "hud_icon": {"filename":"hud_rank16_4.png"} },
    { "xp": 500.0, "name": "General of the Army (V)", "hud_icon": {"filename":"hud_rank16_5.png"} },
    { "xp": 600.0, "name": "Field Marshal", "hud_icon": {"filename":"hud_rank18.png"} },
    { "xp": 800.0, "name": "Vice President", "hud_icon": {"filename":"hud_rank19.png"} },
    { "xp": 1000.0, "name": "President", "hud_icon": {"filename":"hud_rank17.png"} }
  ],
  "soldiers": [
    {
      "name": "default",
      "character_file": "default_male.character",
      "ai_file": "default.ai",
      "item_existence": [
        { "class": "weapon", "slot": 1, "probability": 0.4 },
        { "class": "carry_item", "slot": 1, "probability": 0.02 }
      ],
      "attribute_configs": [
        { "class": "rp", "attributes": [{ "weight": 0.3, "min": 0.0, "max": 0.3 }] },
        { "class": "xp", "attributes": [{ "weight": 0.7, "min": 0.0, "max": 1.0 }] }
      ]
    }
  ],
  "type": "faction"
}
```

---

## 数据类型的 JSON 表示

| 原始 XML 类型 | JSON 表示 | 出现位置 |
|--------------|----------|---------|
| 数值字符串 `"123.45"` | `number` (`float` / `int`) | transform: `to_float`, `to_int` |
| 布尔字符串 `"true"` / `"1"` | `boolean` | transform: `to_bool` |
| 向量 `"x y z"` | `[number, number, number]` | transform: `parse_vector3` |
| 向量 `"x y"` | `[number, number]` | transform: `parse_vector2` |
| 纯字符串 | `string` | 无 transform |
| 单次子元素 | `object` (嵌套 dict) | `is_array: false` |
| 多次子元素 | `array` | `is_array: true` |
| 无匹配 | 字段不存在或 `null` | — |

---

---

## 8. map_config — 地图配置（19 条）

地图通过 `map_config.xml` 文件定义，每个地图目录一个。地图的名称从目录名提取（`key_from_path`）。

### 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 地图标识（目录名，如 `map1`, `lobby`） |
| `locale` | string | 同 key |
| `min_factions` | int | 最少阵营数 |
| `max_factions` | int | 最多阵营数 |
| `custom_bases` | int | 自定义基地（0/1） |
| `scene.fog` | object | 场景雾效（offset, range） |
| `include_layers` | array | 场景图层引用 |

### 子结构

**factions** — 可用阵营
```json
[{ "file": "green.xml" }, { "file": "brown.xml" }]
```

**weapons / projectiles / vehicles / calls / carry_items** — 可用资源
```json
[{ "file": "all_weapons.xml" }]
```

**scene** — 场景配置
```json
{
  "fog": { "offset": 20.0, "range": 50.0 }
}
```

**include_layers** — 场景图层
```json
[{ "name": "layer1.default" }, { "name": "bases.default" }]
```

### 完整示例

```json
{
  "key": "map14",
  "locale": "map14",
  "min_factions": 2,
  "max_factions": 2,
  "custom_bases": 0,
  "scene": {
    "fog": { "offset": 20.0, "range": 50.0 }
  },
  "include_layers": [
    { "name": "layer1.default" },
    { "name": "bases.default" }
  ],
  "factions": [
    { "file": "green.xml" },
    { "file": "grey.xml" }
  ],
  "weapons":  [{ "file": "all_weapons.xml" }],
  "projectiles": [{ "file": "all_throwables.xml" }],
  "vehicles": [{ "file": "all_vehicles.xml" }],
  "calls": [{ "file": "all_calls.xml" }],
  "carry_items": [{ "file": "all_carry_items.xml" }],
  "type": "map_config"
}
```

### 地图目录相关资源（assets 目录）

每个地图除了 `map_config.xml` 外还有以下视觉资源：

| 文件 | 说明 |
|------|------|
| `map.png` | 缩略小地图 |
| `mapview_frame.png` | 地图视图边框 |
| `*_overlay_*.png` | 不同模式（TDM, KOTH）的覆盖层 |
| `objects.svg` | 地图对象布局 SVG |

这些资源通过 `assets/` 目录结构按地图名组织，路径为 `assets/maps/{map_name}/`。

---

## 9. map_legend — 地图图例

地图图例定义地图符号的含义。

```json
{
  "entries": [
    { "image": "mapview_spawnpoint.png", "text": "Spawn point", "scale": 0.5 },
    { "image": "mapview_attack_target.png", "text": "Main attack target", "scale": 0.8 },
    { "image": "mapview_attack_start.png", "text": "Main attack route", "use_faction_color": 1 }
  ],
  "type": "map_legend"
}
```

---

## 数据类型转换参考

| 原始 XML 类型 | JSON 表示 | 出现位置 |
|--------------|----------|---------|
| 数值字符串 `"123.45"` | `number` (`float` / `int`) | transform: `to_float`, `to_int` |
| 布尔字符串 `"true"` / `"1"` | `boolean` | transform: `to_bool` |
| 向量 `"x y z"` | `[number, number, number]` | transform: `parse_vector3` |
| 向量 `"x y"` | `[number, number]` | transform: `parse_vector2` |
| 纯字符串 | `string` | 无 transform |
| 单次子元素 | `object` (嵌套 dict) | `is_array: false` |
| 多次子元素 | `array` | `is_array: true` |
| 无匹配 | 字段不存在或 `null` | — |

---

## 跨实体关联参考

| 源 | 字段 | 关联到 | 说明 |
|----|------|--------|------|
| vehicle | `inherit_from` | vehicle | 继承链 |
| vehicle | `turrets[].weapon_key` | weapon | 炮塔武器 |
| vehicle | `events[].result.instance_key` | projectile | 事件产生的弹头 |
| vehicle | `character_slots[].weapon_slots[].allowed_weapon` | weapon | 乘员可用武器 |
| weapon | `inherit_from` | weapon | 继承链 |
| weapon | `projectile_file` | projectile | 发射的弹头 |
| projectile | `inherit_from` | projectile | 继承链 |
| projectile | `result_key` | projectile | 命中后产生的弹头 |
| carry_item | `inherit_from` | carry_item | 继承链 |
| carry_item | `transform_on_consume` | carry_item | 使用后变成 |
| call | `rounds[].instance_key` | vehicle / soldier | 部署的载具或士兵 |
| achievement | `criteria_list[].vehicles[].key` | vehicle | 目标载具 |
| faction | `soldiers[].resources[].item_overrides[].key` | carry_item / weapon | 装备覆盖 |
