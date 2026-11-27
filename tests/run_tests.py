#!/usr/bin/env python3
"""验收与对抗测试。

每个用例在临时副本上运行，互不污染真实数据。
用法：python3 tests/run_tests.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
IGNORE = shutil.ignore_patterns(
    "generated", ".generated.tmp", ".git", ".codebuddy", "__pycache__",
    "works.jsonl")  # 本地正式数据不参与测试，测试一律从 works.example.jsonl 起

# 一条结构合法的基线记录，各用例在其上做单点破坏
BASE = {
    "id": "manga-900001-01",
    "titles": [{"type": "zh", "value": "测试作品"}],
    "creators": [{"role": "art", "name": "测试作者"}],
    "progress": {"chapter": 1},
    "tags": [],
    "synopsis": "",
    "sources": [],
    "created": "2026-11-24",
}


# ---------------------------------------------------------------- 工具

def fresh(tmp: str) -> Path:
    dst = Path(tmp) / "repo"
    shutil.copytree(REPO, dst, ignore=IGNORE)
    for d in (dst / "generated", dst / ".generated.tmp"):
        if d.exists():
            shutil.rmtree(d)
    return dst


def write_cfg(root: Path, ids) -> None:
    (root / "config" / "deployment.json").write_text(
        json.dumps({"plugins": ids}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def write_data(root: Path, plugin: str, recs) -> None:
    p = root / "plugins" / plugin / "data" / "works.jsonl"
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
        encoding="utf-8")


def run(root: Path):
    return subprocess.run(
        [PY, str(root / "kernel" / "build.py"), "--root", str(root)],
        capture_output=True, text=True)


def caps(root: Path) -> dict:
    return json.loads((root / "generated" / "capabilities.json").read_text(encoding="utf-8"))


def snapshot(root: Path) -> dict:
    """生成物快照，逐字节比较——不做任何字段剔除或归一化。

    出口刻意不含时间戳，因此连续构建的产物必须字节级一致。
    """
    g = root / "generated"
    out = {}
    if g.exists():
        for p in sorted(g.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(g))] = p.read_text(encoding="utf-8")
    return out


def expect_fail(root: Path, keyword: str):
    r = run(root)
    out = r.stdout + r.stderr
    if r.returncode == 0:
        return False, f"期望失败但构建成功\n{out}"
    if keyword not in out:
        return False, f"失败信息未包含 {keyword!r}\n{out}"
    return True, ""


def expect_ok(root: Path):
    r = run(root)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    return True, ""


# ---------------------------------------------------------------- 用例

def t_empty_config(root):
    write_cfg(root, [])
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    c = caps(root)
    files = [p.name for p in (root / "generated").rglob("*") if p.is_file()]
    if c["plugins"] != []:
        return False, f"plugins 非空：{c['plugins']}"
    if files != ["capabilities.json"]:
        return False, f"空配置下产出了多余文件：{files}"
    return True, ""


def t_only_manga(root):
    write_cfg(root, ["manga"])
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    c = caps(root)
    if [p["id"] for p in c["plugins"]] != ["manga"]:
        return False, f"plugins={c['plugins']}"
    if (root / "generated" / "plugins" / "light-novel").exists():
        return False, "未启用的插件仍产出目录"
    return True, ""


def t_real_data(root):
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    c = caps(root)
    got = {p["id"]: (p["count"], p["work_count"]) for p in c["plugins"]}
    want = {"manga": (3, 2), "light-novel": (3, 1)}
    if got != want:
        return False, f"count 不符：{got} != {want}"
    # 同作品系列必须相邻
    lines = (root / "generated/plugins/manga/index.jsonl").read_text(encoding="utf-8").splitlines()
    ids = [json.loads(x)["id"] for x in lines]
    if ids != ["manga-000001-01", "manga-000002-01", "manga-000002-02"]:
        return False, f"排序或相邻性不符：{ids}"
    return True, ""


def t_bad_prefix_in_id(root):
    rec = dict(BASE, id="mang-000001-01")
    write_data(root, "manga", [rec])
    return expect_fail(root, "id` 格式不符")


def t_two_segment_id(root):
    write_data(root, "manga", [dict(BASE, id="manga-000001")])
    return expect_fail(root, "id` 格式不符")


def t_empty_titles(root):
    write_data(root, "manga", [dict(BASE, titles=[])])
    return expect_fail(root, "titles` 不能为空")


def t_unknown_field(root):
    rec = dict(BASE)
    rec["creater"] = []
    write_data(root, "manga", [rec])
    return expect_fail(root, "未知字段")


def t_bad_date(root):
    write_data(root, "manga", [dict(BASE, started="2026-13-01")])
    return expect_fail(root, "日期格式不符")


def t_empty_progress(root):
    write_data(root, "manga", [dict(BASE, progress={})])
    return expect_fail(root, "progress` 至少需要")


def t_series_zero(root):
    write_data(root, "manga", [dict(BASE, id="manga-000001-00")])
    return expect_fail(root, "系列号为 `00`")


def t_work_zero(root):
    write_data(root, "manga", [dict(BASE, id="manga-000000-01")])
    return expect_fail(root, "作品号为 `000000`")


def t_duplicate_id(root):
    write_data(root, "manga", [BASE, dict(BASE)])
    return expect_fail(root, "id 重复")


def t_alias_equals_name(root):
    rec = dict(BASE)
    rec["creators"] = [{"role": "art", "name": "测试作者", "aliases": ["测试作者"]}]
    write_data(root, "manga", [rec])
    return expect_fail(root, "与 name 相同")


def t_prefix_conflict(root):
    p = root / "plugins" / "light-novel" / "plugin.json"
    pj = json.loads(p.read_text(encoding="utf-8"))
    pj["record_prefix"] = "manga"
    p.write_text(json.dumps(pj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return expect_fail(root, "record_prefix 冲突")


def t_prefix_with_dash(root):
    p = root / "plugins" / "manga" / "plugin.json"
    pj = json.loads(p.read_text(encoding="utf-8"))
    pj["record_prefix"] = "man-ga"
    p.write_text(json.dumps(pj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return expect_fail(root, "record_prefix` 不符")


def t_missing_plugin_dir(root):
    write_cfg(root, ["manga", "ghost"])
    return expect_fail(root, "插件目录不存在")


def t_bad_status(root):
    write_data(root, "manga", [dict(BASE, status="未知")])
    return expect_fail(root, "status` 非法")


def t_bad_title_type(root):
    write_data(root, "manga", [dict(BASE, titles=[{"type": "jp", "value": "x"}])])
    return expect_fail(root, "titles[0].type` 非法")


def t_bad_url(root):
    write_data(root, "manga", [dict(BASE, sources=[{"type": "official", "url": "ftp://x"}])])
    return expect_fail(root, "url` 必须以 http")


def t_short_created(root):
    write_data(root, "manga", [dict(BASE, created="2026")])
    return expect_fail(root, "created` 必须为 YYYY-MM-DD")


def t_bom_tolerated(root):
    """Windows 记事本存 UTF-8 会带 BOM，不应导致构建失败。"""
    p = root / "plugins" / "manga" / "data" / "works.jsonl"
    p.write_text("\ufeff" + json.dumps(BASE, ensure_ascii=False) + "\n", encoding="utf-8")
    return expect_ok(root)


def t_dup_plugin_id(root):
    write_cfg(root, ["manga", "manga"])
    return expect_fail(root, "插件 id 重复")


def t_bad_plugin_id(root):
    write_cfg(root, ["../etc"])
    return expect_fail(root, "插件 id 非法")


def t_data_path_escape(root):
    p = root / "plugins" / "manga" / "plugin.json"
    pj = json.loads(p.read_text(encoding="utf-8"))
    pj["data"] = "../../../tmp/leak.jsonl"
    p.write_text(json.dumps(pj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return expect_fail(root, "必须为插件目录内的相对路径")


def t_defaults_present(root):
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    d = caps(root).get("defaults", {})
    if d.get("part") != "正篇":
        return False, f"defaults 缺失或错误：{d!r}"
    return True, ""


def t_warn_unknown_role(root):
    """role 偏离推荐值应警告但不阻断构建。"""
    write_data(root, "manga", [dict(BASE, creators=[{"role": "作者", "name": "测试作者"}])])
    r = run(root)
    if r.returncode != 0:
        return False, "偏离推荐值不应导致构建失败\n" + r.stdout + r.stderr
    if "WARN" not in r.stderr or "role" not in r.stderr:
        return False, f"未输出 role 警告：{r.stderr!r}"
    return True, ""


def t_idempotent(root):
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    s1 = snapshot(root)
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    s2 = snapshot(root)
    if s1 != s2:
        diff = set(s1) ^ set(s2) or [k for k in s1 if s1[k] != s2.get(k)]
        return False, f"两次构建结果不一致：{diff}"
    return True, ""


def t_no_timestamp(root):
    """出口不得含时间戳字段——时间戳会破坏字节级幂等。"""
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    for path, text in snapshot(root).items():
        if '"generated_at"' in text or '"built_at"' in text or '"timestamp"' in text:
            return False, f"{path} 含时间戳字段"
    return True, ""


def t_example_fallback(root):
    """没有正式数据时必须回退 works.example.jsonl，并在输出里明确告知。"""
    p = root / "plugins" / "manga" / "data" / "works.jsonl"
    if p.exists():
        p.unlink()
    r = run(root)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    if "[SRC]" not in r.stdout:
        return False, "回退了示例数据却没有提示：\n" + r.stdout
    return True, ""


def t_contracts_in_sync(root):
    """contracts/ 必须是由 schema.py 导出的那一份，不能手改。

    schema.py 是唯一真相源；contracts/*.schema.json 只是给外部工具看的投影。
    两份并存必然漂移，所以每次构建前用 --check 逐字节比对。
    """
    r = subprocess.run(
        [PY, str(root / "kernel" / "emit_contracts.py"), "--root", str(root), "--check"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    return True, ""


def t_failure_keeps_previous(root):
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    before = snapshot(root)
    write_data(root, "manga", [dict(BASE, id="bad-id")])
    r = run(root)
    if r.returncode == 0:
        return False, "坏数据居然构建成功"
    after = snapshot(root)
    if before != after:
        return False, "构建失败后 generated/ 被改动，原子性被破坏"
    return True, ""


def t_caps_progress_semantics(root):
    """出口必须声明 progress 两键独立。

    缺这条声明，消费方会拿卷数推算话数、或把「话卷不相等」当成数据错误，
    两种都是静默错——所以声明缺失必须测试红，而不是等上线后被误用。
    """
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    c = caps(root)
    if c.get("api_version") != "1.1":
        return False, f"api_version 应为 1.1，实际 {c.get('api_version')!r}"
    ps = c.get("progress_semantics")
    if not isinstance(ps, dict):
        return False, "capabilities.json 缺少 progress_semantics 声明"
    if ps.get("independent") is not True:
        return False, f"independent 不为 true：{ps!r}"
    for k in ("chapter", "volume", "note"):
        v = ps.get(k)
        if not isinstance(v, str) or not v.strip():
            return False, f"progress_semantics.{k} 缺失或为空：{ps!r}"
    return True, ""


def t_progress_keys_independent(root):
    """chapter 单独、volume 单独、两者并存都必须合法。

    旧测试只覆盖了 chapter；轻小说常见的「只有卷」从未被显式验证过。
    """
    write_data(root, "manga", [
        dict(BASE, id="manga-900001-01", progress={"chapter": 96}),
        dict(BASE, id="manga-900002-01", progress={"volume": 11}),
        dict(BASE, id="manga-900003-01", progress={"chapter": 147, "volume": 15}),
    ])
    ok, msg = expect_ok(root)
    if not ok:
        return ok, msg
    lines = (root / "generated/plugins/manga/works.jsonl").read_text(
        encoding="utf-8").splitlines()
    got = [json.loads(x)["progress"] for x in lines]
    want = [{"chapter": 96}, {"volume": 11}, {"chapter": 147, "volume": 15}]
    if got != want:
        return False, f"progress 输出不符：{got} != {want}"
    return True, ""


def t_stats_line(root):
    """构建末尾必须打印可信度体检行，且不因体检项影响退出码。

    示例数据 6 条、sources 全为空数组——这正是「零来源记录可以存在，
    但不能悄悄存在」要暴露的情形。
    """
    r = run(root)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    lines = [l for l in r.stdout.splitlines() if l.startswith("[STAT]")]
    if not lines:
        return False, f"缺少 [STAT] 体检行\n{r.stdout}"
    if "6 条记录" not in lines[0]:
        return False, f"总数不符：{lines[0]}"
    if "无来源 6" not in lines[0]:
        return False, f"无来源条数不符：{lines[0]}"
    return True, ""


def t_stats_counts(root):
    """体检行的四个计数必须算对，且零来源/单源互斥。"""
    write_cfg(root, ["manga"])          # 只启用 manga，否则 light-novel 的示例数据会混进总数
    write_data(root, "manga", [
        dict(BASE, id="manga-900001-01", sources=[]),
        dict(BASE, id="manga-900002-01",
             sources=[{"type": "official", "url": "https://example.com/a"}]),
        dict(BASE, id="manga-900003-01", status="连载中",
             titles=[{"type": "ja", "value": "テスト"}, {"type": "zh", "value": "测试"}],
             sources=[{"type": "official", "url": "https://example.com/a"},
                      {"type": "aggregator", "url": "https://example.com/b"}]),
    ])
    r = run(root)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    stat = next((l for l in r.stdout.splitlines() if l.startswith("[STAT]")), "")
    want = {"无来源": 1, "单源": 1, "status 缺失": 2, "无 ja 标题": 2}
    for k, v in want.items():
        if f"{k} {v}" not in stat:
            return False, f"{k} 期望 {v}，实际行：{stat}"
    if "3 条记录" not in stat:
        return False, f"总数不符：{stat}"
    return True, ""


CASES = [
    ("验收1 空配置构建成功且无插件文件", t_empty_config),
    ("验收2 只启用 manga", t_only_manga),
    ("验收3/7 真实数据 count、work_count、相邻性", t_real_data),
    ("对抗42 id 前缀与插件不符", t_bad_prefix_in_id),
    ("对抗43 两段式 id", t_two_segment_id),
    ("对抗44 空 titles", t_empty_titles),
    ("对抗45 未知字段拼写错误", t_unknown_field),
    ("对抗46 非法日期 2026-13-01", t_bad_date),
    ("对抗47 progress 无键", t_empty_progress),
    ("对抗48 系列号 00", t_series_zero),
    ("对抗49 作品号 000000", t_work_zero),
    ("对抗50 id 重复", t_duplicate_id),
    ("对抗51 alias 与 name 相同", t_alias_equals_name),
    ("对抗52 两插件前缀冲突", t_prefix_conflict),
    ("对抗53 前缀含连字符", t_prefix_with_dash),
    ("对抗54 插件目录不存在", t_missing_plugin_dir),
    ("对抗55 status 非法枚举", t_bad_status),
    ("对抗56 titles.type 非法枚举", t_bad_title_type),
    ("对抗57 sources.url 非 http(s)", t_bad_url),
    ("对抗58 created 精度不足", t_short_created),
    ("健壮性 BOM 文件仍可构建", t_bom_tolerated),
    ("对抗59 插件 id 重复", t_dup_plugin_id),
    ("对抗60 插件 id 格式非法（路径穿越）", t_bad_plugin_id),
    ("对抗61 data 路径越出插件目录", t_data_path_escape),
    ("契约 part 默认值写入 capabilities", t_defaults_present),
    ("契约 progress 两键独立的声明存在", t_caps_progress_semantics),
    ("契约 progress 两键可独立缺失", t_progress_keys_independent),
    ("体检 构建末尾打印 [STAT] 行", t_stats_line),
    ("体检 [STAT] 四项计数正确", t_stats_counts),
    ("建议性警告 role 偏离推荐值不阻断", t_warn_unknown_role),
    ("验收6 幂等：连续构建一致", t_idempotent),
    ("数据源回退：无正式数据时用示例并提示", t_example_fallback),
    ("契约 contracts/ 与 schema.py 同步", t_contracts_in_sync),
    ("出口无时间戳字段", t_no_timestamp),
    ("验收4 失败不留残骸、原子替换", t_failure_keeps_previous),
]


def main() -> int:
    fails = 0
    for name, fn in CASES:
        with tempfile.TemporaryDirectory() as td:
            root = fresh(td)
            try:
                ok, msg = fn(root)
            except Exception as ex:  # noqa: BLE001
                ok, msg = False, f"用例抛出 {type(ex).__name__}: {ex}"
        print(("PASS  " if ok else "FAIL  ") + name)
        if not ok:
            fails += 1
            for line in msg.splitlines()[:12]:
                print("        " + line)
    total = len(CASES)
    print(f"\n{total - fails}/{total} 通过")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
