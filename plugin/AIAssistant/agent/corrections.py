# -*- coding: utf-8 -*-
"""User corrections of the material choice ("for flexible seals prefer TPV80, not TPU D70").

A correction is DATA, never instructions: a condition built from fixed lists (part type + requirement features)
and one action (prefer / avoid a Stereotech material). It is checked against a whitelist and the spec before it
is stored, and again every time it is applied, so it can only choose between materials that already satisfy the
spec - it can never push an unsuitable material.

Storage (see README):
  local   %APPDATA%/steslicer/<ver>/ai_assistant/corrections.json         - this computer only
  global  corrections/global.json in the GitHub repository (accepted by moderate.py), cached locally as
          %APPDATA%/steslicer/<ver>/ai_assistant/corrections_global.json

Pure Python (no UM imports) so that moderate.py can reuse the same checks outside the slicer.
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid

from . import knowledge

# Function of the part - finite on purpose: corrections must be comparable and countable.
PART_TYPES = [
    ("seal", "уплотнение / пыльник / манжета"),
    ("gear", "зубчатая передача"),
    ("bushing", "втулка / подшипник скольжения"),
    ("shaft", "вал / ось"),
    ("housing", "корпус / кожух"),
    ("bracket", "кронштейн / рычаг"),
    ("impeller", "крыльчатка / лопасти"),
    ("fastener", "крепёж"),
    ("pipe", "трубка / фитинг"),
    ("spring", "пружинящий элемент"),
    ("tooling", "оснастка / приспособление"),
    ("decor", "декор / фигурка"),
    ("other", "прочее"),
]
PART_TYPE_IDS = [p[0] for p in PART_TYPES]
PART_TYPE_LABELS = dict(PART_TYPES)

# Features derived from the spec requirements (the same dict that recommend_materials receives).
FEATURES = [
    ("flexible", "гибкая / эластичная"),
    ("rigid", "жёсткая"),
    ("high_temp", "высокая температура (от 80 °C)"),
    ("oils", "масла / топливо"),
    ("water", "контакт с водой / низкое водопоглощение"),
    ("chemicals", "кислоты / щёлочи"),
    ("uv", "улица / УФ"),
    ("wear", "износ / трение"),
    ("load", "механическая нагрузка"),
    ("light", "малый вес"),
    ("food", "контакт с пищей"),
    ("esd", "антистатика"),
]
FEATURE_IDS = [f[0] for f in FEATURES]
FEATURE_LABELS = dict(FEATURES)

MIN_CONDITION_ITEMS = 2      # "for every part -> X" is too broad to be stored
MAX_COMMENT = 300
LOCAL_WEIGHT, GLOBAL_WEIGHT = 2, 1

_lock = threading.Lock()


def features_from_requirements(req):
    """Requirement dict -> sorted list of feature ids."""
    req = req or {}
    f = set()

    def num(key):
        try:
            return float(req.get(key)) if req.get(key) is not None else None
        except (TypeError, ValueError):
            return None

    if req.get("flexible") is True:
        f.add("flexible")
    if req.get("flexible") is False or (num("min_tensile_modulus_mpa") or 0) >= 1500:
        f.add("rigid")
    if max(num("min_glass_or_service_temp_c") or 0, num("min_hdt_c") or 0) >= 80:
        f.add("high_temp")
    if (num("oils_fuels") or 0) >= 2:
        f.add("oils")
    if num("max_water_absorption_pct") is not None:
        f.add("water")
    if max(num("acids") or 0, num("alkali") or 0) >= 2:
        f.add("chemicals")
    if (num("uv") or 0) >= 2:
        f.add("uv")
    if (num("abrasion") or 0) >= 2 or req.get("low_friction"):
        f.add("wear")
    if (num("min_tensile_strength_mpa") or 0) >= 40:
        f.add("load")
    if num("max_density") is not None:
        f.add("light")
    if req.get("food_contact"):
        f.add("food")
    if req.get("esd"):
        f.add("esd")
    return sorted(f)


def clean_comment(text):
    """A comment is shown to people only; it never reaches the scoring and is stripped of markup/control chars."""
    text = re.sub(r"[\x00-\x1f<>`{}\[\]]+", " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:MAX_COMMENT]


def fingerprint(part_type, features, action):
    key = json.dumps({"part_type": part_type or None, "features": sorted(features or []),
                      "action": action}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def build(part_type, features, prefer=None, avoid=None, comment="", requirements=None, mode=None):
    """Make a correction record (not validated, not stored)."""
    action = {"prefer": prefer} if prefer else {"avoid": avoid}
    features = sorted(set(features or []))
    return {
        "id": uuid.uuid4().hex[:12],
        "conditions": {"part_type": part_type or None, "features": features},
        "action": action,
        "comment": clean_comment(comment),
        "context": {"requirements": requirements or {}, "mode": mode},
        "fingerprint": fingerprint(part_type, features, action),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def validate(corr, check_spec=True):
    """Whitelist + 'at least two condition items' + spec check. Returns a list of problems (empty = valid)."""
    problems = []
    if not isinstance(corr, dict):
        return ["Корректировка повреждена"]
    cond = corr.get("conditions") or {}
    action = corr.get("action") or {}
    part_type = cond.get("part_type")
    features = cond.get("features") or []
    if part_type is not None and part_type not in PART_TYPE_IDS:
        problems.append("Неизвестный тип детали: %s" % part_type)
    bad = [f for f in features if f not in FEATURE_IDS]
    if bad:
        problems.append("Неизвестные признаки: %s" % ", ".join(map(str, bad)))
    items = (1 if part_type and part_type != "other" else 0) + len([f for f in features if f in FEATURE_IDS])
    if items < MIN_CONDITION_ITEMS:
        problems.append("Слишком общее условие: нужно минимум %d признака (тип детали и/или требования), "
                        "иначе корректировка затронет почти все детали" % MIN_CONDITION_ITEMS)
    if len(action) != 1 or list(action)[0] not in ("prefer", "avoid"):
        problems.append("Действие должно быть одно: предпочесть или избегать материал")
    material = list(action.values())[0] if len(action) == 1 else None
    if material not in knowledge.MATERIALS:
        problems.append("Материала %s нет в базе Stereotech" % material)
    if corr.get("fingerprint") != fingerprint(part_type, features, action):
        problems.append("Отпечаток корректировки не совпадает с её содержимым")
    if check_spec and not problems and "prefer" in action:
        reason = spec_problem(action["prefer"], (corr.get("context") or {}).get("requirements"))
        if reason:
            problems.append(reason)
    return problems


def spec_problem(material_id, requirements):
    """The preferred material must satisfy the spec at least as well as the best material without corrections."""
    if not requirements:
        return None
    ranked = knowledge.score_materials(requirements)
    if not ranked:
        return None
    best_failed = set(ranked[0]["failed"])
    mine = next((r for r in ranked if r["id"] == material_id), None)
    if mine is None:
        return "Материала %s нет в базе Stereotech" % material_id
    extra = [k for k in mine["failed"] if k not in best_failed]
    if extra:
        return "%s не выполняет требования ТЗ: %s" % (mine["name"], ", ".join(extra))
    return None


# ------------------------------------------------------------------ storage
class Store:
    def __init__(self, folder, logger=None):
        self.local_path = os.path.join(folder, "corrections.json")
        self.global_path = os.path.join(folder, "corrections_global.json")
        self._log = logger or (lambda *a: None)

    def _read(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else data.get("corrections", [])
        except (OSError, ValueError):
            return []

    def _valid(self, items, source):
        good = []
        for c in items:
            problems = validate(c, check_spec=False)  # the spec is re-checked when applied
            if problems:
                self._log("AIAssistant: ignored %s correction %s: %s" % (source, c.get("id"), "; ".join(problems)))
            else:
                good.append(dict(c, source=source))
        return good

    def local(self):
        return self._valid(self._read(self.local_path), "local")

    def global_(self):
        return self._valid(self._read(self.global_path), "global")

    def all(self):
        return self.local() + self.global_()

    def add_local(self, corr, proposed=False):
        with _lock:
            items = self._read(self.local_path)
            items = [c for c in items if c.get("fingerprint") != corr["fingerprint"]]  # same rule -> replace
            corr = dict(corr, scope="proposed" if proposed else "local")
            corr.pop("source", None)
            items.append(corr)
            self._write(self.local_path, items)
        return corr

    def delete_local(self, corr_id):
        with _lock:
            items = self._read(self.local_path)
            kept = [c for c in items if c.get("id") != corr_id]
            self._write(self.local_path, kept)
        return len(items) != len(kept)

    def save_global_cache(self, data):
        items = data if isinstance(data, list) else (data or {}).get("corrections", [])
        self._write(self.global_path, items)
        return len(items)

    @staticmethod
    def _write(path, items):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


# ------------------------------------------------------------------ applying
def apply(ranked, requirements, part_type, corrections):
    """Re-rank recommend_materials results with matching corrections. Returns (ranked, applied)."""
    current = set(features_from_requirements(requirements))
    by_id = {r["id"]: r for r in ranked}
    best_failed = set(ranked[0]["failed"]) if ranked else set()
    applied = []
    for c in corrections:
        cond = c["conditions"]
        if cond.get("part_type") and cond["part_type"] != part_type:
            continue
        if not set(cond.get("features") or []) <= current:
            continue
        kind, material = list(c["action"].items())[0]
        row = by_id.get(material)
        if row is None:
            continue
        weight = (LOCAL_WEIGHT if c.get("source") == "local" else GLOBAL_WEIGHT) * 10 + len(cond.get("features") or [])
        if kind == "prefer":
            # never lets a correction override the spec: the material must not fail more than the best one
            if any(k not in best_failed for k in row["failed"]):
                continue
            row["correction_bonus"] = max(row.get("correction_bonus", 0), weight)
        else:
            row["correction_bonus"] = min(row.get("correction_bonus", 0), -weight)
        applied.append({"id": c["id"], "source": c.get("source"), "action": c["action"],
                        "condition": describe_condition(cond), "comment": c.get("comment", "")})
    ranked.sort(key=lambda r: (len(r["failed"]), -r.get("correction_bonus", 0), -r["score"]))
    return ranked, applied


def describe_condition(cond):
    parts = []
    if cond.get("part_type"):
        parts.append(PART_TYPE_LABELS.get(cond["part_type"], cond["part_type"]))
    parts += [FEATURE_LABELS.get(f, f) for f in cond.get("features") or []]
    return " + ".join(parts)


def describe(corr):
    kind, material = list(corr["action"].items())[0]
    name = knowledge.MATERIALS.get(material, {}).get("name", material)
    verb = "предпочитать" if kind == "prefer" else "избегать"
    return "%s → %s %s" % (describe_condition(corr["conditions"]), verb, name)


def issue_body(corr, install_id):
    """Text of the GitHub issue that proposes a correction for everyone (no personal data)."""
    payload = {k: corr[k] for k in ("conditions", "action", "comment", "context", "fingerprint", "created")}
    payload["install_id"] = install_id
    return ("Предложение корректировки подбора материала для всех пользователей.\n\n"
            "%s\n\n```json\n%s\n```\n" % (describe(corr), json.dumps(payload, ensure_ascii=False, indent=2)))
