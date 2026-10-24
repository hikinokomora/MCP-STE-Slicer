"""Thin, thread-aware facade over the STE Slicer (Cura 3.6) API.

Methods without a leading underscore are safe to call from worker threads:
everything that touches the scene, the stacks or the backend is marshalled
to the Qt main thread through run_on_main.
"""
import copy
import math
import os
import threading
import time

import numpy

from PyQt5.QtCore import QUrl

from UM.Backend.Backend import BackendState
from UM.Logger import Logger
from UM.Math.Matrix import Matrix
from UM.Math.Quaternion import Quaternion
from UM.Math.Vector import Vector
from UM.Mesh.MeshWriter import MeshWriter
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Operations.GroupedOperation import GroupedOperation
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation
from UM.Operations.RotateOperation import RotateOperation
from UM.Operations.ScaleOperation import ScaleOperation
from UM.Operations.TranslateOperation import TranslateOperation
from UM.PluginRegistry import PluginRegistry
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator

from steslicer.Settings.SetObjectExtruderOperation import SetObjectExtruderOperation

from . import geometry
from .main_thread import run_on_main

TARGET_PRINTER_NAME = "Stereotech Hybrid 530 V5.2.4"
TARGET_PRINTER_DEFINITION = "hte530v5.2.4"

MODE_KEYS = ("printing_mode", "cylindrical_mode_base_diameter", "non_printing_base_diameter", "cylindrical_round_segments")

WARNING_HARD_FACTOR = 1.5

PRINT_MODES = {
    "classic": "3D",
    "cylindrical": "5D Spiral",
    "cylindrical_full": "5D",
}

STATE_NAMES = {
    BackendState.NotStarted: "not_started",
    BackendState.Processing: "processing",
    BackendState.Done: "done",
    BackendState.Error: "error",
    BackendState.Disabled: "disabled",
}


class ToolError(Exception):
    """Error that is reported back to the LLM as a normal tool result."""


def _printer_to_scene_vec(v):
    return Vector(float(v[0]), float(v[2]), -float(v[1]))


def _scene_to_printer_list(v):
    return [round(float(v.x), 2), round(float(-v.z), 2), round(float(v.y), 2)]


class SlicerAPI:
    def __init__(self, application, bus):
        self._app = application
        self._bus = bus
        self._slice_lock = threading.Lock()
        self._slice_done = threading.Event()
        self._slice_state = "not_started"
        self._slice_progress = 0.0
        self._slice_started_at = None
        self._slice_error = None
        self._slice_cancel = threading.Event()
        self._needs_slice = False
        self._hooked_backends = set()
        self._uploads = {}

    def _global(self):
        stack = self._app.getGlobalContainerStack()
        if stack is None:
            raise ToolError("Принтер не выбран: добавьте принтер в STE Slicer.")
        return stack

    def _extruder(self, position=0):
        stack = self._global()
        key = str(position if position is not None else 0)
        if key not in stack.extruders:
            raise ToolError("Нет экструдера с номером %s (есть: %s)" % (key, ", ".join(sorted(stack.extruders.keys()))))
        return stack.extruders[key]

    def _nodes(self):
        root = self._app.getController().getScene().getRoot()
        nodes = []
        for node in DepthFirstIterator(root):
            if node.callDecoration("isSliceable") and node.getMeshData() is not None:
                parent = node.getParent()
                if parent is not None and parent.callDecoration("isGroup"):
                    continue
                nodes.append(node)
        return nodes

    def _node(self, object_id):
        nodes = self._nodes()
        if not nodes:
            raise ToolError("На столе нет моделей. Сначала загрузите модель (load_model).")
        if object_id in (None, "", "auto"):
            if len(nodes) == 1:
                return nodes[0]
            raise ToolError("На столе несколько моделей, укажите object_id: %s" % ", ".join(self._node_id(n) for n in nodes))
        for node in nodes:
            if self._node_id(node) == str(object_id) or node.getName() == str(object_id):
                return node
        raise ToolError("Объект %s не найден. Доступные: %s" % (object_id, ", ".join(self._node_id(n) for n in nodes)))

    @staticmethod
    def _node_id(node):
        return "obj_%x" % (id(node) & 0xffffff)

    def _node_info(self, node):
        bbox = node.getBoundingBox()
        info = {"object_id": self._node_id(node), "name": node.getName()}
        if bbox is not None:
            info["size_mm"] = {"x": round(bbox.width, 2), "y": round(bbox.depth, 2), "z": round(bbox.height, 2)}
            info["center_mm"] = _scene_to_printer_list(bbox.center)
            info["bottom_z_mm"] = round(bbox.bottom, 2)
        info["outside_build_area"] = bool(node.isOutsideBuildArea()) if hasattr(node, "isOutsideBuildArea") else None
        info["extruder"] = node.callDecoration("getActiveExtruderPosition")
        return info

    def _assign_extruder(self, node, position):
        stack = self._extruder(position)
        if node.callDecoration("getActiveExtruder") != stack.getId():
            SetObjectExtruderOperation(node, stack.getId()).push()

    def _setting_stack(self, key, extruder):
        gs = self._global()
        # Machine-wide settings (printing mode, 5D base and overlap...) are read from the global stack only:
        # written to an extruder they are silently ignored, whatever extruder the caller named.
        if not gs.getProperty(key, "settable_per_extruder"):
            return gs
        return self._extruder(0 if extruder is None else extruder)

    @staticmethod
    def _convert(value, setting_type, options):
        if setting_type == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "да", "on")
            return bool(value)
        if setting_type == "int":
            return int(round(float(value)))
        if setting_type == "float":
            return float(value)
        if setting_type == "enum":
            value = str(value)
            if options and value not in options:
                for key, label in options.items():
                    if value.lower() in (key.lower(), str(label).lower()):
                        return key
                raise ToolError("Недопустимое значение %s. Варианты: %s" % (value, ", ".join("%s (%s)" % (k, v) for k, v in options.items())))
            return value
        if setting_type in ("extruder", "optional_extruder"):
            return str(int(float(value)))
        return value if isinstance(value, str) else str(value)

    def scene_info(self):
        return run_on_main(self._scene_info)

    def _scene_info(self):
        gs = self._global()
        mm = self._app.getMachineManager()
        ext = self._extruder(0)
        quality_changes = gs.qualityChanges
        info = {
            "printer": gs.getName(),
            "printer_definition": gs.definition.getId(),
            "print_mode": gs.getProperty("printing_mode", "value"),
            "print_mode_label": PRINT_MODES.get(gs.getProperty("printing_mode", "value"), "?"),
            "quality_type": mm.activeQualityType,
            "profile_name": mm.activeQualityOrQualityChangesName,
            "custom_profile": quality_changes.getName() if quality_changes is not None and quality_changes.getId() != "empty_quality_changes" else None,
            "material": {
                "id": ext.material.getMetaDataEntry("base_file", ext.material.getId()),
                "name": ext.material.getName(),
            },
            "extruders": len(gs.extruders),
            "build_volume_mm": {
                "x": gs.getProperty("machine_width", "value"),
                "y": gs.getProperty("machine_depth", "value"),
                "z": gs.getProperty("machine_height", "value"),
            },
            "objects": [self._node_info(n) for n in self._nodes()],
            "slice_state": self._slice_state,
        }
        if info["print_mode"] in ("cylindrical", "cylindrical_full"):
            info["five_axis"] = {k: gs.getProperty(k, "value") for k in (
                "cylindrical_mode_base_diameter", "non_printing_base_diameter",
                "cylindrical_mode_overlap", "cylindrical_round_segments")}
        user_changes = {}
        for stack, prefix in [(gs, "")] + [(e, "extruder_%s." % p) for p, e in gs.extruders.items()]:
            for key in stack.userChanges.getAllKeys():
                user_changes[prefix + key] = stack.userChanges.getProperty(key, "value")
        info["changed_settings"] = user_changes
        if info["printer_definition"] != TARGET_PRINTER_DEFINITION:
            info["printer_warning"] = (
                "Активен принтер «%s» (%s), а проекты готовятся для «%s» (%s): профили, материалы и "
                "размер стола отличаются. Попросите пользователя выбрать «%s» в слайсере "
                "(Настройки → Принтер → Добавить принтер), если он не подтвердил другой принтер явно."
                % (info["printer"], info["printer_definition"], TARGET_PRINTER_NAME,
                   TARGET_PRINTER_DEFINITION, TARGET_PRINTER_NAME))
        return info

    def list_profiles(self):
        return run_on_main(self._list_profiles)

    def _list_profiles(self):
        gs = self._global()
        qm = self._app.getQualityManager()
        mm = self._app.getMachineManager()
        qualities = []
        for quality_type, group in sorted(qm.getQualityGroups(gs).items()):
            qualities.append({"quality_type": quality_type, "name": group.name,
                              "available": bool(group.is_available),
                              "active": quality_type == mm.activeQualityType})
        custom = []
        for name, group in sorted(qm.getQualityChangesGroups(gs).items()):
            custom.append({"name": name, "quality_type": group.quality_type, "available": bool(group.is_available)})
        return {"quality_profiles": qualities, "custom_profiles": custom,
                "note": "Профили качества STE Slicer общие для всех принтеров; конкретные значения (слой, стенки и т.д.) задаются настройками."}

    def set_profile(self, quality_type=None, custom_profile=None):
        return run_on_main(self._set_profile, quality_type, custom_profile)

    def _set_profile(self, quality_type, custom_profile):
        gs = self._global()
        qm = self._app.getQualityManager()
        mm = self._app.getMachineManager()
        mode_before = {key: gs.getProperty(key, "value") for key in MODE_KEYS}
        if custom_profile:
            groups = qm.getQualityChangesGroups(gs)
            if custom_profile not in groups:
                raise ToolError("Пользовательский профиль %s не найден. Есть: %s" % (custom_profile, ", ".join(groups.keys()) or "нет"))
            mm.setQualityChangesGroup(groups[custom_profile], no_dialog=True)
        else:
            groups = qm.getQualityGroups(gs)
            if quality_type not in groups:
                raise ToolError("Профиль %s не найден. Есть: %s" % (quality_type, ", ".join(sorted(groups.keys()))))
            mm.setQualityGroup(groups[quality_type], no_dialog=True)
        result = {"quality_type": mm.activeQualityType, "profile_name": mm.activeQualityOrQualityChangesName}
        mode_after = {key: gs.getProperty(key, "value") for key in MODE_KEYS}
        if mode_after != mode_before:
            if custom_profile:
                result["print_mode_changed"] = {"from": mode_before["printing_mode"], "to": mode_after["printing_mode"]}
            else:
                for key, value in mode_before.items():
                    if mode_after[key] != value:
                        gs.userChanges.setProperty(key, "value", value)
                result["print_mode_kept"] = mode_before["printing_mode"]
        return result

    def create_profile(self, name, timeout=10.0):
        """Save the user changes as a new custom profile and activate it.

        QualityManager.createQualityChanges moves the user changes into the new profile and clears them,
        but does not activate it, and the quality lookup tables are rebuilt on a timer of the main thread.
        So: create on the main thread, wait here (worker thread) until the profile shows up, activate it.
        If it never shows up, put the user changes back so nothing is lost."""
        if not name:
            raise ToolError("Укажите имя нового профиля")
        snapshot = run_on_main(self._snapshot_user_changes)
        unique_name = run_on_main(self._create_quality_changes, name)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.3)
            if run_on_main(self._activate_custom_profile, unique_name):
                return {"created": unique_name, "active_profile": run_on_main(
                    lambda: self._app.getMachineManager().activeQualityOrQualityChangesName),
                        "note": "Текущие изменения настроек сохранены в пользовательский профиль и он активирован."}
        run_on_main(self._restore_user_changes, snapshot)
        raise ToolError("Профиль «%s» создан, но слайсер не дал его активировать; изменённые настройки "
                        "оставлены в проекте как были." % unique_name)

    def _create_quality_changes(self, name):
        unique_name = self._app.getContainerRegistry().uniqueName(name)
        self._app.getQualityManager().createQualityChanges(name)
        return unique_name

    def _activate_custom_profile(self, profile_name):
        groups = self._app.getQualityManager().getQualityChangesGroups(self._global())
        if profile_name not in groups:
            return False
        self._app.getMachineManager().setQualityChangesGroup(groups[profile_name], no_dialog=True)
        return True

    def save_profile(self, name=None):
        """Like "Update profile with current settings/overrides": merge the user changes into the
        active custom profile. With a built-in quality profile active there is nothing to update,
        so a new custom profile is created when a name is given."""
        has_custom, active = run_on_main(self._custom_profile_state)
        if not has_custom:
            if not name:
                raise ToolError("Активен встроенный профиль качества «%s»: обновлять нечего. Укажите name, "
                                "чтобы сохранить текущие настройки как новый пользовательский профиль." % active)
            result = self.create_profile(name)
            result["mode"] = "created"
            return result
        return run_on_main(self._update_custom_profile)

    def _custom_profile_state(self):
        quality_changes = self._global().qualityChanges
        has_custom = quality_changes is not None and quality_changes.getId() != "empty_quality_changes"
        return has_custom, self._app.getMachineManager().activeQualityOrQualityChangesName

    def _update_custom_profile(self):
        gs = self._global()
        mm = self._app.getMachineManager()
        quality_changes = gs.qualityChanges
        changed = sum(len(list(stack.userChanges.getAllKeys())) for stack in [gs] + list(gs.extruders.values()))
        from steslicer.Settings.ContainerManager import ContainerManager
        manager = ContainerManager.getInstance()
        if manager is None or not manager.updateQualityChanges():
            raise ToolError("Не удалось обновить профиль «%s»" % quality_changes.getName())
        manager.clearUserContainers()
        return {"mode": "updated", "profile": quality_changes.getName(), "merged_settings": changed,
                "active_profile": mm.activeQualityOrQualityChangesName}

    def list_materials(self, extruder=0):
        return run_on_main(self._list_materials, extruder)

    def _list_materials(self, extruder):
        gs = self._global()
        ext = self._extruder(extruder)
        nodes = self._app.getMaterialManager().getAvailableMaterialsForMachineExtruder(gs, ext) or {}
        active = ext.material.getMetaDataEntry("base_file", ext.material.getId())
        result = []
        for root_id, node in sorted(nodes.items()):
            md = node.getMetadata() or {}
            result.append({
                "id": root_id,
                "name": md.get("name", root_id),
                "brand": md.get("brand", ""),
                "type": md.get("material", ""),
                "diameter": md.get("properties", {}).get("diameter") if isinstance(md.get("properties"), dict) else None,
                "active": root_id == active,
            })
        return {"extruder": extruder, "materials": result}

    def set_material(self, material_id, extruder=0):
        return run_on_main(self._set_material, material_id, extruder)

    def _set_material(self, material_id, extruder):
        gs = self._global()
        ext = self._extruder(extruder)
        nodes = self._app.getMaterialManager().getAvailableMaterialsForMachineExtruder(gs, ext) or {}
        if material_id not in nodes:
            lowered = str(material_id).lower()
            matches = [k for k, n in nodes.items() if lowered in k.lower() or lowered in str(n.getMetaDataEntry("name", "")).lower()]
            if len(matches) == 1:
                material_id = matches[0]
            else:
                raise ToolError("Материал %s недоступен для этого принтера. Похожие: %s" % (material_id, ", ".join(matches[:10]) or "нет"))
        self._app.getMachineManager().setMaterial(str(extruder), nodes[material_id])
        temps = {k: ext.getProperty(k, "value") for k in ("material_print_temperature", "material_bed_temperature")}
        return {"extruder": extruder, "material": material_id, "name": ext.material.getName(), "material_defaults": temps}

    def set_extruder_enabled(self, extruder, enabled):
        return run_on_main(self._set_extruder_enabled, extruder, enabled)

    def _set_extruder_enabled(self, extruder, enabled):
        extruder = int(extruder)
        enabled = bool(enabled)
        if extruder == 0 and not enabled:
            raise ToolError("Основной экструдер (0) выключать нельзя")
        mm = self._app.getMachineManager()
        if not hasattr(mm, "setExtruderEnabled"):
            raise ToolError("Эта версия слайсера не умеет включать/выключать экструдер из плагина")
        self._extruder(extruder)
        mm.setExtruderEnabled(extruder, enabled)
        gs = self._global()
        return {"extruder": extruder, "enabled": enabled,
                "extruders_enabled_count": gs.getProperty("extruders_enabled_count", "value")}

    def get_settings(self, keys, extruder=None):
        return run_on_main(self._get_settings, keys, extruder)

    def _get_settings(self, keys, extruder):
        gs = self._global()
        result = {}
        for key in keys:
            if not gs.definition.findDefinitions(key=key):
                result[key] = {"error": "нет такой настройки"}
                continue
            stack = self._setting_stack(key, extruder)
            entry = {
                "value": stack.getProperty(key, "value"),
                "label": gs.getProperty(key, "label"),
                "unit": gs.getProperty(key, "unit") or "",
                "type": gs.getProperty(key, "type"),
                "per_extruder": bool(gs.getProperty(key, "settable_per_extruder")),
                "enabled": bool(stack.getProperty(key, "enabled")),
            }
            for bound in ("minimum_value", "maximum_value"):
                val = stack.getProperty(key, bound)
                if val is not None:
                    entry[bound] = val
            options = gs.getProperty(key, "options")
            if options:
                entry["options"] = dict(options)
            result[key] = entry
        return result

    def find_settings(self, query, limit=25):
        return run_on_main(self._find_settings, query, limit)

    def _find_settings(self, query, limit):
        gs = self._global()
        q = query.lower()
        found = []
        for definition in gs.definition.findDefinitions():
            if definition.type == "category":
                continue
            text = (definition.key + " " + str(definition.label) + " " + str(definition.description)).lower()
            if q in text:
                found.append({"key": definition.key, "label": definition.label, "unit": definition.unit or "",
                              "value": self._setting_stack(definition.key, None).getProperty(definition.key, "value")})
                if len(found) >= limit:
                    break
        return {"query": query, "settings": found}

    def set_settings(self, values, extruder=None):
        return run_on_main(self._set_settings, values, extruder)

    def _set_settings(self, values, extruder):
        gs = self._global()
        applied, rejected, warnings = {}, {}, []
        for key, raw in values.items():
            if not gs.definition.findDefinitions(key=key):
                rejected[key] = "нет такой настройки"
                continue
            stack = self._setting_stack(key, extruder)
            setting_type = gs.getProperty(key, "type")
            try:
                value = self._convert(raw, setting_type, gs.getProperty(key, "options"))
            except (ToolError, ValueError, TypeError) as e:
                rejected[key] = str(e)
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                low = stack.getProperty(key, "minimum_value")
                high = stack.getProperty(key, "maximum_value")
                if low is not None and value < low:
                    rejected[key] = "значение %s меньше допустимого минимума %s" % (value, low)
                    continue
                if high is not None and value > high:
                    rejected[key] = "значение %s больше допустимого максимума %s" % (value, high)
                    continue
                low_w = stack.getProperty(key, "minimum_value_warning")
                high_w = stack.getProperty(key, "maximum_value_warning")
                if high is None and high_w is not None and high_w > 0 and value > high_w * WARNING_HARD_FACTOR:
                    rejected[key] = ("значение %s намного больше рекомендуемого максимума %s (жёсткая граница %s)"
                                     % (value, high_w, round(high_w * WARNING_HARD_FACTOR, 4)))
                    continue
                if low is None and low_w is not None and low_w > 0 and value < low_w / WARNING_HARD_FACTOR:
                    rejected[key] = ("значение %s намного меньше рекомендуемого минимума %s (жёсткая граница %s)"
                                     % (value, low_w, round(low_w / WARNING_HARD_FACTOR, 4)))
                    continue
                if (low_w is not None and value < low_w) or (high_w is not None and value > high_w):
                    warnings.append("%s = %s вне рекомендуемого диапазона [%s; %s]" % (key, value, low_w, high_w))
            stack.userChanges.setProperty(key, "value", value)
            applied[key] = stack.getProperty(key, "value")
            if not stack.getProperty(key, "enabled"):
                warnings.append("%s сейчас не используется (enabled = false) при текущих настройках" % key)
        result = {"applied": applied}
        if rejected:
            result["rejected"] = rejected
        if warnings:
            result["warnings"] = warnings
        return result

    def reset_settings(self):
        return run_on_main(self._reset_settings)

    def _reset_settings(self):
        gs = self._global()
        cleared = 0
        for stack in [gs] + list(gs.extruders.values()):
            keys = list(stack.userChanges.getAllKeys())
            cleared += len(keys)
            for key in keys:
                stack.userChanges.removeInstance(key)
        return {"cleared": cleared}

    def set_print_mode(self, mode, base_diameter=None, non_printing_base_diameter=None, round_segments=None):
        return run_on_main(self._set_print_mode, mode, base_diameter, non_printing_base_diameter, round_segments)

    def _set_print_mode(self, mode, base_diameter, non_printing_base_diameter, round_segments):
        aliases = {"3d": "classic", "5d": "cylindrical_full", "5d_spiral": "cylindrical", "spiral": "cylindrical"}
        mode = aliases.get(str(mode).lower(), mode)
        if mode not in PRINT_MODES:
            raise ToolError("Режим %s не поддерживается. Разрешены: classic (3D), cylindrical (5D Spiral), cylindrical_full (5D)." % mode)
        gs = self._global()
        if not gs.getProperty("machine_five_axis", "value") and mode != "classic":
            raise ToolError("Текущий принтер %s не поддерживает 5D." % gs.getName())
        gs.userChanges.setProperty("printing_mode", "value", mode)
        extra = {}
        if base_diameter is not None:
            extra["cylindrical_mode_base_diameter"] = base_diameter
        if non_printing_base_diameter is not None:
            extra["non_printing_base_diameter"] = non_printing_base_diameter
        if round_segments is not None:
            extra["cylindrical_round_segments"] = round_segments
        result = {"print_mode": gs.getProperty("printing_mode", "value"), "label": PRINT_MODES[mode]}
        if extra:
            result.update(self._set_settings(extra, None))
        if mode != "classic":
            result["five_axis"] = {k: gs.getProperty(k, "value") for k in (
                "cylindrical_mode_base_diameter", "non_printing_base_diameter", "cylindrical_round_segments")}
            result["note"] = "В 5D ось вращения — вертикаль через центр стола (X=0, Y=0); тело вращения нужно ставить осью вертикально и центровать (orient_model с target=5d)."
        return result

    def remember_upload(self, name, path):
        """Called for every file the user attaches in the chat."""
        self._uploads[name.lower()] = path

    @staticmethod
    def _stem(name):
        name = os.path.basename((name or "").replace("\\", "/")).lower()
        return os.path.splitext(name)[0]

    def load_model(self, path, extruder=0, timeout=120):
        path = (path or "").strip().strip('"')
        if not os.path.isfile(path):
            name = os.path.basename(path.replace("\\", "/")).lower()
            on_plate = [n for n in run_on_main(self._nodes) if self._stem(n.getName()) == self._stem(name)]
            if on_plate:
                return {"already_on_plate": True,
                        "objects": [run_on_main(lambda n=n: self._node_info(n)) for n in on_plate],
                        "note": "Эта модель уже на столе, загружать её не нужно — работай с ней по object_id."}
            if name in self._uploads and os.path.isfile(self._uploads[name]):
                path = self._uploads[name]
            else:
                raise ToolError("Файл %s не найден: пользователь не прикладывал такую 3D-модель и её нет на столе. "
                                "Не угадывай имена файлов: если модели нет, попроси пользователя приложить "
                                "STL/OBJ/3MF или открыть её в слайсере." % path)
        before = set(run_on_main(lambda: [self._node_id(n) for n in self._nodes()]))
        run_on_main(lambda: self._app.readLocalFile(QUrl.fromLocalFile(path), True))
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            new = run_on_main(lambda: [n for n in self._nodes() if self._node_id(n) not in before])
            if new:
                time.sleep(0.5)

                def finish():
                    nodes = [n for n in self._nodes() if self._node_id(n) not in before]
                    for node in nodes:
                        self._assign_extruder(node, extruder)
                    return [self._node_info(n) for n in nodes]
                return {"loaded": run_on_main(finish)}
        raise ToolError("Модель не появилась на столе за %s с" % timeout)

    def list_objects(self):
        return run_on_main(lambda: {"objects": [self._node_info(n) for n in self._nodes()]})

    def delete_objects(self, object_id=None):
        return run_on_main(self._delete_objects, object_id)

    def _delete_objects(self, object_id):
        nodes = self._nodes() if object_id in (None, "", "all") else [self._node(object_id)]
        op = GroupedOperation()
        for node in nodes:
            op.addOperation(RemoveSceneNodeOperation(node))
        op.push()
        return {"deleted": [self._node_id(n) for n in nodes]}

    def transform(self, object_id=None, move_to=None, move_by=None, rotate=None, scale_percent=None, lay_on_plate=True):
        return run_on_main(self._transform, object_id, move_to, move_by, rotate, scale_percent, lay_on_plate)

    def _transform(self, object_id, move_to, move_by, rotate, scale_percent, lay_on_plate):
        node = self._node(object_id)
        op = GroupedOperation()
        has_ops = False
        if rotate:
            axis = {"x": Vector(1, 0, 0), "y": Vector(0, 0, -1), "z": Vector(0, 1, 0)}.get(str(rotate.get("axis", "z")).lower())
            if axis is None:
                raise ToolError("Ось поворота должна быть x, y или z")
            angle = math.radians(float(rotate.get("angle_deg", 0)))
            op.addOperation(RotateOperation(node, Quaternion.fromAngleAxis(angle, axis), rotate_around_point=node.getBoundingBox().center))
            has_ops = True
        if scale_percent:
            factor = float(scale_percent) / 100.0
            op.addOperation(ScaleOperation(node, Vector(factor, factor, factor), scale_around_point=node.getBoundingBox().center))
            has_ops = True
        if has_ops:
            op.push()
        if move_to is not None:
            center = node.getBoundingBox().center
            target = _printer_to_scene_vec([move_to[0], move_to[1], 0])
            TranslateOperation(node, Vector(target.x - center.x, 0, target.z - center.z)).push()
        if move_by is not None:
            d = _printer_to_scene_vec(move_by)
            TranslateOperation(node, d).push()
        if lay_on_plate:
            self._drop_to_plate(node)
        return self._node_info(node)

    def _drop_to_plate(self, node):
        bbox = node.getBoundingBox()
        if bbox is not None and abs(bbox.bottom) > 1e-3:
            TranslateOperation(node, Vector(0, -bbox.bottom, 0)).push()

    def duplicate_for_batch(self, object_id=None, count=1, max_per_run=None, spacing_mm=None):
        return run_on_main(self._duplicate_for_batch, object_id, count, max_per_run, spacing_mm)

    def _duplicate_for_batch(self, object_id, count, max_per_run, spacing_mm):
        """3D batch: copies of an (already oriented) part on one plate, split into equal runs."""
        gs = self._global()
        if gs.getProperty("printing_mode", "value") != "classic":
            raise ToolError("Партия на одном столе возможна только в 3D. В 5D деталь печатается на цилиндрическом "
                            "основании — одна деталь за запуск; посчитай число запусков и общее время.")
        node = self._node(object_id)
        old = [n for n in self._nodes() if n is not node and n.getName() == node.getName()]
        if old:
            op = GroupedOperation()
            for n in old:
                op.addOperation(RemoveSceneNodeOperation(n))
            op.push()
        spacing = float(spacing_mm) if spacing_mm else 10.0
        adhesion = gs.getProperty("adhesion_type", "value")
        try:
            if adhesion == "brim":
                spacing += 2 * float(self._extruder(0).getProperty("brim_width", "value") or 0)
            elif adhesion == "raft":
                spacing += 2 * float(self._extruder(0).getProperty("raft_margin", "value") or 0)
        except Exception:
            pass
        bbox = node.getBoundingBox()
        plan = geometry.plan_batches(count, bbox.width, bbox.depth,
                                     float(gs.getProperty("machine_width", "value")),
                                     float(gs.getProperty("machine_depth", "value")),
                                     margin=10.0, spacing=spacing, max_per_run=max_per_run)
        if not plan.get("max_per_plate"):
            raise ToolError("Деталь %.0f×%.0f мм не помещается на стол с отступами." % (bbox.width, bbox.depth))
        if plan["rotated_90"]:
            RotateOperation(node, Quaternion.fromAngleAxis(math.pi / 2, Vector(0, 1, 0)),
                            rotate_around_point=bbox.center).push()
            bbox = node.getBoundingBox()
        targets = [_printer_to_scene_vec([x, y, 0]) for x, y in plan["positions_mm"]]

        def offset_to(target):
            return Vector(target.x - bbox.center.x, 0, target.z - bbox.center.z)

        op = GroupedOperation()
        build_plate = node.callDecoration("getBuildPlateNumber")
        for target in targets[1:]:
            new_node = copy.deepcopy(node)
            if build_plate is not None:
                new_node.callDecoration("setBuildPlateNumber", build_plate)
            new_node.setPosition(node.getPosition() + offset_to(target))
            op.addOperation(AddSceneNodeOperation(new_node, node.getParent()))
        op.addOperation(TranslateOperation(node, offset_to(targets[0])))
        op.push()
        plan.pop("positions_mm", None)
        plan["objects"] = [self._node_info(n) for n in self._nodes()]
        plan["note"] = ("На столе %d шт. Партия %d шт.: %d запуск(а) по %d шт. (последний — %d). "
                        "После нарезки время и расход — на один запуск." % (
                            plan["per_run"], plan["requested"], plan["runs"], plan["per_run"], plan["last_run"]))
        return plan

    def arrange_all(self):
        run_on_main(self._app.arrangeAll)
        time.sleep(1.0)
        return self.list_objects()

    def _mesh_triangles(self, object_id):
        node = self._node(object_id)
        md = node.getMeshData().getTransformed(node.getWorldTransformation())
        vertices = numpy.array(md.getVertices(), copy=True)
        indices = numpy.array(md.getIndices(), copy=True) if md.hasIndices() else None
        return self._node_id(node), vertices, indices

    def _printer_triangles(self, object_id):
        node_id, vertices, indices = run_on_main(self._mesh_triangles, object_id)
        tri = geometry.triangles_from_mesh(geometry.scene_to_printer(vertices), indices)
        return node_id, tri

    def analyze_model(self, object_id=None):
        node_id, tri = self._printer_triangles(object_id)
        result = geometry.analyze(tri)
        result["object_id"] = node_id
        return result

    def orient(self, object_id=None, target="3d", axis=None):
        node_id, tri = self._printer_triangles(object_id)
        if target == "5d":
            info = geometry.analyze(tri)
            axis = (axis or info.get("revolution_axis") or "Z").upper()
            rotation = geometry.axis_to_vertical_rotation(axis)
            rev = info["revolution_by_axis"].get(axis, {})
            axis_point = numpy.array(rev.get("axis_point_mm", [0.0, 0.0, 0.0]))
            new_axis_point = numpy.dot(rotation, axis_point)
            summary = {"mode": "5d", "axis": axis, "revolution": rev}
        else:
            rotation, metrics, down = geometry.best_flat_orientation(tri)
            new_axis_point = None
            summary = {"mode": "3d", "down_direction": down, "metrics": metrics}
        run_on_main(self._apply_rotation, node_id, rotation, new_axis_point)
        summary["object"] = self.list_objects()["objects"]
        return summary

    def _apply_rotation(self, object_id, rotation_printer, axis_point_printer):
        node = self._node(object_id)
        rs = geometry.rotation_printer_to_scene(rotation_printer)
        m = numpy.identity(4)
        m[:3, :3] = rs
        if not numpy.allclose(rs, numpy.identity(3), atol=1e-6):
            q = Quaternion.fromMatrix(Matrix(m.tolist()))
            RotateOperation(node, q, rotate_around_point=node.getBoundingBox().center).push()
        if axis_point_printer is not None:
            _, vertices, indices = self._mesh_triangles(object_id)
            tri = geometry.triangles_from_mesh(geometry.scene_to_printer(vertices), indices)
            rev = geometry.revolution_analysis(tri, geometry.AXES["Z"])
            px, py = (rev["axis_point_mm"][0], rev["axis_point_mm"][1]) if rev else (0.0, 0.0)
            TranslateOperation(node, _printer_to_scene_vec([-px, -py, 0])).push()
        self._drop_to_plate(node)

    def _hook_backends(self):
        manager = self._app.getBackendManager()
        for backend in list(manager.getBackends().values()):
            key = id(backend)
            if key in self._hooked_backends:
                continue
            self._hooked_backends.add(key)
            backend.backendStateChange.connect(self._onBackendState)
            backend.processingProgress.connect(self._onProgress)

    def _onBackendState(self, state):
        name = STATE_NAMES.get(state, str(state))
        if self._slice_started_at is None:
            self._slice_state = name
            return
        self._slice_state = name
        self._bus.emit("slice_state", state=name)
        if state == BackendState.Done:
            self._slice_done.set()
        elif state == BackendState.Error:
            self._slice_error = "Слайсер сообщил об ошибке (проверьте, что модель внутри области печати и настройки корректны)."
            self._slice_done.set()

    def _onProgress(self, amount):
        self._slice_progress = float(amount)
        if self._slice_started_at is not None:
            self._bus.emit("slice_progress", progress=round(float(amount), 3))

    def _backend_busy(self):
        """What the slicer is still doing; forcing a slice during it kills the engine mid-work."""
        backend = self._app.getBackend()
        busy = {}
        for attr in ("_slicing", "_start_slice_job", "_generate_basement_job", "_process_layers_job"):
            value = getattr(backend, attr, None)
            if value:
                busy[attr] = str(value) if not isinstance(value, bool) else True
        checker = self._app.getMachineErrorChecker()
        if checker is not None and checker.needToWaitForResult:
            busy["error_check"] = True
        return busy

    def _wait_until_idle(self, timeout=90.0, quiet=2.0):
        """Wait until the backend and the setting error checker stay idle for `quiet` seconds.

        The error checker is scheduled on a timer after every setting change and, when it
        finishes, resets the backend; slicing during it crashes CuraEngineBackend
        (KeyError in gcode_dict) or deadlocks the engine restart.
        """
        deadline = time.time() + timeout
        idle_since = None
        busy = {}
        while time.time() < deadline:
            busy = run_on_main(self._backend_busy)
            now = time.time()
            if busy:
                idle_since = None
            elif idle_since is None:
                idle_since = now
            elif now - idle_since >= quiet:
                return {}
            time.sleep(0.25)
        return busy

    def _start_slice(self):
        self._hook_backends()
        if not self._nodes():
            raise ToolError("Нечего слайсить: на столе нет моделей.")
        backend = self._app.getBackend()
        process = getattr(backend, "_process", None)
        if backend.getPluginId() == "CuraEngineBackend" and process is not None and process.poll() is not None:
            Logger.log("d", "AIAssistant: engine of %s exited (%s), restarting it", backend.getPluginId(), process.returncode)
            backend._process = None
        Logger.log("d", "AIAssistant: forceSlice on %s, busy=%s", backend.getPluginId(), self._backend_busy())
        self._slice_done.clear()
        self._slice_cancel.clear()
        self._slice_error = None
        self._slice_progress = 0.0
        self._slice_started_at = time.time()
        self._slice_state = "processing"
        self._bus.emit("slice_state", state="processing", backend=backend.getPluginId())
        backend.forceSlice()
        return backend.getPluginId()

    def slice(self, timeout=900):
        with self._slice_lock:
            still_busy = self._wait_until_idle()
            if still_busy:
                Logger.log("w", "AIAssistant: backend still busy before slicing: %s", still_busy)
            backend_id = run_on_main(self._start_slice)
            try:
                self._wait_for_slice(timeout)
            finally:
                started = self._slice_started_at
                self._slice_started_at = None
            if self._slice_error:
                raise ToolError(self._slice_error)
            time.sleep(0.5)
            result = self.slice_result()
            self._needs_slice = False
            result["backend"] = backend_id
            result["slicing_seconds"] = round(time.time() - started, 1)
            self._bus.emit("slice_result", **result)
            return result

    def _wait_for_slice(self, timeout, idle_abort=5.0):
        """Wait for Done/Error. Gives up early when the user stops the agent, or when the slice was
        cancelled in the slicer (state back to not_started and the backend idle for `idle_abort` s)."""
        deadline = time.time() + timeout
        idle_since = None
        while not self._slice_done.wait(1.0):
            if self._slice_cancel.is_set():
                raise ToolError("Слайсинг остановлен пользователем.")
            now = time.time()
            if now > deadline:
                raise ToolError("Слайсинг не завершился за %d с. Для 5D проверьте, что активирована лицензия ATSS." % timeout)
            if self._slice_state in ("not_started", "disabled") and not run_on_main(self._backend_busy):
                if idle_since is None:
                    idle_since = now
                elif now - idle_since >= idle_abort:
                    if self._slice_state == "disabled":
                        raise ToolError("Слайсинг недоступен: бэкенд отключён. Для 5D проверьте лицензию ATSS.")
                    raise ToolError("Слайсинг прерван: его отменили в слайсере или изменилась сцена. Запустите slice ещё раз.")
            else:
                idle_since = None

    def cancel_slice(self):
        """Stop a slice started by the agent (called from the chat's Stop button)."""
        if self._slice_started_at is None:
            return False
        self._slice_cancel.set()
        try:
            run_on_main(lambda: self._app.getBackend().stopSlicing(), timeout=10)
        except Exception:
            Logger.logException("w", "AIAssistant: stopSlicing failed")
        return True

    VARIANT_PRESETS = [
        ("прочно", {"wall_line_count": 5, "top_layers": 6, "bottom_layers": 6, "infill_sparse_density": 60}),
        ("быстро", {"layer_height": 0.25, "wall_line_count": 2, "infill_sparse_density": 15}),
        ("экономно", {"wall_line_count": 2, "top_layers": 3, "bottom_layers": 3, "infill_sparse_density": 10}),
    ]

    def _snapshot_user_changes(self):
        gs = self._global()
        snapshot = {}
        for stack in [gs] + list(gs.extruders.values()):
            snapshot[stack.getId()] = dict((key, stack.userChanges.getProperty(key, "value"))
                                           for key in stack.userChanges.getAllKeys())
        return snapshot

    def _restore_user_changes(self, snapshot):
        gs = self._global()
        for stack in [gs] + list(gs.extruders.values()):
            wanted = snapshot.get(stack.getId(), {})
            for key in list(stack.userChanges.getAllKeys()):
                if key not in wanted:
                    stack.userChanges.removeInstance(key)
            for key, value in wanted.items():
                stack.userChanges.setProperty(key, "value", value)

    def _variant_values(self, values):
        """In 5D the layer height has its own key; drop keys this printer does not have."""
        gs = self._global()
        five_axis = gs.getProperty("printing_mode", "value") != "classic"
        result, skipped = {}, []
        for key, value in values.items():
            if five_axis and key == "layer_height" and gs.definition.findDefinitions(key="cylindrical_layer_height"):
                key = "cylindrical_layer_height"
            if gs.definition.findDefinitions(key=key):
                result[key] = value
            else:
                skipped.append(key)
        return result, skipped

    def compare_variants(self, variants=None, apply=None):
        """Slice the scene with 2-3 setting variants on top of the current settings, compare print time
        and material, then restore the settings (or keep the variant named in `apply`)."""
        if not run_on_main(self._nodes):
            raise ToolError("На столе нет моделей. Сначала загрузите модель (load_model).")
        if not variants:
            variants = [{"name": name, "settings": dict(values)} for name, values in self.VARIANT_PRESETS]
        if not isinstance(variants, list) or not 2 <= len(variants) <= 3:
            raise ToolError("Нужно 2–3 варианта: [{name, settings: {ключ: значение}}]")
        snapshot = run_on_main(self._snapshot_user_changes)
        rows, applied = [], None
        try:
            for variant in variants:
                name = str(variant.get("name") or "вариант %d" % (len(rows) + 1))
                values, skipped = run_on_main(self._variant_values, dict(variant.get("settings") or {}))
                run_on_main(self._restore_user_changes, snapshot)
                change = run_on_main(self._set_settings, values, None)
                row = {"name": name, "settings": change.get("applied", {})}
                if change.get("rejected"):
                    row["rejected"] = change["rejected"]
                if skipped:
                    row["skipped"] = skipped
                try:
                    result = self.slice()
                    row.update({"print_time": result["print_time"], "print_time_seconds": result["print_time_seconds"],
                                "material_total_g": result["material_total_g"]})
                except ToolError as e:
                    row["error"] = str(e)
                rows.append(row)
        finally:
            run_on_main(self._restore_user_changes, snapshot)
            if apply:
                chosen = [v for v in variants if str(v.get("name")) == str(apply)]
                if chosen:
                    values, _skipped = run_on_main(self._variant_values, dict(chosen[0].get("settings") or {}))
                    run_on_main(self._set_settings, values, None)
                    applied = str(apply)
        ok = [r for r in rows if "error" not in r]
        self._needs_slice = True
        summary = {"variants": rows, "applied": applied, "needs_slice": True,
                   "note": ("Настройки возвращены к исходным. " if not applied else "Применён вариант «%s». " % applied)
                           + "G-code сброшен: перед export_gcode/save_project снова вызови slice."}
        if ok:
            summary["fastest"] = min(ok, key=lambda r: r["print_time_seconds"])["name"]
            summary["lightest"] = min(ok, key=lambda r: r["material_total_g"])["name"]
        return summary

    def slice_status(self):
        status = {"state": self._slice_state, "progress": round(self._slice_progress, 3)}
        if self._slice_started_at is not None:
            status["running_s"] = round(time.time() - self._slice_started_at, 1)
            try:
                status["backend_busy"] = run_on_main(self._backend_busy, timeout=5)
            except Exception:
                pass
        return status

    def slice_result(self):
        return run_on_main(self._slice_result)

    def _slice_result(self):
        info = self._app.getPrintInformation()
        duration = info.currentPrintTime
        seconds = int(duration) if duration is not None and duration.valid else 0
        raw_lengths = list(info.materialLengths or [])
        raw_weights = list(info.materialWeights or [])
        gs = self._global()
        amounts = getattr(info, "_material_amounts", None)
        positions = [p for p in gs.extruders if amounts is None or int(p) < len(amounts)]
        if len(positions) != len(raw_weights):
            positions = sorted(gs.extruders.keys(), key=int)[:len(raw_weights)]
        by_position = dict(zip(positions, zip(raw_lengths, raw_weights)))
        ordered = sorted(by_position.keys(), key=int)
        lengths = [round(float(by_position[p][0]), 3) for p in ordered]
        weights = [round(float(by_position[p][1]), 1) for p in ordered]
        scene = self._app.getController().getScene()
        has_gcode = bool(getattr(scene, "gcode_dict", {}).get(self._app.getMultiBuildPlateModel().activeBuildPlate))
        names = {"0": "основной экструдер", "1": "второй экструдер"}
        return {
            "state": self._slice_state,
            "print_time_seconds": seconds,
            "print_time": "%d ч %02d мин" % (seconds // 3600, (seconds % 3600) // 60),
            "material_length_m": lengths,
            "material_weight_g": weights,
            "material_total_g": round(sum(weights), 1),
            "by_extruder": [{"extruder": names.get(p, "экструдер %s" % p), "material": gs.extruders[p].material.getName(),
                             "length_m": round(float(by_position[p][0]), 3), "weight_g": round(float(by_position[p][1]), 1)}
                            for p in ordered if by_position[p][1] > 0],
            "gcode_ready": has_gcode,
        }

    def export_gcode(self, path):
        if self._needs_slice:
            raise ToolError("После compare_variants G-code относится к тестовому варианту. Сначала вызови slice "
                            "с итоговыми настройками, затем export_gcode.")
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        writer = PluginRegistry.getInstance().getPluginObject("GCodeWriter")
        with open(path, "w", encoding="utf-8") as stream:
            ok = writer.write(stream, None, MeshWriter.OutputMode.TextMode)
        if not ok:
            raise ToolError("G-code не готов: сначала выполните слайсинг (%s)" % writer.getInformation())
        return {"path": path, "size_kb": round(os.path.getsize(path) / 1024.0, 1)}

    def save_project(self, path):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        writer = self._app.getWorkspaceFileHandler().getWriter("3MFWriter")
        if writer is None:
            raise ToolError("Плагин 3MFWriter недоступен")
        root = self._app.getController().getScene().getRoot()
        with open(path, "wb") as stream:
            ok = writer.write(stream, [root])
        if not ok:
            raise ToolError("Не удалось записать проект 3MF")
        return {"path": path, "size_kb": round(os.path.getsize(path) / 1024.0, 1)}

    def set_job_name(self, name):
        run_on_main(lambda: self._app.getPrintInformation().setJobName(name, is_user_specified_job_name=True))
