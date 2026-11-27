# 漫画与轻小说索引库

一个**只供 AI 消费**的公开数据仓库。没有网页、没有人类界面、没有 API 服务，只有可直接读取的 JSONL 文件。

消费者读取 raw URL 即可使用；也可整库克隆到本地，自行部署查询。

> 本仓库的一切设计取舍都服从一条原则：**宁可构建失败，不可静默出错。**

---

## 0. 当前状态

| 项 | 值 |
|---|---|
| 契约版本 | `api_version` = `1.0` |
| 插件 | `manga`（漫画）3 条 / `light-novel`（轻小说）3 条 |
| 数据来源 | `plugins/*/data/works.jsonl`（唯一手写层） |
| 派生层 | `generated/`（构建产出，可随时删除重建，**已入库以便 raw 读取**） |

**仓库地址**：`mugino-shizuri/manga-novel-index`（已发布）。

---

## 1. 读取协议（三步）

不要把整个仓库读完。按下面的顺序，按需取用：

```text
第 1 步   读 capabilities.json      → 有哪些插件、各多少条、文件名与匹配语义
第 2 步   读 <插件>/index.jsonl     → 窄表，只含检索用的三个维度，用于筛选
第 3 步   读 <插件>/works.jsonl     → 完整记录，按第 2 步命中的 id 取详情
```

### raw URL 模板

```text
https://raw.githubusercontent.com/mugino-shizuri/manga-novel-index/main/generated/capabilities.json
https://raw.githubusercontent.com/mugino-shizuri/manga-novel-index/main/generated/plugins/manga/index.jsonl
https://raw.githubusercontent.com/mugino-shizuri/manga-novel-index/main/generated/plugins/manga/works.jsonl
https://raw.githubusercontent.com/mugino-shizuri/manga-novel-index/main/generated/plugins/light-novel/index.jsonl
https://raw.githubusercontent.com/mugino-shizuri/manga-novel-index/main/generated/plugins/light-novel/works.jsonl
```

`mugino-shizuri/manga-novel-index` 须替换为实际仓库；插件清单以 `capabilities.json` 为准，不要硬编码上面的列表。

### 为什么分两层

索引是窄表：一行只有 4–6 个键，几万条也就几 MB，可整份读入内存做匹配。
完整记录含长文本（`synopsis`），只在命中后才取。这样检索成本与数据总量无关。

---

## 2. `capabilities.json`

```json
{
  "api_version": "1.0",
  "id_format": "<前缀>-<6位作品号>-<2位系列号>",
  "group_key_rule": "按 '-' 分割 id 取前两段，再用 '-' 连接",
  "defaults": { "part": "正篇" },
  "plugins": [
    {
      "id": "manga",
      "name": "漫画",
      "version": "1.0.0",
      "record_prefix": "manga",
      "count": 3,
      "work_count": 2,
      "files": { "index": "plugins/manga/index.jsonl", "works": "plugins/manga/works.jsonl" },
      "searchable": { "titles": "contains", "creators": "contains", "tags": "exact" }
    }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `plugins[].id` | 插件 id，同时是目录名。**与 ID 前缀不是一回事** |
| `plugins[].record_prefix` | 该插件记录 ID 的字面前缀，如 `manga`、`novel` |
| `plugins[].count` | 记录数（含同作品的多条系列记录） |
| `plugins[].work_count` | 作品数（按分组键去重）。恒有 `count >= work_count` |
| `plugins[].files` | 相对仓库根的路径 |
| `plugins[].searchable` | 三个维度的匹配方式，见第 3 节 |
| `defaults.part` | **缺省语义，必须读**。见第 6.1 节 |
| `group_key_rule` | 如何从 `id` 得到「同一作品」的分组键 |

出口**不含时间戳或随机字段**。需要判断数据新鲜度时看 git 历史（`git log -1 -- generated/`），而不是文件里的某个值。

`id` 与 `record_prefix` 可能不同：轻小说插件的 `id` 是 `light-novel`，前缀是 `novel`。按 `plugins[].id` 拼路径，按 `record_prefix` 理解 ID。

---

## 3. 索引记录（`index.jsonl`）

一行一条，按 `id` 升序。字段：

| 字段 | 类型 | 必现 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 三段格式 `<前缀>-######-##` |
| `titles` | string[] | 是 | 全部名称压平，**已丢弃 type**。顺序沿用源数据（惯例为 原文名 → 罗马字 → 中文名 → 中文别名 → 英文名），**消费时不要依赖顺序**，按集合使用 |
| `creators` | string[] | 是 | 创作者名与别名**全部展开**，不区分角色 |
| `tags` | string[] | 是 | 标签 |
| `variant` | string | 否 | 仅当非空时出现，如 `重制版` |
| `part` | string | 否 | 仅当非空时出现，缺失时按 `defaults.part` 理解 |

示例：

```jsonl
{"id":"manga-000001-01","titles":["ひまてん!","Hima-Ten!","妃真与殿!","妃真與殿!"],"creators":["小野玄晖","小野玄暉"],"tags":["恋爱","校园"]}
{"id":"manga-000002-01","titles":["ワンパンマン","One-Punch Man","一拳超人","一击男"],"creators":["ONE","村田雄介"],"tags":["热血","战斗"],"variant":"重制版"}
{"id":"manga-000002-02","titles":["ワンパンマン","One-Punch Man","一拳超人","一击男"],"creators":["ONE"],"tags":["热血","战斗"],"variant":"原作版"}
```

注意第 2、3 行的 `titles` 完全相同——它们是同一作品的两个独立出版物，靠 `variant` 区分。**不要因为名称相同就合并它们。**

### 匹配语义（关键）

| 字段 | 方式 | 含义 |
|---|---|---|
| `titles` | `contains` | 对数组任一元素做子串包含 |
| `creators` | `contains` | 同上 |
| `tags` | `exact` | 数组元素**完全相等**，不做子串 |

**所有匹配都不做归一化**：大小写、全角/半角、简体/繁体、空格均按字节比较。调用方若需模糊匹配，自行归一化后再比对。

`creators` 已展开别名，所以 `小野玄暉`（繁体）能命中 `小野玄晖`（简体）那条记录——前提是录入时把两种写法都写进了 `aliases`。这是仓库侧唯一做过的"防空"处理，因为 `冢`/`塚` 这类字符差异无法靠算法兜底。

`tags` 为 `exact` 意味着搜 `奇幻` 不会命中 `奇幻冒险`。要么按完整标签搜，要么改用 `contains` 自行实现。

---

## 4. 按作品聚合

`id` 是三段：`<前缀>-<6位作品号>-<2位系列号>`。**作品号相同的记录属于同一部作品。**

```python
group_key = "-".join(rec["id"].split("-")[:2])   # 正确
# group_key = rec["id"][:11]                     # 错误，不要用固定偏移
```

前缀长度不固定，任何写死的字符数都会在插件改名后静默算错——把两个不同作品并成一组，且不报错。`capabilities.json` 只给规则，不给长度。

因为作品号定长 6 位、系列号定长 2 位，按 `id` 升序时同一作品的记录必然相邻，可以流式扫描。

示例：`manga-000002-01` 与 `manga-000002-02` 的 `group_key` 都是 `manga-000002`，即《一拳超人》的重制版与原作版。

---

## 5. 完整记录（`works.jsonl`）

一行一条，键序固定，值为 `null` 或缺失的可选字段一律省略。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 三段格式；文件内唯一；**永不复用** |
| `titles` | object[] | 是 | `{type, value}`，`type` ∈ `ja` / `ja_romaji` / `zh` / `zh_alias` / `en`；非空；值全局不重复 |
| `creators` | object[] | 是 | `{role, name, aliases?}`；`role` 见下；非空 |
| `progress` | object | 是 | `{chapter?, volume?}`，**至少一个**，值为 ≥1 的整数 |
| `tags` | string[] | 是 | 可为空数组；元素不重复 |
| `synopsis` | string | 是 | **可为空字符串**（未撰写 ≠ 缺失） |
| `sources` | object[] | 是 | `{type, url, updated?}`，**可为空数组**；`type` ∈ `aggregator` / `official` / `other`；`url` 须 http(s)；**首条为主源** |
| `created` | string | 是 | 记录创建日，`YYYY-MM-DD` |
| `status` | string\|null | 否 | `连载中` / `已完结` / `休载` / `腰斩` |
| `variant` | string | 否 | 出版形态，如 `重制版`、`单行本`、`完全版` |
| `part` | string | 否 | 内容归属，**缺失 = 正篇**（见 6.1） |
| `started` | string | 否 | 起始日，精度可为 `YYYY` / `YYYY-MM` / `YYYY-MM-DD` |
| `ended` | string | 否 | 结束日，同上 |

### `creators[].role` 推荐值

`author`（作者）· `original`（原作）· `art`（作画）· `illustration`（插画）· `character_design`（角色设计）· `director`（监督）· `writer`（脚本）

这是**推荐值而非枚举**：其他取值允许写入，构建只给警告不报错。因此判断角色时按字符串比对，不要假定集合封闭。

### 为什么 `progress` 的两个键都可选

`{chapter: 96, volume: 11}` 表示有话数也有卷数；`{volume: 33}` 表示只有卷（如轻小说）；`{chapter: 150}` 表示只有话（如网络连载）。**不能假定两者同时存在。**

---

## 6. 三个必知陷阱

### 6.1 `part` 缺失等于「正篇」

索引与 `works.jsonl` 中，正篇记录**不写** `part` 字段，外传才写 `"part":"外传"`。

因此筛选正篇时：

```python
if rec.get("part", DEFAULTS["part"]) == "正篇":   # 正确
if rec.get("part") == "正篇":                     # 错误，会漏掉全部正篇
```

`DEFAULTS["part"]` 取自 `capabilities.json` 的 `defaults.part`。不读这个声明，筛"只要正篇"会返回空集，**且不报错**。

### 6.2 简繁与异体字不可算法归一

`冢` 与 `塚` 是不同 Unicode 字符，互相包含匹配不命中；`与` / `與` 同理。

仓库的应对方式是把异体写法全部写进 `titles`（作为 `zh_alias`）和 `creators[].aliases`。**这是一条录入纪律，不是机器保证**——查不到某部作品的繁体写法时，该写法就不会命中。

### 6.3 同一作品的多条记录，名称可能完全相同

《一拳超人》重制版与原作版的 `titles` 一字不差，只能靠 `variant` 区分。同理《Re:Zero》正篇 / `Ex` 外传 / 短篇集是三条记录。

**判断"是否同一部作品"看 `group_key`，判断"是哪一本"看 `variant` 与 `part`，不要看名称。**

---

## 7. 本地使用

克隆后无需安装任何依赖（仅用 Python 标准库，3.11+）：

```bash
git clone <repo-url>
cd <repo>

python3 kernel/build.py           # 重新生成 generated/
python3 kernel/emit_contracts.py  # 从 schema.py 重新导出 contracts/
python3 tests/run_tests.py        # 30 项契约与对抗测试
```

构建行为：

- 校验失败 → 退出码 `1`，打印全部错误与行号，**`generated/` 保持上一版不变**
- 配置不可读 → 退出码 `2`
- 成功 → 退出码 `0`；建议性警告走 stderr，不影响退出码
- 输出**逐字节可复现**：键序固定、记录按 `id` 升序、无时间戳、无随机量——数据未变时连续构建的产物完全一致，`git status` 保持干净

构建是原子的：先写 `.generated.tmp/`，全部成功后才替换 `generated/`。中断不会留下半套文件。

CI（`.github/workflows/validate.yml`）在 push 与 PR 时执行同一套检查：构建 → 检查 `generated/` 无差异 → 检查 `contracts/` 无差异 → 跑 30 项测试；Python 3.11 / 3.12 / 3.13 / 3.14 四档并行。改了数据却忘记重建 `generated/`，会在 CI 里直接失败。

需要 SQL 查询时，自行把 JSONL 导入 SQLite（不入 Git）：

```python
import json, sqlite3

db = sqlite3.connect("/tmp/index.db")
db.execute("CREATE TABLE IF NOT EXISTS works (id TEXT PRIMARY KEY, body TEXT)")
for line in open("generated/plugins/manga/works.jsonl", encoding="utf-8"):
    rec = json.loads(line)
    db.execute("INSERT OR REPLACE INTO works VALUES (?, ?)", (rec["id"], line))
db.commit()
```

注意 SQLite 命令行工具的 `.import` 按分隔符切列，**不能直接导入 JSONL**；必须逐行解析，或先转 CSV。

---

## 8. 目录结构

```text
.
├── config/deployment.json          # 启用哪些插件（顺序即构建顺序）
├── kernel/
│   ├── schema.py                   # 字段约束的唯一真相源（V1–V15 的可执行形态）
│   ├── build.py                     # 构建器：校验 → 生成三类出口
│   └── emit_contracts.py            # 从 schema.py 导出 contracts/*.schema.json
├── contracts/
│   ├── work.schema.json            # 作品记录形状（生成物，勿手改）
│   └── plugin.schema.json          # plugin.json 形状（生成物，勿手改）
├── plugins/
│   ├── manga/
│   │   ├── plugin.json             # 插件声明（8 字段）
│   │   ├── schema.json             # 插件级字段扩展（当前为空）
│   │   └── data/works.jsonl        # ← 手写数据，唯一编辑入口
│   └── light-novel/
│       └── ...
├── generated/                       # 构建产出，可删可重建，已入库
│   ├── capabilities.json
│   └── plugins/<id>/{index,works}.jsonl
├── tests/run_tests.py
└── 插件系统与静态出口规格.md         # 契约全文（人类可读版）
```

`schema.py` 是约束的权威形态；规格文档是它的说明。**两者冲突时以 `schema.py` 为准，并回头修文档。**

---

## 9. 维护流程

```text
1. 用户提供线索（作品名 / 作者 / 链接）
2. AI 查证：至少 2 个独立权威信源交叉验证
3. 判定每个事实是「已落地」还是「预期/传闻」
   - 已落地 → 写入对应字段
   - 未确认 → 省略字段或留空，不猜
4. 编辑 plugins/<id>/data/works.jsonl（一行一条，不换行）
5. 运行 python3 kernel/build.py
6. 校验通过后提交 data/ 与 generated/
```

### 录入规则（机器会拦的）

- `id` 前缀必须与插件 `record_prefix` 逐字一致；作品号从 `000001` 起、系列号从 `01` 起；不复用
- 未知字段直接拒绝（拼错 `creaters` 不会静默丢弃，会构建失败）
- 字符串不得有首尾空白（不做 trim，直接报错）
- `titles[].value` 全局不重复；`creators[].aliases` 不得与 `name` 相同
- `created` 必须是完整日期 `YYYY-MM-DD`

### 录入规则（机器拦不住的）

| 项 | 后果 |
|---|---|
| `role`/`variant`/`part` 自由文本未归一 | `重制版` 与 `重製版` 会并存，仅 stderr 警告 |
| `sources` 顺序错误 | 首条应为主源，顺序不参与校验 |
| 事实填错但格式合法 | 静默入库 |
| 异体字写法遗漏 | 该写法查不到 |
| ID 删除后被复用 | 构建期无法检测，只能查 Git 历史 |

---

## 10. 已知限制

- **无分片**：单插件单文件；万条量级约 2 MB，届时再考虑按月/首字母拆分
- **无增量构建**：每次全量重建，当前规模下耗时可忽略
- **无服务端**：只有静态文件。需要搜索 API 时另行部署，直接消费 `generated/`
- **`plugins/*/schema.json` 尚未生效**：插件级字段扩展点已预留，当前两插件均为空，构建器暂不读取
- **`contracts/*.schema.json` 是生成物**：由 `kernel/emit_contracts.py` 从 `schema.py` 导出，只表达形状。跨字段语义（`id` 前缀须等于 `record_prefix`、作品号唯一、`part` 缺省为正篇）无法用 JSON Schema 表达，仍在 `schema.py` 与本文档中；CI 会校验两者同步，手改 contracts 会失败

---

## 11. 许可证

两者分离声明：

- **代码**（`kernel/`、`tests/`）：**MIT**，见 [`LICENSE`](LICENSE)
- **数据**（`plugins/*/data/`、`generated/`）：**CC0 1.0**，见 [`LICENSE-DATA`](LICENSE-DATA)

作品名称、作者、进度等属于事实性信息，不构成独创表达，因此数据部分采用最宽的 CC0，便于任意复用；代码保留 MIT 以明确免责。
