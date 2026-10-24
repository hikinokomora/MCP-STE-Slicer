# -*- coding: utf-8 -*-
"""Tool registry shared by the MCP server (tools/list, tools/call) and the LLM agent."""
import os
import re
from collections import OrderedDict

from . import corrections, knowledge
from .slicer_api import ToolError


def _obj(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return schema


OBJECT_ID = {"type": "string", "description": "object_id из list_objects; можно не указывать, если модель одна"}
EXTRUDER = {"type": "integer", "description": "Номер экструдера (0 — основной)", "default": 0}


class ToolRegistry:
    def __init__(self, api, output_dir_provider, corrections_store=None, bus=None):
        self._api = api
        self._output_dir = output_dir_provider
        self._corrections = corrections_store
        self._bus = bus
        self._last_selection = {}  # requirements / part type of the last recommend_materials call
        self._current_material = None  # material of the main extruder set through the agent
        self._tools = OrderedDict()
        self._register_all()

    # ------------------------------------------------------------------ registry
    def add(self, name, description, schema, handler, group):
        self._tools[name] = {"name": name, "description": description, "inputSchema": schema,
                             "handler": handler, "group": group}

    def mcp_list(self):
        return [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                for t in self._tools.values()]

    def openai_tools(self):
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["inputSchema"]}}
                for t in self._tools.values()]

    def group_of(self, name):
        tool = self._tools.get(name)
        return tool["group"] if tool else "unknown"

    def call(self, name, arguments):
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError("Неизвестный инструмент %s" % name)
        return tool["handler"](**(arguments or {}))

    # ------------------------------------------------------------------ helpers
    def _default_path(self, ext):
        info = self._api.scene_info()
        objects = info.get("objects") or []
        base = objects[0]["name"] if objects else "project"
        base = re.sub(r"[\\/:*?\"<>|]+", "_", os.path.splitext(base)[0]).strip() or "project"
        folder = os.path.join(self._output_dir(), base)
        name = "project.3mf" if ext == "3mf" else "result.gcode"
        return os.path.join(folder, name)

    # ------------------------------------------------------------------ tools
    def _register_all(self):
        api = self._api

        # --- settings & profiles
        self.add("get_scene_info",
                 "Текущее состояние слайсера: принтер, режим 3D/5D, профиль, материал, объекты на столе, изменённые настройки.",
                 _obj(), lambda: api.scene_info(), "scene")
        self.add("list_profiles", "Список профилей качества и пользовательских профилей.",
                 _obj(), lambda: api.list_profiles(), "profile")
        self.add("set_profile",
                 "Выбрать профиль качества по quality_type (например normal, fast, draft, high, coarse, extra coarse, verydraft) или пользовательский профиль по имени.",
                 _obj({"quality_type": {"type": "string"}, "custom_profile": {"type": "string"}}),
                 lambda quality_type=None, custom_profile=None: api.set_profile(quality_type, custom_profile), "profile")
        self.add("create_profile",
                 "Сохранить текущие изменённые настройки как новый пользовательский профиль и активировать его.",
                 _obj({"name": {"type": "string"}}, ["name"]),
                 lambda name: api.create_profile(name), "profile")
        self.add("list_materials",
                 "Материалы, доступные для экструдера текущего принтера. in_knowledge_base=true — материал Stereotech "
                 "с проверенными свойствами (выбирай из них); generic_* — общие профили без данных о свойствах.",
                 _obj({"extruder": EXTRUDER}), self._list_materials, "material")
        self.add("set_material",
                 "Выбрать материал по id (например enduse_petg). Если материал не выполняет требования ТЗ из последнего "
                 "recommend_materials, инструмент откажет: объясни пользователю, что не выполняется, и только после его "
                 "явного подтверждения вызови снова с confirmed_by_user=true.",
                 _obj({"material_id": {"type": "string"}, "extruder": EXTRUDER,
                       "confirmed_by_user": {"type": "boolean", "description": "пользователь подтвердил материал, несмотря на несоответствие ТЗ"}},
                      ["material_id"]),
                 self._set_material, "material")
        self.add("set_extruder_enabled",
                 "Включить или выключить экструдер. Если второй экструдер (1) не нужен для детали — выключи его, "
                 "чтобы в проекте не оставался лишний материал. Основной экструдер (0) выключать нельзя.",
                 _obj({"extruder": {"type": "integer", "description": "Номер экструдера (1 — второй)"},
                       "enabled": {"type": "boolean"}}, ["extruder", "enabled"]),
                 lambda extruder, enabled: api.set_extruder_enabled(extruder, enabled), "material")
        self.add("recommend_materials",
                 "Подобрать материал по инженерным требованиям из ТЗ. Возвращает материалы слайсера, отсортированные по числу невыполненных требований, сразу с ключевыми свойствами "
                 "(material_properties для них вызывать не нужно; рейтинги 0..3). "
                 "Ключи требований: min_glass_or_service_temp_c, min_hdt_c, max_density, max_water_absorption_pct, min_tensile_modulus_mpa, "
                 "min_tensile_strength_mpa, min_elongation_pct, uv/oils_fuels/alkali/acids/alcohol_ipa/abrasion (0..3), flexible, food_contact, esd, low_friction, high_friction (bool).",
                 _obj({"requirements": {"type": "object", "description": "Требования, например {\"min_hdt_c\": 130, \"max_density\": 1.2, \"alkali\": 3}"},
                       "part_type": {"type": "string", "enum": corrections.PART_TYPE_IDS,
                                     "description": "функция детали: " + "; ".join("%s — %s" % p for p in corrections.PART_TYPES)},
                       "limit": {"type": "integer", "default": 6}}, ["requirements"]),
                 self._recommend_materials, "material")
        self.add("propose_correction",
                 "Предложить пользователю запомнить корректировку подбора материала — ТОЛЬКО когда пользователь сам "
                 "заменил выбранный материал и объяснил почему. Условие строится из типа детали и признаков последнего "
                 "recommend_materials; проверяется по базе Stereotech и ТЗ. Сохранять или нет, решает пользователь кнопкой.",
                 _obj({"prefer_material": {"type": "string", "description": "id материала, который выбрал пользователь"},
                       "avoid_material": {"type": "string", "description": "id материала, который пользователь отверг"},
                       "part_type": {"type": "string", "enum": corrections.PART_TYPE_IDS},
                       "features": {"type": "array", "items": {"type": "string", "enum": corrections.FEATURE_IDS},
                                    "description": "признаки условия (подмножество признаков текущего ТЗ); по умолчанию все"},
                       "comment": {"type": "string", "description": "причина словами пользователя, коротко"}}),
                 self._propose_correction, "material")
        self.add("material_properties", "Инженерные свойства материала из базы знаний (Tg, HDT, плотность, водопоглощение, стойкость).",
                 _obj({"material_id": {"type": "string"}}, ["material_id"]),
                 self._material_properties, "material")
        self.add("get_settings",
                 "Прочитать настройки по ключам (значение, единицы, min/max, варианты). Настройки экструдера читаются с экструдера 0, если не указан другой.",
                 _obj({"keys": {"type": "array", "items": {"type": "string"}}, "extruder": EXTRUDER}, ["keys"]),
                 lambda keys, extruder=None: api.get_settings(keys, extruder), "settings")
        self.add("find_settings", "Найти ключи настроек по слову (например 'seam', 'brim', 'cylindrical').",
                 _obj({"query": {"type": "string"}}, ["query"]),
                 lambda query: api.find_settings(query), "settings")
        self.add("set_settings",
                 "Изменить настройки: {ключ: значение}. Глобальные пишутся в глобальный стек, настройки экструдера — в экструдер (по умолчанию 0). "
                 "Значения вне min/max отклоняются.",
                 _obj({"values": {"type": "object"}, "extruder": EXTRUDER}, ["values"]),
                 lambda values, extruder=None: api.set_settings(values, extruder), "settings")
        self.add("reset_settings", "Сбросить все пользовательские изменения настроек. Только в самом начале работы над новой "
                 "деталью, до любых изменений; посреди работы не вызывать (сотрёт уже выставленное).",
                 _obj(), lambda: api.reset_settings(), "settings")
        self.add("set_print_mode",
                 "Переключить режим печати: classic (3D), cylindrical_full (5D), cylindrical (5D Spiral). Для 5D можно сразу задать диаметр цилиндрического основания.",
                 _obj({"mode": {"type": "string", "enum": ["classic", "cylindrical_full", "cylindrical"]},
                       "base_diameter": {"type": "number", "description": "cylindrical_mode_base_diameter, мм"},
                       "non_printing_base_diameter": {"type": "number"},
                       "round_segments": {"type": "integer"}}, ["mode"]),
                 lambda mode, base_diameter=None, non_printing_base_diameter=None, round_segments=None:
                 api.set_print_mode(mode, base_diameter, non_printing_base_diameter, round_segments), "mode")

        # --- models
        self.add("load_model", "Загрузить файл модели (STL/OBJ/3MF) на стол по абсолютному пути; модель назначается на экструдер (по умолчанию 0 — основной).",
                 _obj({"path": {"type": "string"}, "extruder": EXTRUDER}, ["path"]),
                 lambda path, extruder=0: api.load_model(path, extruder), "model")
        self.add("list_objects", "Объекты на столе: id, имя, габариты, положение.",
                 _obj(), lambda: api.list_objects(), "model")
        self.add("analyze_model",
                 "Анализ геометрии: габариты, объём, тело вращения и его ось, осевое отверстие, нависания, лучшая ориентация для 3D.",
                 _obj({"object_id": OBJECT_ID}), lambda object_id=None: api.analyze_model(object_id), "model")
        self.add("orient_model",
                 "Автоориентация: target=3d — уложить на грань с минимумом нависаний; target=5d — ось вращения вертикально и по центру стола (ось платформы).",
                 _obj({"object_id": OBJECT_ID, "target": {"type": "string", "enum": ["3d", "5d"]},
                       "axis": {"type": "string", "enum": ["X", "Y", "Z"], "description": "ось вращения детали для 5D (по умолчанию из analyze_model)"}},
                      ["target"]),
                 lambda target, object_id=None, axis=None: api.orient(object_id, target, axis), "model")
        self.add("transform_model",
                 "Переместить/повернуть/масштабировать модель. Координаты принтера в мм: X вправо, Y назад, Z вверх; (0,0) — центр стола.",
                 _obj({"object_id": OBJECT_ID,
                       "move_to": {"type": "array", "items": {"type": "number"}, "description": "[x, y] центр модели"},
                       "move_by": {"type": "array", "items": {"type": "number"}, "description": "[dx, dy, dz]"},
                       "rotate": {"type": "object", "properties": {"axis": {"type": "string", "enum": ["x", "y", "z"]},
                                                                   "angle_deg": {"type": "number"}}},
                       "scale_percent": {"type": "number"},
                       "lay_on_plate": {"type": "boolean", "default": True}}),
                 lambda object_id=None, move_to=None, move_by=None, rotate=None, scale_percent=None, lay_on_plate=True:
                 api.transform(object_id, move_to, move_by, rotate, scale_percent, lay_on_plate), "model")
        self.add("duplicate_model",
                 "3D-партия: разместить на столе копии детали (после orient_model). Считает, сколько деталей помещается "
                 "с зазором, делит партию на равные запуски и раскладывает детали одного запуска сеткой. "
                 "max_per_run — ограничить число деталей за запуск (например, если один запуск слишком долгий). "
                 "Только 3D; в 5D одна деталь за запуск.",
                 _obj({"object_id": OBJECT_ID,
                       "count": {"type": "integer", "description": "сколько деталей нужно всего (из ТЗ)"},
                       "max_per_run": {"type": "integer", "description": "не больше стольких деталей за запуск"},
                       "spacing_mm": {"type": "number", "description": "зазор между деталями, по умолчанию 10 мм (+ brim/raft)"}},
                      ["count"]),
                 lambda count, object_id=None, max_per_run=None, spacing_mm=None:
                 api.duplicate_for_batch(object_id, count, max_per_run, spacing_mm), "model")
        self.add("arrange_all", "Авторасстановка всех моделей на столе.", _obj(), lambda: api.arrange_all(), "model")
        self.add("delete_objects", "Удалить модель по object_id или все модели (object_id = all).",
                 _obj({"object_id": {"type": "string"}}), lambda object_id=None: api.delete_objects(object_id), "model")

        # --- slicing
        self.add("slice", "Запустить слайсинг и дождаться результата: время печати, расход материала.",
                 _obj(), lambda: api.slice(), "slice")
        self.add("slice_status", "Состояние и прогресс слайсинга.", _obj(), lambda: api.slice_status(), "slice")
        self.add("export_gcode", "Сохранить G-code после слайсинга. Без path — в папку результатов по имени модели (result.gcode).",
                 _obj({"path": {"type": "string"}}), self._export_gcode, "slice")
        self.add("save_project", "Сохранить проект STE Slicer (.3mf) с моделью и всеми настройками. Без path — project.3mf в папку результатов.",
                 _obj({"path": {"type": "string"}}), self._save_project, "slice")
        self.add("validate_gcode",
                 "Проверить сохранённый G-code: не пустой, есть слои, температуры соответствуют материалу, режим печати, оценка расхода.",
                 _obj({"path": {"type": "string"}}), self._validate_gcode, "slice")

    # ------------------------------------------------------------------ handlers
    def _recommend_materials(self, requirements, limit=6, part_type=None):
        available = None
        try:
            available = set(m["id"] for m in self._api.list_materials(0)["materials"])
        except Exception:
            pass
        ranked = knowledge.score_materials(requirements, available)
        applied = []
        if self._corrections is not None:
            ranked, applied = corrections.apply(ranked, requirements, part_type, self._corrections.all())
        self._last_selection = {"requirements": requirements, "part_type": part_type,
                                "base_choice": knowledge.score_materials(requirements, available)[0]["id"] if ranked else None}
        result = {"requirements": requirements, "part_type": part_type,
                  "features": corrections.features_from_requirements(requirements),
                  "candidates": ranked[:max(1, int(limit))],
                  "note": "Свойства — типичные справочные значения; температуры печати берутся из профиля материала слайсера."}
        if applied:
            result["applied_corrections"] = applied
            result["note"] += (" Учтены корректировки пользователей (applied_corrections): они меняют порядок только среди "
                               "материалов, которые выполняют ТЗ. Упомяни их одной строкой в итоге.")
        return result

    def _set_material(self, material_id, extruder=0, confirmed_by_user=False):
        ctx = self._last_selection or {}
        problem = None
        if ctx.get("requirements") and int(extruder) == 0:
            problem = corrections.spec_problem(material_id, ctx["requirements"])
        if problem and not confirmed_by_user:
            # enforced in code: a material that breaks the spec is never applied silently
            raise ToolError(problem + ". Материал НЕ изменён. Объясни пользователю, какие требования ТЗ не выполняются, "
                            "и спроси подтверждение; если подтвердит — вызови set_material с confirmed_by_user=true.")
        previous = self._current_material if int(extruder) == 0 else None
        result = self._api.set_material(material_id, extruder)
        if int(extruder) == 0:
            self._current_material = material_id
        if problem:
            result["warning"] = ("Материал выбран по решению пользователя и не выполняет ТЗ: %s. Обязательно укажи это в итоге. "
                                 "Корректировку подбора с ним сохранить нельзя." % problem)
        elif previous and previous != material_id and ctx.get("requirements"):
            result["note"] = ("Материал заменён после подбора. Если это замена по просьбе пользователя — после нарезки вызови "
                              "propose_correction(prefer_material=\"%s\", comment=<причина словами пользователя>), "
                              "чтобы он решил, запомнить ли её." % material_id)
        return result

    def _propose_correction(self, prefer_material=None, avoid_material=None, part_type=None, features=None, comment=""):
        if bool(prefer_material) == bool(avoid_material):
            raise ToolError("Укажи ровно одно: prefer_material или avoid_material")
        ctx = self._last_selection or {}
        if not ctx.get("requirements"):
            raise ToolError("Сначала вызови recommend_materials с требованиями ТЗ: корректировка строится от них")
        current = corrections.features_from_requirements(ctx["requirements"])
        chosen = current if features is None else [f for f in features if f in current]
        corr = corrections.build(part_type or ctx.get("part_type"), chosen, prefer_material, avoid_material, comment,
                                 ctx["requirements"])
        problems = corrections.validate(corr)
        if problems:
            return {"ok": False, "problems": problems,
                    "note": "Корректировка не прошла проверку и не будет предложена. Коротко объясни пользователю почему."}
        if self._bus is not None:
            self._bus.emit("correction_offer", correction=corr, text=corrections.describe(corr))
        return {"ok": True, "offered": corrections.describe(corr),
                "note": "Пользователю показана карточка «Запомнить?». Не спрашивай об этом текстом и не сохраняй сам."}

    def _list_materials(self, extruder=0):
        data = self._api.list_materials(extruder)
        for m in data.get("materials", []):
            m["in_knowledge_base"] = m.get("id") in knowledge.MATERIALS
        data["materials"].sort(key=lambda m: (not m["in_knowledge_base"], m.get("id", "")))
        data["note"] = ("Выбирай материалы с in_knowledge_base=true (Stereotech): для них есть инженерные свойства. "
                        "generic_* — общие профили Ultimaker без проверенных свойств, их не выбирай.")
        return data

    def _material_properties(self, material_id):
        card = knowledge.material_card(material_id)
        if card is None:
            raise ToolError("Для материала %s нет проверенных свойств: это общий профиль, а не материал Stereotech. "
                            "Выбери материал из recommend_materials (материалы Stereotech из базы знаний)." % material_id)
        return card

    def _export_gcode(self, path=None):
        return self._api.export_gcode(path or self._default_path("gcode"))

    def _save_project(self, path=None):
        return self._api.save_project(path or self._default_path("3mf"))

    def _validate_gcode(self, path=None):
        path = path or self._default_path("gcode")
        if not os.path.isfile(path):
            raise ToolError("Файл G-code не найден: %s" % path)
        return validate_gcode_file(path, self._api)


def validate_gcode_file(path, api=None):
    layers = 0
    extrude_moves = 0
    temps = set()
    bed_temps = set()
    header = {}
    size = os.path.getsize(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith(";LAYER:"):
                layers += 1
            elif line.startswith(";") and ":" in line[:30] and len(header) < 40 and not line.startswith(";PREVIEW"):
                key, _, value = line[1:].partition(":")
                header.setdefault(key.strip(), value.strip())
            elif line.startswith("G1") and " E" in line:
                extrude_moves += 1
            elif line.startswith(("M104", "M109")):
                m = re.search(r"S(\d+)", line)
                if m and int(m.group(1)) > 0:
                    temps.add(int(m.group(1)))
            elif line.startswith(("M140", "M190")):
                m = re.search(r"S(\d+)", line)
                if m and int(m.group(1)) > 0:
                    bed_temps.add(int(m.group(1)))
    problems = []
    if size < 1024 or extrude_moves == 0:
        problems.append("G-code пустой или не содержит экструзии")
    if layers == 0:
        problems.append("нет слоёв (;LAYER:)")
    result = {"path": path, "size_kb": round(size / 1024.0, 1), "layers": layers, "extrusion_moves": extrude_moves,
              "nozzle_temperatures": sorted(temps), "bed_temperatures": sorted(bed_temps),
              "print_mode": header.get("PRINTING_MODE"), "time_s": header.get("TIME"),
              "filament": header.get("Filament used")}
    if api is not None:
        try:
            settings = api.get_settings(["material_print_temperature", "material_bed_temperature"], 0)
            expected = settings["material_print_temperature"]["value"]
            if temps and all(abs(t - expected) > 15 for t in temps):
                problems.append("температура сопла %s не совпадает с настройкой материала %s" % (sorted(temps), expected))
        except Exception:
            pass
    result["ok"] = not problems
    result["problems"] = problems
    return result
