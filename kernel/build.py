#!/usr/bin/env python3
"""构建入口：读配置 → 校验 → 生成三类静态出口。

零依赖，仅标准库。用法：

    python3 kernel/build.py [--root <repo>]

退出码：0 成功；1 数据或配置有错；2 环境问题（缺文件等）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import schema  # 同目录

# 不设 generated_at：它记的是构建时间而非数据更新时间，且会让
# 数据未变的构建也产生 git diff，破坏字节级幂等。需要新鲜度时看 git 历史。
ID_FORMAT = "<前缀>-<6位作品号>-<2位系列号>"
GROUP_KEY_RULE = "按 '-' 分割 id 取前两段，再用 '-' 连接"


# ---------------------------------------------------------------- 工具

def load_json(p: Path):
    # utf-8-sig：容忍 Windows 记事本保存时写入的 BOM，
    # 否则首字符会变成 \ufeff 导致 JSON 解析失败，且报错信息难以理解。
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def line_dump(obj) -> str:
    """紧凑 JSONL 行：无多余空格、保留中文原样。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def work_key(wid: str) -> str:
    """分组键：按 '-' 分割取前两段。

    不使用字符偏移——前缀不定长，任何写死的偏移量都会在改名后静默算错。
    """
    return "-".join(wid.split("-")[:2])


def unsafe_rel(rel) -> bool:
    """判断 plugin.json 里的相对路径是否可能逃出插件目录。

    同时按 Windows 与 POSIX 两种分隔符切分，因为仓库可能在两个平台上被编辑；
    只信任 pathlib 的解析会在跨平台时漏掉 `..\\..\\x` 这类写法。
    """
    if not isinstance(rel, str) or not rel:
        return True
    if rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
        return True
    return ".." in re.split(r"[\\/]", rel)


def build_index(rec: dict) -> dict:
    """索引行：只含检索字段 + 区分字段。"""
    idx: dict = {
        "id": rec["id"],
        "titles": [t["value"] for t in rec["titles"]],
    }
    # creators 展开 name 与 aliases，保持出现顺序并去重
    creators: list[str] = []
    seen: set[str] = set()
    for c in rec["creators"]:
        for n in (c["name"], *c.get("aliases", [])):
            if n not in seen:
                seen.add(n)
                creators.append(n)
    idx["creators"] = creators
    idx["tags"] = rec["tags"]
    if rec.get("variant"):
        idx["variant"] = rec["variant"]
    if rec.get("part"):
        idx["part"] = rec["part"]
    return idx


def normalize_work(rec: dict) -> dict:
    """按固定键序重排，省略 null，保证输出可复现。"""
    return {k: rec[k] for k in schema.WORK_KEY_ORDER
            if k in rec and rec[k] is not None}


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    root = Path(args.root).resolve()

    # ---- 读配置
    cfg_path = root / "config" / "deployment.json"
    if not cfg_path.is_file():
        print(f"[FAIL] 缺少配置文件 {cfg_path}")
        return 2
    try:
        cfg = load_json(cfg_path)
    except Exception as ex:
        print(f"[FAIL] config/deployment.json 解析失败：{ex}")
        return 2
    if not isinstance(cfg, dict) or not isinstance(cfg.get("plugins"), list):
        print('[FAIL] config/deployment.json 必须形如 {"plugins": ["manga"]}')
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    plugins: list[dict] = []
    used_prefix: dict[str, str] = {}
    seen_plugin_ids: set[str] = set()

    # ---- 校验每个插件
    for pid in cfg["plugins"]:
        if not isinstance(pid, str):
            errors.append(f"config: plugins 列表含非字符串项 {pid!r}")
            continue
        if pid in seen_plugin_ids:
            # 先判重复：否则会继续走到前缀冲突，报出「manga 与 manga 冲突」
            # 这种看不出真因的信息。
            errors.append(f"config: 插件 id 重复 {pid!r}（V14）")
            continue
        seen_plugin_ids.add(pid)
        if not schema.PLUGIN_ID_RE.match(pid):
            errors.append(
                f"config: 插件 id 非法 {pid!r}，必须匹配 "
                f"^[a-z][a-z0-9-]{{1,31}}$（V14）")
            continue
        pdir = root / "plugins" / pid
        if not pdir.is_dir():
            errors.append(f"插件目录不存在：plugins/{pid}（V13）")
            continue
        pj_path = pdir / "plugin.json"
        if not pj_path.is_file():
            errors.append(f"plugins/{pid}: 缺少 plugin.json")
            continue
        try:
            pj = load_json(pj_path)
        except Exception as ex:
            errors.append(f"plugins/{pid}/plugin.json 解析失败：{ex}")
            continue

        for m in schema.validate_plugin(pj, where=f"plugins/{pid}"):
            errors.append(m + "（V1/V2）")

        if isinstance(pj, dict) and isinstance(pj.get("id"), str) and pj["id"] != pid:
            errors.append(f"plugins/{pid}: plugin.json 的 id 为 {pj['id']!r}，与目录名不符")

        prefix = pj.get("record_prefix") if isinstance(pj, dict) else None
        if isinstance(prefix, str):
            if prefix in used_prefix:
                errors.append(
                    f"record_prefix 冲突：{prefix!r} 同时被 "
                    f"{used_prefix[prefix]} 与 {pid} 使用（V3）")
            else:
                used_prefix[prefix] = pid

        if isinstance(pj, dict):
            base = pdir.resolve()
            data_path = None
            for field in ("data", "schema"):
                rel = pj.get(field)
                if unsafe_rel(rel):
                    errors.append(
                        f"plugins/{pid}: `{field}` 必须为插件目录内的相对路径，"
                        f"实际 {rel!r}（V15）")
                    continue
                rp = (base / rel).resolve()
                try:
                    rp.relative_to(base)
                except ValueError:
                    errors.append(
                        f"plugins/{pid}: `{field}` 解析后越出插件目录：{rel!r}（V15）")
                    continue
                if field == "data":
                    data_path = rp
                elif not rp.is_file():
                    errors.append(
                        f"plugins/{pid}: `schema` 指向的文件不存在：{rel!r}（V15）")

            plugins.append({
                "id": pid,
                "name": pj.get("name"),
                "version": pj.get("version"),
                "prefix": prefix,
                "data": pj.get("data"),
                "data_path": data_path,
            })

    # ---- 读数据并校验
    results: list[tuple[dict, list[dict]]] = []
    for p in plugins:
        if not isinstance(p["prefix"], str):
            continue  # 前缀无效已记录错误，跳过数据校验
        dp = p["data_path"]
        if dp is None:
            continue  # 路径非法已记录错误
        if not dp.is_file():
            errors.append(f"plugins/{p['id']}: 数据文件不存在 {p['data']}")
            continue

        recs: list[dict] = []
        first_seen: dict[str, int] = {}
        with open(dp, encoding="utf-8-sig") as f:
            for lineno, raw in enumerate(f, 1):
                text = raw.strip()
                # DECISION: 空行跳过，容忍文件末尾换行与手工排版空行
                if not text:
                    continue
                try:
                    rec = json.loads(text)
                except json.JSONDecodeError as ex:
                    errors.append(f"plugins/{p['id']} 第 {lineno} 行: 非法 JSON（{ex.msg}）（V4）")
                    continue

                for m in schema.validate_work(rec, p["prefix"]):
                    errors.append(f"plugins/{p['id']} 第 {lineno} 行: {m}")
                for w in schema.warn_work(rec):
                    warnings.append(f"plugins/{p['id']} 第 {lineno} 行: {w}")

                if isinstance(rec, dict) and isinstance(rec.get("id"), str):
                    wid = rec["id"]
                    if wid in first_seen:
                        errors.append(
                            f"plugins/{p['id']} 第 {lineno} 行: id 重复 {wid!r}"
                            f"（首次出现于第 {first_seen[wid]} 行）（V6）")
                    else:
                        first_seen[wid] = lineno
                        recs.append(rec)
                elif isinstance(rec, dict):
                    errors.append(f"plugins/{p['id']} 第 {lineno} 行: 缺少可用 id，无法排序")

        recs.sort(key=lambda r: r["id"])
        results.append((p, recs))

    # ---- 有错则整体失败，不动 generated/
    if errors:
        print(f"[FAIL] 共 {len(errors)} 处错误，构建中止，generated/ 保持不变：")
        for m in errors:
            print(f"  - {m}")
        return 1

    # ---- 写临时目录，全部成功后原子替换
    tmp = root / ".generated.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    cap_plugins = []
    for p, recs in results:
        outdir = tmp / "plugins" / p["id"]
        outdir.mkdir(parents=True)

        with open(outdir / "index.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for r in recs:
                f.write(line_dump(build_index(r)) + "\n")

        with open(outdir / "works.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for r in recs:
                f.write(line_dump(normalize_work(r)) + "\n")

        cap_plugins.append({
            "id": p["id"],
            "name": p["name"],
            "version": p["version"],
            "record_prefix": p["prefix"],
            "count": len(recs),
            "work_count": len({work_key(r["id"]) for r in recs}),
            "files": {
                "index": f"plugins/{p['id']}/index.jsonl",
                "works": f"plugins/{p['id']}/works.jsonl",
            },
            "searchable": {
                "titles": "contains",
                "creators": "contains",
                "tags": "exact",
            },
        })

    caps = {
        "api_version": "1.0",
        "id_format": ID_FORMAT,
        "group_key_rule": GROUP_KEY_RULE,
        "defaults": {"part": schema.DEFAULT_PART},
        "plugins": cap_plugins,
    }
    with open(tmp / "capabilities.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(caps, f, ensure_ascii=False, indent=2)
        f.write("\n")

    gen = root / "generated"
    if gen.exists():
        shutil.rmtree(gen)
    os.replace(tmp, gen)

    total = sum(c["count"] for c in cap_plugins)
    print(f"[OK] 构建完成：{len(cap_plugins)} 个插件，{total} 条记录")
    for c in cap_plugins:
        print(f"  - {c['id']}: count={c['count']} work_count={c['work_count']}")
    if warnings:
        print(f"\n[WARN] {len(warnings)} 条建议性提示（不影响构建结果）：", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
