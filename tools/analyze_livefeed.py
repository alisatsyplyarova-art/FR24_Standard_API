#!/usr/bin/env python3
"""
analyze_livefeed.py - полный разбор LiveFeed из HAR. Только стандартная библиотека.

Запуск:
    python analyze_livefeed.py www.flightradar24_clean.har fr24_analysis

Ничего в проекте не меняет. В папку вывода пишет:
    report.md      - отчёт: ответы, структура полей, кандидаты ICAO, вывод
    structure.txt  - полное дерево полей: первый и последний самолёт
    flights.csv    - все самолёты из всех ответов (скалярные поля)
"""
import base64
import collections
import csv
import json
import os
import re
import struct
import sys

WT_VARINT, WT_I64, WT_LEN, WT_SGRP, WT_EGRP, WT_I32 = 0, 1, 2, 3, 4, 5
U64 = 1 << 64
ICAO_RE = re.compile(r"^[0-9A-F]{6}$")


class PBError(Exception):
    pass


def read_varint(buf, pos, end):
    result, shift = 0, 0
    while True:
        if pos >= end:
            raise PBError("обрыв varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift >= 70:
            raise PBError("varint слишком длинный")


class Node:
    __slots__ = ("field", "wt", "value", "kind", "children")

    def __init__(self, field, wt, value=None, kind=None, children=None):
        self.field = field
        self.wt = wt
        self.value = value
        self.kind = kind          # int / i32 / i64 / msg / str / bytes
        self.children = children


def classify_len(field, buf, start, end):
    raw = buf[start:end]
    if raw and all(0x20 <= c <= 0x7E for c in raw):
        return Node(field, WT_LEN, raw.decode("ascii"), "str")
    if raw:
        try:
            kids = parse_fields(buf, start, end)
            if kids:
                return Node(field, WT_LEN, raw.hex(), "msg", kids)
        except PBError:
            pass
    return Node(field, WT_LEN, raw.hex(), "bytes")


def parse_fields(buf, start, end):
    nodes = []
    pos = start
    while pos < end:
        key, pos = read_varint(buf, pos, end)
        field, wt = key >> 3, key & 7
        if field == 0 or wt in (WT_SGRP, WT_EGRP):
            raise PBError("недопустимый ключ %d" % key)
        if wt == WT_VARINT:
            v, pos = read_varint(buf, pos, end)
            nodes.append(Node(field, wt, v, "int"))
        elif wt == WT_I64:
            if pos + 8 > end:
                raise PBError("обрыв fixed64")
            nodes.append(Node(field, wt, struct.unpack_from("<Q", buf, pos)[0], "i64"))
            pos += 8
        elif wt == WT_I32:
            if pos + 4 > end:
                raise PBError("обрыв fixed32")
            nodes.append(Node(field, wt, struct.unpack_from("<I", buf, pos)[0], "i32"))
            pos += 4
        elif wt == WT_LEN:
            ln, pos = read_varint(buf, pos, end)
            if pos + ln > end:
                raise PBError("обрыв length-delimited")
            nodes.append(classify_len(field, buf, pos, pos + ln))
            pos += ln
        else:
            raise PBError("wire type %d" % wt)
    return nodes


def grpc_frames(data):
    frames, pos = [], 0
    while pos + 5 <= len(data):
        flag = data[pos]
        ln = struct.unpack_from(">I", data, pos + 1)[0]
        body = data[pos + 5:pos + 5 + ln]
        if len(body) != ln:
            raise PBError("обрезанный gRPC-фрейм")
        frames.append((flag, body))
        pos += 5 + ln
    if pos != len(data):
        raise PBError("лишние байты после фреймов")
    return frames


class Stat:
    def __init__(self):
        self.count = 0
        self.kinds = collections.Counter()
        self.values = set()
        self.examples = []

    def add(self, kind, value):
        self.count += 1
        self.kinds[kind] += 1
        if value is None:
            return
        s = str(value)[:120]
        if len(self.values) < 3000:
            self.values.add(s)
        if len(self.examples) < 5 and s not in self.examples:
            self.examples.append(s)


class Ctx:
    def __init__(self):
        self.stats = collections.defaultdict(Stat)
        self.cand = collections.defaultdict(lambda: collections.defaultdict(set))
        self.hex6 = collections.defaultdict(set)


def walk(node, path, key, ctx):
    p = "%s.%d" % (path, node.field)
    if node.kind == "msg":
        ctx.stats[p].add("msg", None)
        for c in node.children:
            walk(c, p, key, ctx)
        return
    ctx.stats[p].add(node.kind, node.value)
    if node.kind == "str" and ICAO_RE.match(node.value):
        ctx.hex6[p].add((key, node.value))
    if node.kind == "bytes" and len(node.value) == 6:      # 3 байта, big-endian
        ctx.cand[p][key].add(int(node.value, 16))
    elif node.kind in ("int", "i32") and 0 < node.value <= 0xFFFFFF and p != "F.1":
        ctx.cand[p][key].add(node.value)


def dump(nodes, indent=0, lines=None):
    if lines is None:
        lines = []
    pad = "  " * indent
    for n in nodes:
        if n.kind == "msg":
            lines.append("%s%d: msg (%d байт)" % (pad, n.field, len(n.value) // 2))
            dump(n.children, indent + 1, lines)
        elif n.kind == "str":
            lines.append("%s%d: str '%s'" % (pad, n.field, n.value))
        elif n.kind == "bytes":
            lines.append("%s%d: bytes[%d] %s" % (pad, n.field, len(n.value) // 2, n.value[:80]))
        elif n.kind == "int":
            extra = ""
            if n.value >= 1 << 63:
                extra = " (signed %d)" % (n.value - U64)
            lines.append("%s%d: varint %d%s" % (pad, n.field, n.value, extra))
        elif n.kind == "i32":
            f = struct.unpack("<f", struct.pack("<I", n.value))[0]
            lines.append("%s%d: fixed32 %d (float %.6g)" % (pad, n.field, n.value, f))
        elif n.kind == "i64":
            lines.append("%s%d: fixed64 %d" % (pad, n.field, n.value))
    return lines


def decode_entry(entry):
    content = entry["response"]["content"]
    text = content.get("text", "")
    if content.get("encoding") == "base64":
        return base64.b64decode(text)
    return text.encode("latin-1", "replace")


def eval_candidates(cand, obs):
    rows = []
    for p in sorted(cand):
        bykey = cand[p]
        checked = [k for k in bykey if obs[k] >= 2]
        const = [k for k in checked if len(bykey[k]) == 1]
        values = {next(iter(bykey[k])) for k in const}
        if len(checked) < 3:
            verdict = "мало данных (нужно >=3 самолёта, каждый встречён >=2 раз)"
        elif len(const) == len(checked) and len(values) == 1:
            verdict = "константа у всех самолётов - не ICAO"
        elif len(const) == len(checked) and len(values) >= max(3, len(checked) // 2):
            verdict = "КАНДИДАТ ICAO: постоянен у каждого самолёта, различается между самолётами"
        else:
            verdict = "меняется внутри самолёта (%d из %d постоянны) - не ICAO" % (len(const), len(checked))
        rows.append((p, len(checked), len(const), len(values), verdict))
    return rows


def path_key(p):
    return [int(t) if t.isdigit() else t for t in p.split(".")]


def describe_14(node):
    f14 = [c for c in node.children if c.field == 14 and c.kind == "msg"]
    if not f14:
        return ["поля 14 нет"]
    out = []
    for item in f14[0].children[:6]:
        if item.kind == "msg":
            vals = [(c.field, c.value - U64 if c.value >= 1 << 63 else c.value)
                    for c in item.children if c.kind == "int"]
            out.append(str(vals))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    har_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "fr24_analysis"
    os.makedirs(out_dir, exist_ok=True)

    with open(har_path, encoding="utf-8") as f:
        har = json.load(f)
    entries = [e for e in har["log"]["entries"] if "LiveFeed" in e["request"]["url"]]

    ctx = Ctx()
    obs = collections.Counter()
    resp_rows, flights_csv, examples = [], [], []
    field_present = collections.Counter()
    total_flights = 0

    for idx, entry in enumerate(entries, 1):
        row = {"idx": idx, "time": entry.get("startedDateTime", ""), "bytes": 0,
               "frames": 0, "flights": 0, "status": "ok", "trailer": ""}
        try:
            raw = decode_entry(entry)
            row["bytes"] = len(raw)
            for flag, body in grpc_frames(raw):
                row["frames"] += 1
                if flag & 0x80:
                    row["trailer"] = body.decode("ascii", "replace").strip()
                    continue
                if flag != 0:
                    row["status"] = "сжатый фрейм flag=%d (не разобран)" % flag
                    continue
                root = parse_fields(body, 0, len(body))
                for node in root:
                    if node.field != 1 or node.kind != "msg":
                        ctx.stats["root.%d" % node.field].add(node.kind, node.value)
                        continue
                    total_flights += 1
                    row["flights"] += 1
                    kid = next((c for c in node.children if c.field == 1 and c.kind == "int"), None)
                    key = kid.value if kid else "noid-%d-%d" % (idx, total_flights)
                    obs[key] += 1
                    seen = set()
                    for c in node.children:
                        seen.add(c.field)
                        walk(c, "F", key, ctx)
                    for fnum in seen:
                        field_present[fnum] += 1
                    flat = {"key": key}
                    for c in node.children:
                        if c.kind in ("int", "i32", "str"):
                            flat["f%d" % c.field] = c.value
                    flights_csv.append({"response": idx, "time": row["time"], "key": key,
                                        "data": json.dumps(flat, ensure_ascii=False)})
                    examples.append((idx, node))
        except Exception as exc:
            row["status"] = "ошибка: %s" % exc
        resp_rows.append(row)

    cand_rows = eval_candidates(ctx.cand, obs)
    multi = sum(1 for k in obs if obs[k] >= 2)

    # --- structure.txt ---
    if examples:
        with open(os.path.join(out_dir, "structure.txt"), "w", encoding="utf-8") as f:
            for title, (ridx, node) in (("ПЕРВЫЙ САМОЛЁТ (ответ %d)" % examples[0][0], examples[0]),
                                        ("ПОСЛЕДНИЙ САМОЛЁТ (ответ %d)" % examples[-1][0], examples[-1])):
                f.write("== %s ==\n" % title)
                f.write("\n".join(dump(node.children)) + "\n")
                f.write("поле 14, первые элементы: %s\n\n" % " | ".join(describe_14(node)))

    # --- flights.csv ---
    with open(os.path.join(out_dir, "flights.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["response", "time", "key", "data"])
        w.writeheader()
        w.writerows(flights_csv)

    # --- report.md ---
    L = []
    A = L.append
    A("# Анализ LiveFeed: %s" % os.path.basename(har_path))
    A("")
    A("Ответов LiveFeed: %d. Самолётов всего: %d. Самолётов с >=2 появлениями: %d."
      % (len(entries), total_flights, multi))
    A("")
    A("## 1. Ответы")
    A("| # | время | байт | фреймов | самолётов | статус | трейлер |")
    A("|---|---|---|---|---|---|---|")
    for r in resp_rows:
        A("| %d | %s | %d | %d | %d | %s | %s |" % (r["idx"], r["time"], r["bytes"],
                                                    r["frames"], r["flights"], r["status"], r["trailer"]))
    A("")
    A("## 2. Поля верхнего уровня и самолёта (путь = номер поля через точку)")
    A("| путь | вхождений | типы | примеры |")
    A("|---|---|---|---|")
    for p in sorted(ctx.stats, key=path_key):
        if p.count(".") == 1:
            st = ctx.stats[p]
            A("| %s | %d | %s | %s |" % (p, st.count, ", ".join("%s:%d" % kv for kv in st.kinds.most_common()),
                                       "; ".join(st.examples)))
    A("")
    A("## 3. Вложенные поля")
    A("| путь | вхождений | типы | примеры |")
    A("|---|---|---|---|")
    for p in sorted(ctx.stats, key=path_key):
        if p.count(".") > 1:
            st = ctx.stats[p]
            A("| %s | %d | %s | %s |" % (p, st.count, ", ".join("%s:%d" % kv for kv in st.kinds.most_common()),
                                       "; ".join(st.examples)))
    A("")
    A("## 4. Кандидаты ICAO (24-битные значения: int, fixed32, bytes[3])")
    A("| путь | самолётов проверено | постоянны у самолёта | уникальных значений | вердикт |")
    A("|---|---|---|---|---|")
    for p, nchk, nconst, nval, verdict in cand_rows:
        A("| %s | %d | %d | %d | %s |" % (p, nchk, nconst, nval, verdict))
    A("")
    A("## 5. Строки формата hex-6 (возможный ICAO в виде строки)")
    if ctx.hex6:
        for p in sorted(ctx.hex6, key=path_key):
            vals = sorted({v for _, v in ctx.hex6[p]})
            A("- %s: %s" % (p, ", ".join(vals[:20])))
    else:
        A("Не найдено.")
    A("")
    A("## 6. Поля 13 и 14")
    A("- Поле 13 встретилось у %d из %d самолётов." % (field_present.get(13, 0), total_flights))
    A("- Поле 14 (вложенное сообщение) встретилось у %d самолётов." % field_present.get(14, 0))
    A("")
    A("## 7. Вывод")
    candidates = [r for r in cand_rows if r[4].startswith("КАНДИДАТ")]
    if candidates:
        A("Найдены кандидаты ICAO по критерию «постоянен у самолёта»:")
        for r in candidates:
            A("- %s (проверено %d самолётов)" % (r[0], r[1]))
        A("Перед использованием сверьте хотя бы один самолёт с известной регистрацией в ICAO-базе.")
    else:
        A("По критерию «постоянен у каждого самолёта и различается между самолётами» в этих ответах")
        A("ICAO-поля нет среди int, fixed32 и 3-байтовых bytes. Строк hex-6: см. раздел 5.")
        A("Это утверждение относится только к полям самолётов и их вложенным сообщениям (разделы 2-3).")
        A("Если в разделе 2 есть поля, похожие на ICAO, но не прошедшие проверку, смотрите раздел 4.")
    A("")
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("Готово. Отчёт: %s" % os.path.join(out_dir, "report.md"))
    print("Ответов: %d, самолётов: %d, кандидатов ICAO: %d"
          % (len(entries), total_flights, len(candidates)))


if __name__ == "__main__":
    main()