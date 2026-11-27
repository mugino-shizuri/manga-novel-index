#!/usr/bin/env python3
"""从 kernel/schema.py 生成 contracts/*.schema.json。

真相源始终是 schema.py，本脚本只是「导出」，不参与构建，也不被 build.py 引用。
JSON Schema 只能表达形状；跨字段语义无法表达，已写进各文件的 $comment，
仍以 schema.py 与 README 为准。

用法：

    python3 kernel/emit_contracts.py            # 生成/覆盖 contracts/
    python3 kernel/emit_contracts.py --check    # 只校验是否已同步（CI 用）

退出码：0 一致或已写出；1 使用 --check 时发现不一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import schema  # 同目录

# JSON Schema 表达不了真实日期，只能约束形状；语义校验在 schema.py
DATE_RX = r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$"
CREATED_RX = r"^\d{4}-\d{2}-\d{2}$"
URL_RX = r"^https?://"
ID_RX = r"^[a-z][a-z0-9]{2,15}-\d{6}-\d{2}$"

WORK_COMMENT = (
    "由 kernel/emit_contracts.py 从 kernel/schema.py 生成，请勿手改。"
    "JSON Schema 只描述形状；以下语义无法表达，仍在 schema.py 与 README 中定义："
    "(1) id 的前缀必须逐字等于所属插件 plugin.json 的 record_prefix，且插件间前缀不得重复；"
    "(2) 作品号在单个数据文件内唯一，删除后不得复用；"
    "(3) part 缺失表示正篇，缺省值以 capabilities.json 的 defaults.part 为准；"
    "(4) 同一作品的分组键由 id 按 '-' 分割取前两段得到，禁止用固定字符偏移；"
    "(5) 同一记录内 titles[].value 不得重复，creators[].aliases 不得与 name 相同。"
)

PLUGIN_COMMENT = (
    "由 kernel/emit_contracts.py 从 kernel/schema.py 生成，请勿手改。"
    "JSON Schema 只描述形状；record_prefix 必须全局唯一且一经发布不得更改"
    "（构建期由 V3 检查），这一条无法在本文件中表达。"
)


def work_schema() -> dict:
    """作品记录的 JSON Schema，属性顺序与 schema.WORK_KEY_ORDER 一致。"""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "contracts/work.schema.json",
        "title": "作品记录（plugins/<id>/data/works.jsonl 的一行）",
        "description": "所有内容插件共用的记录形状。插件 schema.json 只能收窄，不能新增与通用契约冲突的字段。",
        "$comment": WORK_COMMENT,
        "type": "object",
        "additionalProperties": False,
        "required": list(schema.WORK_REQUIRED),
        "properties": {
            "id": {
                "type": "string",
                "pattern": ID_RX,
                "description": "<前缀>-<6位作品号>-<2位系列号>；前缀由记录自身的插件决定",
            },
            "titles": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "value"],
                    "properties": {
                        "type": {"enum": list(schema.TITLE_TYPES)},
                        "value": {"type": "string", "minLength": 1},
                    },
                },
            },
            "creators": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["role", "name"],
                    "properties": {
                        "role": {
                            "type": "string",
                            "minLength": 1,
                            "description": "推荐值见 README 的 creators[].role 表；自由文本，偏离仅警告",
                        },
                        "name": {"type": "string", "minLength": 1},
                        "aliases": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                            "description": "繁简/日文汉字等异体写法，用于索引展开",
                        },
                    },
                },
            },
            "status": {"enum": [*schema.STATUS_VALUES, None]},
            "variant": {"type": "string", "minLength": 1},
            "part": {"type": "string", "minLength": 1},
            "progress": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chapter": {"type": "integer", "minimum": 1},
                    "volume": {"type": "integer", "minimum": 1},
                },
                "anyOf": [{"required": ["chapter"]}, {"required": ["volume"]}],
                "description": "chapter 与 volume 至少一个；不能假定两者同时存在",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
            "synopsis": {"type": "string", "description": "可为空字符串；空字符串表示未撰写"},
            "started": {"type": "string", "pattern": DATE_RX},
            "ended": {"type": "string", "pattern": DATE_RX},
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "url"],
                    "properties": {
                        "type": {"enum": list(schema.SOURCE_TYPES)},
                        "url": {"type": "string", "pattern": URL_RX},
                        "updated": {"type": "string", "pattern": DATE_RX},
                    },
                },
                "description": "首条为主源",
            },
            "created": {"type": "string", "pattern": CREATED_RX},
        },
    }


def plugin_schema() -> dict:
    """plugin.json 的 JSON Schema。"""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "contracts/plugin.schema.json",
        "title": "插件声明（plugins/<id>/plugin.json）",
        "description": "内容插件的最小声明；插件系统只在构建期加载。",
        "$comment": PLUGIN_COMMENT,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(schema.PLUGIN_FIELDS),
        "properties": {
            "id": {"type": "string", "pattern": schema.PLUGIN_ID_RE.pattern},
            "name": {"type": "string", "minLength": 1},
            "version": {"type": "string", "pattern": schema.SEMVER_RE.pattern},
            "plugin_api": {"const": "1.0"},
            "record_prefix": {"type": "string", "pattern": schema.PREFIX_RE.pattern},
            "data": {"type": "string", "minLength": 1},
            "schema": {"type": "string", "minLength": 1},
            "capabilities": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"enum": list(schema.CAPABILITIES)},
            },
        },
    }


def dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    outdir = root / "contracts"
    targets = {
        "work.schema.json": dump(work_schema()),
        "plugin.schema.json": dump(plugin_schema()),
    }

    if args.check:
        bad: list[str] = []
        for name, text in targets.items():
            p = outdir / name
            if not p.is_file():
                bad.append(f"{name}: 缺失")
            elif p.read_text(encoding="utf-8") != text:
                bad.append(f"{name}: 与 schema.py 不同步")
        if bad:
            print("[FAIL] contracts/ 未同步：")
            for m in bad:
                print(f"  - {m}")
            print("  修复：python3 kernel/emit_contracts.py")
            return 1
        print("[OK] contracts/ 与 schema.py 一致")
        return 0

    outdir.mkdir(parents=True, exist_ok=True)
    for name, text in targets.items():
        (outdir / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] 已生成 {len(targets)} 个契约文件 → contracts/")
    for name in targets:
        print(f"  - contracts/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
