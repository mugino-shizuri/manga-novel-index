"""字段约束的唯一真相源（对应规格 v1.8 的 V1–V13）。

约定：本文件是约束的可执行形态，`插件系统与静态出口规格.md` 是它的说明。
两者冲突时以本文件为准，并回头修文档。

凡文档未明说、由实现作出选择的地方，一律用 DECISION 标注，
便于回看"这个决定是谁定的、依据是什么"。
"""

from __future__ import annotations

import datetime as _dt
import re

# ---------------------------------------------------------------- 枚举

TITLE_TYPES = ("ja", "ja_romaji", "zh", "zh_alias", "en")
STATUS_VALUES = ("连载中", "已完结", "休载", "腰斩")
SOURCE_TYPES = ("aggregator", "official", "other")
CAPABILITIES = ("work.read", "work.list")

# part 是唯一「缺失即等于某值」的字段：不写 part 表示正篇。
# 这个默认值必须由 capabilities.json 声明出去，否则消费方读到没有 part 的
# 正篇记录时，无法区分「这是正篇」还是「归属未填」，筛选会静默漏数据。
DEFAULT_PART = "正篇"

# 推荐值：不强制，偏离时给建议性警告（不影响构建）
RECOMMENDED_ROLES = ("author", "original", "art", "illustration",
                     "character_design", "director", "writer")
RECOMMENDED_VARIANTS = ("原作版", "重制版", "单行本", "完全版", "新装版",
                        "爱藏版", "文库版")
RECOMMENDED_PARTS = ("正篇", "番外", "特典", "外传", "短篇集")

# ---------------------------------------------------------------- 正则

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
PREFIX_RE = re.compile(r"^[a-z][a-z0-9]{2,15}$")   # 字符类不含 '-'
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# ---------------------------------------------------------------- 字段集合

WORK_FIELDS = frozenset({
    "id", "titles", "creators", "status", "variant", "part",
    "progress", "tags", "synopsis", "started", "ended", "sources", "created",
})
PLUGIN_FIELDS = frozenset({
    "id", "name", "version", "plugin_api", "record_prefix",
    "data", "schema", "capabilities",
})
WORK_REQUIRED = ("id", "titles", "creators", "progress", "tags", "synopsis",
                 "sources", "created")

# 索引与 works.jsonl 的固定键序，保证输出可复现
WORK_KEY_ORDER = ("id", "titles", "creators", "status", "variant", "part",
                  "progress", "tags", "synopsis", "started", "ended",
                  "sources", "created")


def id_pattern(prefix: str) -> re.Pattern:
    """按字面量拼正则。

    DECISION: 不用 `^[a-z]{N}-...`。前缀长度不定，任何固定长度模式都会
    在改动后静默放行或误拒，与规格 v1.8 规则 3 直接冲突。
    """
    return re.compile(rf"^{re.escape(prefix)}-\d{{6}}-\d{{2}}$")


# ---------------------------------------------------------------- 基础类型

def _is_str(v) -> bool:
    return isinstance(v, str)


def _blank_edges(s: str) -> bool:
    """首尾存在空白。DECISION: 首尾空白一律视为错误，不做静默 trim。

    trim 会让 'ひまてん! ' 与 'ひまてん!' 看起来相同，掩盖录入时的多余空格；
    直接拒绝可以把问题暴露在录入阶段。
    """
    return s != s.strip()


def _posint(v) -> bool:
    """DECISION: bool 是 int 的子类，必须显式排除，否则 true 会被当成 1。"""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _date_ok(s, allow_short: bool = True) -> bool:
    """YYYY / YYYY-MM / YYYY-MM-DD。

    DECISION: YYYY 取 1000–9999；YYYY-MM 校验月份 01–12；
    YYYY-MM-DD 用 date.fromisoformat 校验日期真实存在（拒绝 2026-02-30）。
    DECISION: 不校验是否晚于今天——会让构建依赖系统时钟，破坏可复现性。
    """
    if not _is_str(s):
        return False
    if re.fullmatch(r"\d{4}", s):
        return allow_short and 1000 <= int(s) <= 9999
    if re.fullmatch(r"\d{4}-\d{2}", s):
        if not allow_short:
            return False
        y, m = s.split("-")
        return 1000 <= int(y) <= 9999 and 1 <= int(m) <= 12
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            _dt.date.fromisoformat(s)
        except ValueError:
            return False
        return True
    return False


# ---------------------------------------------------------------- 作品记录

def validate_work(rec, prefix: str) -> list[str]:
    """校验一条作品记录，返回错误消息列表（空列表表示通过）。"""
    errs: list[str] = []

    def err(msg: str) -> None:
        errs.append(msg)

    if not isinstance(rec, dict):
        return ["记录不是 JSON 对象"]

    # DECISION: 未知字段直接拒绝，不忽略。
    # 拼错字段名（creater/creators）若被忽略，数据会静默丢失而看不出问题。
    unknown = set(rec) - WORK_FIELDS
    if unknown:
        err(f"存在未知字段 {sorted(unknown)}")

    for f in WORK_REQUIRED:
        if f not in rec:
            err(f"缺少必填字段 `{f}`")

    # ---- id
    wid = rec.get("id")
    if isinstance(wid, str):
        if not id_pattern(prefix).match(wid):
            err(f"`id` 格式不符：期望 {prefix}-######-##，实际 {wid!r}")
        else:
            work_no, series_no = wid.split("-")[1], wid.split("-")[2]
            if work_no == "000000":
                err("作品号为 `000000`，编号须从 000001 起")
            if series_no == "00":
                err("系列号为 `00`，编号须从 01 起")
    elif "id" in rec:
        err("`id` 必须为字符串")

    # ---- titles
    ts = rec.get("titles")
    if isinstance(ts, list):
        if not ts:
            err("`titles` 不能为空数组")
        seen: set[str] = set()
        for i, t in enumerate(ts):
            if not isinstance(t, dict):
                err(f"`titles[{i}]` 不是对象")
                continue
            extra = set(t) - {"type", "value"}
            if extra:
                err(f"`titles[{i}]` 存在未知字段 {sorted(extra)}")
            ty, va = t.get("type"), t.get("value")
            if ty not in TITLE_TYPES:
                err(f"`titles[{i}].type` 非法：{ty!r}，允许 {list(TITLE_TYPES)}")
            if not isinstance(va, str) or not va.strip():
                err(f"`titles[{i}].value` 为空")
            elif _blank_edges(va):
                err(f"`titles[{i}].value` 含首尾空白：{va!r}")
            elif va in seen:
                err(f"`titles[{i}].value` 重复：{va!r}")
            else:
                seen.add(va)
    elif "titles" in rec:
        err("`titles` 必须为数组")

    # ---- creators
    cs = rec.get("creators")
    if isinstance(cs, list):
        if not cs:
            err("`creators` 不能为空数组")
        for i, c in enumerate(cs):
            if not isinstance(c, dict):
                err(f"`creators[{i}]` 不是对象")
                continue
            extra = set(c) - {"role", "name", "aliases"}
            if extra:
                err(f"`creators[{i}]` 存在未知字段 {sorted(extra)}")
            role, name = c.get("role"), c.get("name")
            if not isinstance(role, str) or not role.strip():
                err(f"`creators[{i}].role` 为空")
            if not isinstance(name, str) or not name.strip():
                err(f"`creators[{i}].name` 为空")
            elif _blank_edges(name):
                err(f"`creators[{i}].name` 含首尾空白：{name!r}")
            al = c.get("aliases")
            if al is not None:
                if not isinstance(al, list) or not al:
                    err(f"`creators[{i}].aliases` 必须为非空数组或省略")
                else:
                    aseen: set[str] = set()
                    for j, a in enumerate(al):
                        if not isinstance(a, str) or not a.strip():
                            err(f"`creators[{i}].aliases[{j}]` 为空")
                        elif _blank_edges(a):
                            err(f"`creators[{i}].aliases[{j}]` 含首尾空白：{a!r}")
                        elif a == name:
                            # DECISION: 别名与 name 相同属冗余，拒绝以逼出真实差异写法
                            err(f"`creators[{i}].aliases[{j}]` 与 name 相同：{a!r}")
                        elif a in aseen:
                            err(f"`creators[{i}].aliases[{j}]` 重复：{a!r}")
                        else:
                            aseen.add(a)
    elif "creators" in rec:
        err("`creators` 必须为数组")

    # ---- status（可选，可为 null）
    if "status" in rec and rec["status"] is not None:
        if rec["status"] not in STATUS_VALUES:
            err(f"`status` 非法：{rec['status']!r}，允许 {list(STATUS_VALUES)} 或 null")

    # ---- variant / part（可选，出现则必须是非空字符串）
    for f in ("variant", "part"):
        if f in rec and rec[f] is not None:
            v = rec[f]
            if not isinstance(v, str) or not v.strip():
                err(f"`{f}` 必须为非空字符串或省略")
            elif _blank_edges(v):
                err(f"`{f}` 含首尾空白：{v!r}")

    # ---- progress
    pg = rec.get("progress")
    if isinstance(pg, dict):
        extra = set(pg) - {"chapter", "volume"}
        if extra:
            err(f"`progress` 存在未知键 {sorted(extra)}")
        keys = [k for k in ("chapter", "volume") if k in pg]
        if not keys:
            err("`progress` 至少需要 `chapter` 或 `volume` 之一")
        for k in keys:
            if not _posint(pg[k]):
                err(f"`progress.{k}` 必须为正整数，实际 {pg[k]!r}")
    elif "progress" in rec:
        err("`progress` 必须为对象")

    # ---- tags
    tg = rec.get("tags")
    if isinstance(tg, list):
        tseen: set[str] = set()
        for i, v in enumerate(tg):
            if not isinstance(v, str) or not v.strip():
                err(f"`tags[{i}]` 为空")
            elif _blank_edges(v):
                err(f"`tags[{i}]` 含首尾空白：{v!r}")
            elif v in tseen:
                err(f"`tags[{i}]` 重复：{v!r}")
            else:
                tseen.add(v)
    elif "tags" in rec:
        err("`tags` 必须为数组")

    # ---- synopsis（允许空字符串）
    if "synopsis" in rec:
        if not isinstance(rec["synopsis"], str):
            err("`synopsis` 必须为字符串（可为空字符串）")

    # ---- started / ended
    for f in ("started", "ended"):
        if f in rec and rec[f] is not None:
            if not _date_ok(rec[f]):
                err(f"`{f}` 日期格式不符：{rec[f]!r}，允许 YYYY / YYYY-MM / YYYY-MM-DD")

    # ---- sources
    ss = rec.get("sources")
    if isinstance(ss, list):
        for i, s in enumerate(ss):
            if not isinstance(s, dict):
                err(f"`sources[{i}]` 不是对象")
                continue
            extra = set(s) - {"type", "url", "updated"}
            if extra:
                err(f"`sources[{i}]` 存在未知字段 {sorted(extra)}")
            if s.get("type") not in SOURCE_TYPES:
                err(f"`sources[{i}].type` 非法：{s.get('type')!r}，允许 {list(SOURCE_TYPES)}")
            u = s.get("url")
            if not isinstance(u, str) or not (u.startswith("http://") or u.startswith("https://")):
                err(f"`sources[{i}].url` 必须以 http:// 或 https:// 开头：{u!r}")
            if "updated" in s and s["updated"] is not None:
                if not _date_ok(s["updated"]):
                    err(f"`sources[{i}].updated` 日期格式不符：{s['updated']!r}")
    elif "sources" in rec:
        err("`sources` 必须为数组")

    # ---- created
    if "created" in rec and rec["created"] is not None:
        if not _date_ok(rec["created"], allow_short=False):
            err(f"`created` 必须为 YYYY-MM-DD：{rec['created']!r}")

    return errs


# ---------------------------------------------------------------- 插件描述

def validate_plugin(p, where: str = "") -> list[str]:
    errs: list[str] = []

    def err(msg: str) -> None:
        errs.append(f"{where}: {msg}" if where else msg)

    if not isinstance(p, dict):
        return [f"{where}: plugin.json 不是 JSON 对象" if where else "plugin.json 不是 JSON 对象"]

    unknown = set(p) - PLUGIN_FIELDS
    if unknown:
        err(f"存在未知字段 {sorted(unknown)}")
    for f in PLUGIN_FIELDS:
        if f not in p:
            err(f"缺少字段 `{f}`")

    pid = p.get("id")
    if isinstance(pid, str):
        if not PLUGIN_ID_RE.match(pid):
            err(f"`id` 不符 ^[a-z][a-z0-9-]{{1,31}}$：{pid!r}")
    elif "id" in p:
        err("`id` 必须为字符串")

    nm = p.get("name")
    if not isinstance(nm, str) or not nm.strip():
        err("`name` 必须为非空字符串")

    ver = p.get("version")
    if not isinstance(ver, str) or not SEMVER_RE.match(ver):
        err(f"`version` 必须为语义化版本 X.Y.Z：{ver!r}")

    if p.get("plugin_api") != "1.0":
        err(f"`plugin_api` 必须为 \"1.0\"，实际 {p.get('plugin_api')!r}")

    rp = p.get("record_prefix")
    if isinstance(rp, str):
        if not PREFIX_RE.match(rp):
            err(f"`record_prefix` 不符 ^[a-z][a-z0-9]{{2,15}}$：{rp!r}")
    elif "record_prefix" in p:
        err("`record_prefix` 必须为字符串")

    for f in ("data", "schema"):
        v = p.get(f)
        if not isinstance(v, str) or not v:
            err(f"`{f}` 必须为非空相对路径")

    caps = p.get("capabilities")
    if not isinstance(caps, list) or not caps:
        err("`capabilities` 必须为非空数组")
    else:
        if len(caps) != len(set(caps)):
            err("`capabilities` 存在重复项")
        if set(caps) != set(CAPABILITIES):
            err(f"`capabilities` 必须恰好为 {list(CAPABILITIES)}")

    return errs


# ---------------------------------------------------------------- 建议性警告

def warn_work(rec) -> list[str]:
    """非致命提示：字段合法但取值偏离推荐值。

    这些不阻断构建——variant/part/role 在规格中是自由文本，
    强制枚举会误伤真实存在的其他形态。但完全无声又会放任同义泛滥，
    所以在两者之间取「出声但不拦截」。
    """
    warns: list[str] = []
    if not isinstance(rec, dict):
        return warns

    cs = rec.get("creators")
    if isinstance(cs, list):
        for i, c in enumerate(cs):
            if not isinstance(c, dict):
                continue
            r = c.get("role")
            if isinstance(r, str) and r and r not in RECOMMENDED_ROLES:
                warns.append(
                    f"`creators[{i}].role` = {r!r} 不在推荐值内，"
                    f"建议改用 {list(RECOMMENDED_ROLES)} 之一")

    v = rec.get("variant")
    if isinstance(v, str) and v and v not in RECOMMENDED_VARIANTS:
        warns.append(f"`variant` = {v!r} 不在推荐值内，建议改用 "
                     f"{list(RECOMMENDED_VARIANTS)} 之一")

    p = rec.get("part")
    if isinstance(p, str) and p and p not in RECOMMENDED_PARTS:
        warns.append(f"`part` = {p!r} 不在推荐值内，建议改用 "
                     f"{list(RECOMMENDED_PARTS)} 之一")

    return warns
