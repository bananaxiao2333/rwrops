# Exchange System & Command System — 技术规格

## 一、Exchange 兑换系统

### 原理（来自 gift_item_delivery_rewarder.as）

兑换系统是「交付物→奖池随机抽奖」机制。

```
玩家交付 [input 物品] 
  → 触发 GiftItemDeliveryRandomRewarder
  → 3 秒后 doDelayedReward()
  → 遍历每个 prize_pool（奖池）
     → getRandomScoredResource(pool) 按权重随机抽一个
     → 给 player.m_amount 个该物品
  → 私聊玩家告知中奖结果
```

### 数据挂载

兑换数据不单独成类，而是挂在对应实体上：

**正向 — `exchange_prizes`**（此物能换到什么）

挂载在 `input` 物品实体上。例如 `carry_item.beach_ball.carry_item`：

```json
{
  "exchange_prizes": [{
    "category": "Setup Beach Ball",
    "prize_pools": [
      [  // pool 1: 第一个奖池，每次必抽一个
        {"key": "parasol_red.weapon",  "class": "weapon",     "score": 1.0, "count": 2},
        {"key": "parasol_blue.weapon", "class": "weapon",     "score": 1.0, "count": 2},
        {"key": "sunglasses.carry_item", ...},
        ...
      ],
      [  // pool 2: 第二个奖池
        {"key": "lighter.carry_item",   "class": "carry_item", "score": 10.0, "count": 1},
        {"key": "cooler_box_1.carry_item", ..., "score": 30.0, "count": 1},
        ...
      ]
    ]
  }]
}
```

**反向 — `exchange_sources`**（此物能从哪获得）

挂载在作为奖品的实体上。例如 `carry_item.cooler_box_1.carry_item`：

```json
{
  "exchange_sources": [
    {"category": "Setup Ticket Summer", "input": [{"key": "ticket_summer.carry_item", "class": "carry_item"}]},
    {"category": "Setup Beach Ball",    "input": [{"key": "beach_ball.carry_item", "class": "carry_item"}]}
  ]
}
```

### 奖池抽奖规则

| 字段 | 类型 | 说明 |
|------|------|------|
| `prize_pools` | `array[array[object]]` | 多个奖池，每个池独立抽奖 |
| 一个池 | `array[object]` | 每次从该池按权重抽 **1 个** 奖品 |
| `score` | number | 概率系数。运行时所有 score 归一化为概率总和 1.0 |
| `count` | int | 抽中后给多少个此物品 |
| `class` | string | 实体类型（weapon/carry_item/projectile） |
| `key` | string | 实体 key，用于查 result.json |

概率计算（来自 `normalizeScoredResources` + `getRandomScoredResource`）：

```
每个奖池中：
  sum = pool[0].score + pool[1].score + ...
  pool[i].概率 = pool[i].score / sum
  取随机数 p ∈ [0, 1)
  累加概率，第一个超过 p 的即为中奖项
```

### 兑换分类对照表

| 分类 | 输入物 | 奖池数 | 说明 |
|------|--------|--------|------|
| Ticket Summer | `ticket_summer.carry_item` | 2 | 夏季票券 |
| Ticket Halloween | `ticket_halloween.carry_item` | 1 | 万圣票券 |
| Ticket Easter | `ticket_easter.carry_item` | 1 | 复活节票券 |
| Ticket Boxes | `ticket_boxes.carry_item` | 1 | 通用票券 |
| Easter Basket | `easter_basket.carry_item` | 2 | 复活节篮子 |
| Easter Egg 1-5 | `easter_egg_N.carry_item` | 1 each | 复活节彩蛋 |
| Easter Egg Silver/Gold | `egg_silver/gold.carry_item` | 1 each | 稀有彩蛋 |
| Laptop | `laptop.carry_item` | 2 | 笔记本电脑 |
| Briefcase | `suitcase.carry_item` | 2 | 公文包 |
| Gift 1-3 | `gift_box_N.carry_item` | 2 each | 普通礼盒 |
| Halloween 1-3 | `halloween_box_N.carry_item` | 2 each | 万圣礼盒 |
| Xmas Box | `xmas_box.carry_item` | 2 | 圣诞礼盒 |
| Beach Ball | `beach_ball.carry_item` | 2 | 沙滩球 |
| Summer Box 1-3 | `cooler_box_N.carry_item` | 2 each | 夏季保温箱 |
| Community Gift 1-7 | `gift_box_community_N.carry_item` | 2 each | 社区礼盒 |
| Icecream | `icecream.carry_item` | 2 | 冰淇淋 |
| Enemy Weapon Unlocks | （代码生成列表） | - | 武器解锁 |

---

## 二、Command 命令系统

### 原理（来自 basic_command_handler.as）

服务器聊天命令系统，通过 `checkCommand(message, "命令名")` 匹配。

```
玩家在聊天框输入 /命令名 [参数]
  → handleChatEvent(XmlElement)
  → 管理员/主持人权限检查
  → 匹配 checkCommand
  → 执行对应的函数块
```

### 数据结构

```json
{
  "command": "0_win",
  "permission": "moderator",
  "description": "F0 胜利，F1/F2 失败",
  "effects": "设置比赛结果",
  "actions": [
    {"type": "send_xml", "xml": "<command class='set_match_status' lose='1' faction_id='1' />"},
    {"type": "send_xml", "xml": "<command class='set_match_status' lose='1' faction_id='2' />"},
    {"type": "send_xml", "xml": "<command class='set_match_status' win='1' faction_id='0' />"}
  ]
}
```

### 权限等级

| 等级 | 说明 | 检查代码 |
|------|------|---------|
| `moderator` | 主持人 | `isModerator(sender, senderId)` |
| `admin` | 管理员 | `isAdmin(sender, senderId)` |

主持人命令：`modtest`, `sidinfo`, `kick_id`, `kick`, `0_win`, `1_win`, `1_lose`, `1_own`
管理员命令：其他全部

### Action 类型对照

| type | 含义 | 示例数据 |
|------|------|---------|
| `send_xml` | 发送内联 XML 指令 | `"xml": "<command class='set_match_status' win='1' faction_id='0' />"` |
| `send_xml_element` | 发送动态构造的 XML 实体 | `"variable": "dict"` — 变量含 `class=chat`, `text=...` |
| `send_var` | 发送预构建的 XML 变量 | `"variable": "command"` |
| `chat_reply` | 私聊回复玩家 | `"message": "defensive ai set"` |
| `lookup_player_sid` | 遍历玩家列表，模糊匹配名称查 SID | — |
| `kick_player` | 按名称踢出，支持 kick_id 方式 | — |
| `game_result` | 设置胜负 | `"detail": "F0_WIN, F1_LOSE"` |
| `capture_base` | 占领所有基地 | `"faction": "1"` |
| `set_ai_behavior` | 调整 AI 行为 | `"base_defense": "1.0"` 防御；`"0.0"` 进攻 |
| `place_marker` | 放置地图标记 | `"text": "hello!"` |
| `broadcast_message` | 全服广播聊天 | `"text": "test yourself!"` |
| `spawn` | 生成实体 | `"instance_key": "a10_12.resource", "class": "resource"` |
| `destroy_vehicles` | 摧毁全部指定载具 | `"key": "humvee.vehicle"` |
| `destroy_all_enemy_vehicles` | 摧毁敌方全部指定载具 | `"key": "humvee.vehicle"` |
| `fill_inventory` | 填满背包（全部阵营全部物品） | — |
| `update_inventory_cmd` | 更新背包内容 | — |

### 命令清单（部分示例）

| 命令 | 权限 | 行为 |
|------|------|------|
| `modtest` | moderator | 私聊回复 "mod or admin" |
| `sidinfo <name>` | moderator | 遍历玩家列表，匹配名称返回 SID |
| `kick_id` / `kick` | moderator | 踢出玩家，支持 SID 或名称 |
| `0_win` | moderator | F0 胜利，F1+F2 失败 |
| `1_win` | moderator | F1 胜利，F0+F2 失败 |
| `1_lose` | moderator | F1 失败 |
| `1_own` | moderator | 所有基地占领给 F1 |
| `test2` | admin | 在地图坐标 (512,0,512) 放蓝色标记 "hello!" |
| `test` | admin | 全服广播 "test yourself!" |
| `defend` | admin | 双方 AI 改为纯防御 |
| `0_attack` / `1_attack` | admin | 指定方 AI 改为纯进攻 |
| `0_noattack` / `1_noattack` | admin | 指定方 AI 不进攻 |
| `0_vehicle` / `1_vehicle` | admin | 生成坦克 |
| `inc_friendly_capacity` | admin | 增加友方容量 |
| `inc_enemy_capacity` | admin | 增加敌方容量 |
| `swap_players` | admin | 交换阵营 |
| `endround` | admin | 结束当前回合 |
| `items` | admin | 全部武器物品加入背包 |
| `z_plane` | admin | 生成飞机 |
| `0_rp` / `1_rp` / `2_rp` | admin | 给阵营/玩家加 RP |
| `gift1` / `gift2` / `gift3` | admin | 触发对应礼包兑换事件 |
| `community_gift1` ~ `community_gift7` | admin | 触发社区礼盒 |
| `halloween1` / `2` / `3` | admin | 触发万圣礼盒 |
| `xmas` / `xmas_delivery` | admin | 触发圣诞礼盒 |
| `summer` / `summer_gift1~3` | admin | 触发夏日活动 |
| `beach` | admin | 触发沙滩球活动 |
| `easter1~3` / `tck_summer` / `tck_halloween` / `tck_easter` / `tck_boxes` | admin | 触发对应票券/复活节活动 |
| `armory` | admin | 触发军械库解锁交付 |
