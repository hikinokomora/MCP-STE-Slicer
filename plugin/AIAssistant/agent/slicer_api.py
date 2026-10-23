"""Thin, thread-aware facade over the STE Slicer (Cura 3.6) API.

Methods without a leading underscore are safe to call from worker threads:
everything that touches the scene, the stacks or the backend is marshalled
to the Qt main thread through run_on_main.
"""
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
    # printer (x, y, z_up) -> scene (x, y_up, z)
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
        self._hooked_backends = set()

    # ------------------------------------------------------------------ helpers
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
        if extruder is not None:
            return self._extruder(extruder)
        if gs.getProperty(key, "settable_per_extruder"):
            return self._extruder(0)
        return gs

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

    # ------------------------------------------------------------------ scene
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
        return info

    # ------------------------------------------------------------------ profiles
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
        return {"quality_type": mm.activeQualityType, "profile_name": mm.activeQualityOrQualityChangesName}

    def create_profile(self, name):
        return run_on_main(self._create_profile, name)

    def _create_profile(self, name):
        gs = self._global()
        qm = self._app.getQualityManager()
        mm = self._app.getMachineManager()
        qm.createQualityChanges(name)
        groups = qm.getQualityChangesGroups(gs)
        created = None
        for group_name in groups:
            if group_name == name or group_name.startswith(name):
                created = group_name
        if created:
            mm.setQualityChangesGroup(groups[created], no_dialog=True)
        return {"created": created or name, "active_profile": mm.activeQualityOrQualityChangesName,
                "note": "Текущие изменения настроек сохранены в пользовательский профиль и он активирован."}

    # ------------------------------------------------------------------ materials
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

    # ------------------------------------------------------------------ settings
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

    # ------------------------------------------------------------------ print mode
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

    # ------------------------------------------------------------------ models
    def load_model(self, path, extruder=0, timeout=120):
        if not os.path.isfile(path):
            raise ToolError("Файл не найден: %s" % path)
        before = set(run_on_main(lambda: [self._node_id(n) for n in self._nodes()]))
        run_on_main(lambda: self._app.readLocalFile(QUrl.fromLocalFile(path), True))
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            new = run_on_main(lambda: [n for n in self._nodes() if self._node_id(n) not in before])
            if new:
                time.sleep(0.5)  # let platform physics drop the model onto the plate

                def finish():
                    nodes = [n for n in self._nodes() if self._node_id(n) not in before]
                    for node in nodes:
                        # a new model takes the extruder selected in the UI; pin it to the requested one
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

    def arrange_all(self):
        run_on_main(self._app.arrangeAll)
        time.sleep(1.0)
        return self.list_objects()

    # ------------------------------------------------------------------ geometry
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
            # re-read the axis position from the rotated mesh and put it on the machine axis (X=0, Y=0)
            _, vertices, indices = self._mesh_triangles(object_id)
            tri = geometry.triangles_from_mesh(geometry.scene_to_printer(vertices), indices)
            rev = geometry.revolution_analysis(tri, geometry.AXES["Z"])
            px, py = (rev["axis_point_mm"][0], rev["axis_point_mm"][1]) if rev else (0.0, 0.0)
            TranslateOperation(node, _printer_to_scene_vec([-px, -py, 0])).push()
        self._drop_to_plate(node)

    # ------------------------------------------------------------------ slicing
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
        Logger.log("d", "AIAssistant: forceSlice on %s, busy=%s", backend.getPluginId(), self._backend_busy())
        self._slice_done.clear()
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
            finished = self._slice_done.wait(timeout)
            started = self._slice_started_at
            self._slice_started_at = None
            if not finished:
                raise ToolError("Слайсинг не завершился за %s с. Для 5D проверьте лицензию ATSS." % timeout)
            if self._slice_error:
                raise ToolError(self._slice_error)
            time.sleep(0.5)  # print information arrives right after the Done state
            result = self.slice_result()
            result["backend"] = backend_id
            result["slicing_seconds"] = round(time.time() - started, 1)
            self._bus.emit("slice_result", **result)
            return result

    def slice_status(self):
        return {"state": self._slice_state, "progress": round(self._slice_progress, 3)}

    def slice_result(self):
        return run_on_main(self._slice_result)

    def _slice_result(self):
        info = self._app.getPrintInformation()
        duration = info.currentPrintTime
        seconds = int(duration) if duration is not None and duration.valid else 0
        lengths = [round(float(x), 3) for x in (info.materialLengths or [])]
        weights = [round(float(x), 1) for x in (info.materialWeights or [])]
        scene = self._app.getController().getScene()
        has_gcode = bool(getattr(scene, "gcode_dict", {}).get(self._app.getMultiBuildPlateModel().activeBuildPlate))
        return {
            "state": self._slice_state,
            "print_time_seconds": seconds,
            "print_time": "%d ч %02d мин" % (seconds // 3600, (seconds % 3600) // 60),
            "material_length_m": lengths,
            "material_weight_g": weights,
            "material_total_g": round(sum(weights), 1),
            "gcode_ready": has_gcode,
        }

    # ------------------------------------------------------------------ export
    def export_gcode(self, path):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Like Cura's WriteFileJob, writers run off the main thread: GCodeWriter renders its
        # preview through @call_on_qt_thread and would deadlock if called from main.
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
        # ThreeMFWorkspaceWriter.write is @call_on_qt_thread: it posts itself to the main
        # thread and waits, so it must be called from this worker thread, never from main.
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
