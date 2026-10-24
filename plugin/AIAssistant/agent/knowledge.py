# -*- coding: utf-8 -*-
"""Engineering knowledge the agent relies on instead of the LLM's memory.

MATERIALS holds typical datasheet values for the materials shipped with STE Slicer
(ids are the root material ids of the slicer). Printing temperatures are NOT stored
here: they come from the slicer's own material profiles.
"""
from collections import OrderedDict

# Ratings: 0 = poor, 1 = limited, 2 = good, 3 = excellent
MATERIALS = OrderedDict([
    ("proto_pla", {
        "name": "Proto PLA", "base": "PLA", "density": 1.25, "tg_c": 58, "hdt_c": 55,
        "tensile_modulus_mpa": 3300, "tensile_strength_mpa": 55, "elongation_pct": 5, "water_absorption_pct": 0.5,
        "uv": 1, "oils_fuels": 1, "alkali": 0, "acids": 1, "alcohol_ipa": 1, "abrasion": 1, "flexible": False,
        "food_contact": False, "esd": False, "notes": "Прототипы и декор; размягчается выше 55 °C."}),
    ("enduse_petg", {
        "name": "Enduse PETG", "base": "PETG", "density": 1.3, "tg_c": 80, "hdt_c": 70,
        "tensile_modulus_mpa": 2000, "tensile_strength_mpa": 50, "elongation_pct": 20, "water_absorption_pct": 0.15,
        "uv": 1, "oils_fuels": 2, "alkali": 1, "acids": 2, "alcohol_ipa": 2, "abrasion": 1, "flexible": False,
        "food_contact": False, "esd": False, "notes": "Ударопрочный, хорошая межслойная адгезия, малая усадка; корпуса и держатели."}),
    ("enduse_abs", {
        "name": "Enduse ABS", "base": "ABS", "density": 1.05, "tg_c": 105, "hdt_c": 95,
        "tensile_modulus_mpa": 2100, "tensile_strength_mpa": 40, "elongation_pct": 10, "water_absorption_pct": 0.3,
        "uv": 0, "oils_fuels": 1, "alkali": 2, "acids": 1, "alcohol_ipa": 1, "abrasion": 1, "flexible": False,
        "food_contact": False, "esd": False, "notes": "Корпуса и оснастка; НЕ стоек к УФ и высокой влажности; склонен к короблению (нужен brim)."}),
    ("enduse_pc", {
        "name": "Enduse PC", "base": "PC", "density": 1.2, "tg_c": 147, "hdt_c": 130,
        "tensile_modulus_mpa": 2300, "tensile_strength_mpa": 62, "elongation_pct": 8, "water_absorption_pct": 0.15,
        "uv": 1, "oils_fuels": 1, "alkali": 0, "acids": 2, "alcohol_ipa": 1, "abrasion": 1, "flexible": False,
        "food_contact": False, "esd": False, "notes": "Термостойкий и прочный; гидролизуется в щелочах и горячей воде."}),
    ("enduse_pa6", {
        "name": "Enduse PA6", "base": "PA6", "density": 1.05, "tg_c": 55, "hdt_c": 75,
        "tensile_modulus_mpa": 1800, "tensile_strength_mpa": 50, "elongation_pct": 40, "water_absorption_pct": 2.5,
        "uv": 1, "oils_fuels": 3, "alkali": 2, "acids": 1, "alcohol_ipa": 2, "abrasion": 3, "flexible": False,
        "food_contact": False, "esd": False, "low_friction": True, "melting_c": 220,
        "notes": "Износостойкий, самосмазывающийся, для пар трения и элементов скольжения (втулки, направляющие); гигроскопичен."}),
    ("enduse_pp", {
        "name": "Enduse PP", "base": "PP", "density": 0.9, "tg_c": -10, "hdt_c": 90,
        "tensile_modulus_mpa": 1300, "tensile_strength_mpa": 30, "elongation_pct": 150, "water_absorption_pct": 0.01,
        "uv": 1, "oils_fuels": 1, "alkali": 3, "acids": 3, "alcohol_ipa": 3, "abrasion": 2, "flexible": False,
        "food_contact": True, "esd": False, "low_friction": True,
        "notes": "Химстойкий, усталостно-стойкий (живые шарниры), пластичный, но не эластомер; низкая жёсткость."}),
    ("enduse_sbs", {
        "name": "Enduse SBS", "base": "SBS", "density": 1.01, "tg_c": 75, "hdt_c": 70,
        "tensile_modulus_mpa": 1500, "tensile_strength_mpa": 26, "elongation_pct": 30, "water_absorption_pct": 0.1,
        "uv": 1, "oils_fuels": 0, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 1, "flexible": False,
        "food_contact": True, "esd": False, "notes": "Допуск к контакту с пищей; ударопрочные корпуса и тактильные изделия."}),
    ("enduse_tpu_d70", {
        "name": "Enduse TPU D70", "base": "TPU (Shore 70D)", "density": 1.23, "tg_c": -30, "hdt_c": 80,
        "tensile_modulus_mpa": 600, "tensile_strength_mpa": 45, "elongation_pct": 300, "water_absorption_pct": 0.3,
        "uv": 2, "oils_fuels": 3, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 3, "flexible": False,
        "food_contact": False, "esd": False, "high_friction": True,
        "notes": "Полужёсткий полиуретан (Shore 70D, не резина): ролики, манжеты подвижных соединений, износостойкие "
                 "накладки; маслобензостойкий. Для пыльников и сильфонов слишком жёсткий."}),
    ("fiberpart_abs_g4", {
        "name": "Fiberpart ABS G4", "base": "ABS + 4% стекловолокна", "density": 1.1, "tg_c": 105, "hdt_c": 98,
        "tensile_modulus_mpa": 2600, "tensile_strength_mpa": 42, "elongation_pct": 5, "water_absorption_pct": 0.3,
        "uv": 0, "oils_fuels": 1, "alkali": 2, "acids": 1, "alcohol_ipa": 1, "abrasion": 1, "flexible": False,
        "food_contact": False, "esd": False, "notes": "Функциональные детали; шероховатая поверхность."}),
    ("fiberpart_abs_g13", {
        "name": "Fiberpart ABS G13", "base": "ABS + 13% стекловолокна", "density": 1.15, "tg_c": 108, "hdt_c": 105,
        "tensile_modulus_mpa": 4000, "tensile_strength_mpa": 50, "elongation_pct": 3, "water_absorption_pct": 0.3,
        "uv": 0, "oils_fuels": 1, "alkali": 2, "acids": 1, "alcohol_ipa": 1, "abrasion": 2, "flexible": False,
        "food_contact": False, "esd": False,
        "notes": "Ровная поверхность без выраженных слоёв, малая усадка, хорошо шлифуется; не стоек к УФ."}),
    ("fiberpart_abspa_g8", {
        "name": "Fiberpart ABSPA G8", "base": "ABS/PA + стекловолокно", "density": 1.12, "tg_c": 110, "hdt_c": 110,
        "tensile_modulus_mpa": 3500, "tensile_strength_mpa": 55, "elongation_pct": 4, "water_absorption_pct": 0.6,
        "uv": 2, "oils_fuels": 2, "alkali": 2, "acids": 2, "alcohol_ipa": 2, "abrasion": 2, "flexible": False,
        "food_contact": False, "esd": False,
        "notes": "Ударопрочный, стойкий к УФ, инертен к большинству растворителей."}),
    ("fiberpart_pa12_g12", {
        "name": "Fiberpart PA12 G12", "base": "PA12 + 12% стекловолокна", "density": 1.05, "tg_c": 50, "hdt_c": 150,
        "tensile_modulus_mpa": 3500, "tensile_strength_mpa": 60, "elongation_pct": 6, "water_absorption_pct": 0.25,
        "uv": 2, "oils_fuels": 3, "alkali": 3, "acids": 1, "alcohol_ipa": 3, "abrasion": 3, "flexible": False,
        "food_contact": False, "esd": False,
        "notes": "Термо- и износостойкий, держит циклические нагрузки, маслостойкий, лёгкий; стекловолокно абразивно для ответных пластиковых деталей."}),
    ("fiberpart_pc_g20", {
        "name": "Fiberpart PC G20", "base": "PC + 20% стекловолокна", "density": 1.18, "tg_c": 147, "hdt_c": 145,
        "tensile_modulus_mpa": 6000, "tensile_strength_mpa": 80, "elongation_pct": 2.5, "water_absorption_pct": 0.12,
        "uv": 1, "oils_fuels": 2, "alkali": 0, "acids": 2, "alcohol_ipa": 1, "abrasion": 2, "flexible": False,
        "food_contact": False, "esd": False,
        "notes": "Очень жёсткий и прочный, широкий диапазон температур; поликарбонат разрушается в щелочах."}),
    ("fiberpart_pp_g30", {
        "name": "Fiberpart PP G30", "base": "PP + 30% стекловолокна", "density": 1.18, "tg_c": -10, "hdt_c": 145,
        "vicat_c": 150, "tensile_modulus_mpa": 5500, "tensile_strength_mpa": 70, "elongation_pct": 3,
        "water_absorption_pct": 0.02, "uv": 1, "oils_fuels": 2, "alkali": 3, "acids": 3, "alcohol_ipa": 3, "abrasion": 2,
        "flexible": False, "food_contact": False, "esd": False, "creep_resistant": True,
        "notes": "Гидролизостоек, устойчив к горячему тосолу/гликолю, кислотам и щелочам; диэлектрик; жёсткий и лёгкий."}),
    ("fiberpart_tpu_c5", {
        "name": "Fiberpart TPU C5", "base": "TPU + углеволокно", "density": 1.16, "tg_c": -30, "hdt_c": 90,
        "tensile_modulus_mpa": 900, "tensile_strength_mpa": 45, "elongation_pct": 150, "water_absorption_pct": 0.3,
        "uv": 2, "oils_fuels": 3, "alkali": 2, "acids": 2, "alcohol_ipa": 2, "abrasion": 3, "flexible": False,
        "food_contact": False, "esd": False, "high_friction": True,
        "notes": "Полужёсткий износостойкий полиуретан с углеволокном; шестерни, ролики, нагруженные детали. "
                 "Антистатические свойства производителем не заявлены."}),
    ("fiberpart_tpu_g30", {
        "name": "Fiberpart TPU G30", "base": "твёрдый TPU + 30% стекловолокна", "density": 1.45, "tg_c": -20, "hdt_c": 120,
        "tensile_modulus_mpa": 2500, "tensile_strength_mpa": 55, "elongation_pct": 20, "water_absorption_pct": 0.3,
        "uv": 2, "oils_fuels": 3, "alkali": 2, "acids": 2, "alcohol_ipa": 2, "abrasion": 3, "flexible": False,
        "food_contact": False, "esd": False,
        "notes": "Крупные шестерни, ударопрочные корпуса, нагруженные детали; тяжёлый."}),
    ("sealant_tpu", {
        "name": "Sealant TPU", "base": "TPU (гибкий)", "density": 1.15, "tg_c": -40, "hdt_c": 60,
        "tensile_modulus_mpa": 30, "tensile_strength_mpa": 35, "elongation_pct": 500, "water_absorption_pct": 0.5,
        "uv": 2, "oils_fuels": 3, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 3, "flexible": True,
        "food_contact": False, "esd": False, "notes": "Уплотнения и гибкие элементы; масло- и топливостойкий."}),
    ("sealant_tpu_A95", {
        "name": "Sealant TPU A95", "base": "TPU Shore 95A", "density": 1.15, "tg_c": -40, "hdt_c": 60,
        "tensile_modulus_mpa": 40, "tensile_strength_mpa": 40, "elongation_pct": 550, "water_absorption_pct": 0.8,
        "uv": 2, "oils_fuels": 3, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 3, "flexible": True,
        "food_contact": False, "esd": False, "notes": "Гибкий, очень прочный на разрыв; гигроскопичен."}),
    ("sealant_tpu93", {
        "name": "Sealant TPU93", "base": "TPU Shore 93A", "density": 1.13, "tg_c": -40, "hdt_c": 55,
        "tensile_modulus_mpa": 25, "tensile_strength_mpa": 30, "elongation_pct": 550, "water_absorption_pct": 0.8,
        "uv": 2, "oils_fuels": 3, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 3, "flexible": True,
        "food_contact": False, "esd": False, "notes": "Повышенная гибкость; уплотнения, прокладки."}),
    ("sealant_tpv80", {
        "name": "Sealant TPV80", "base": "TPV (EPDM/PP), Shore 80A", "density": 1.13, "tg_c": -50, "hdt_c": 100,
        "tensile_modulus_mpa": 15, "tensile_strength_mpa": 8, "elongation_pct": 400, "water_absorption_pct": 0.05,
        "uv": 3, "oils_fuels": 3, "alkali": 3, "acids": 3, "alcohol_ipa": 3, "abrasion": 2, "flexible": True,
        "food_contact": False, "esd": False,
        "notes": "Резиноподобный, жиро-, масло-, бензостойкий, озоно- и солестойкий; химстойкие уплотнения, пыльники, патрубки."}),
    ("sealant_tpe", {
        "name": "Sealant TPE", "base": "TPE", "density": 1.1, "tg_c": -50, "hdt_c": 60,
        "tensile_modulus_mpa": 10, "tensile_strength_mpa": 10, "elongation_pct": 600, "water_absorption_pct": 0.1,
        "uv": 2, "oils_fuels": 1, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 1, "flexible": True,
        "food_contact": False, "esd": False, "notes": "Мягкий, как силикон; кнопки, прокладки; может содержать пластификаторы."}),
    ("sealant_sebs", {
        "name": "Sealant SEBS", "base": "SEBS (каучук)", "density": 0.95, "tg_c": -60, "hdt_c": 60,
        "tensile_modulus_mpa": 5, "tensile_strength_mpa": 8, "elongation_pct": 600, "water_absorption_pct": 0.05,
        "uv": 2, "oils_fuels": 0, "alkali": 2, "acids": 2, "alcohol_ipa": 1, "abrasion": 1, "flexible": True,
        "food_contact": False, "esd": False, "notes": "Резиноподобный: кнопки, уплотнители, амортизаторы; не маслостойкий."}),
])

# Stiffness class and maximum continuous service temperature (typical datasheet values).
#   elastic    — elastomers (Shore A, modulus < ~100 MPa): boots, bellows, seals, gaskets;
#   semi_rigid — hard TPU (Shore D, 100–1000 MPa): rollers, cuffs, gears that must not crack;
#   rigid      — engineering plastics and composites.
# For elastomers HDT is meaningless, so heat resistance is checked against service_temp_c.
_EXTRA = {
    "proto_pla": {"stiffness": "rigid", "service_temp_c": 50, "melting_c": 155},
    "enduse_petg": {"stiffness": "rigid", "service_temp_c": 65},
    "enduse_abs": {"stiffness": "rigid", "service_temp_c": 85},
    "enduse_pc": {"stiffness": "rigid", "service_temp_c": 115},
    "enduse_pa6": {"stiffness": "rigid", "service_temp_c": 80},
    "enduse_pp": {"stiffness": "rigid", "service_temp_c": 90, "melting_c": 165},
    "enduse_sbs": {"stiffness": "rigid", "service_temp_c": 65},
    "enduse_tpu_d70": {"stiffness": "semi_rigid", "service_temp_c": 90, "hardness": "Shore 70D", "melting_c": 200},
    "fiberpart_abs_g4": {"stiffness": "rigid", "service_temp_c": 90, "abrasive_filler": True},
    "fiberpart_abs_g13": {"stiffness": "rigid", "service_temp_c": 95, "abrasive_filler": True},
    "fiberpart_abspa_g8": {"stiffness": "rigid", "service_temp_c": 100, "abrasive_filler": True},
    "fiberpart_pa12_g12": {"stiffness": "rigid", "service_temp_c": 110, "abrasive_filler": True, "melting_c": 178},
    "fiberpart_pc_g20": {"stiffness": "rigid", "service_temp_c": 120, "abrasive_filler": True},
    "fiberpart_pp_g30": {"stiffness": "rigid", "service_temp_c": 110, "abrasive_filler": True, "melting_c": 165},
    "fiberpart_tpu_c5": {"stiffness": "semi_rigid", "service_temp_c": 90, "melting_c": 190},
    "fiberpart_tpu_g30": {"stiffness": "rigid", "service_temp_c": 100, "abrasive_filler": True, "melting_c": 200},
    "sealant_tpu": {"stiffness": "elastic", "service_temp_c": 80, "high_friction": True, "melting_c": 180},
    "sealant_tpu_A95": {"stiffness": "elastic", "service_temp_c": 80, "hardness": "Shore 95A", "high_friction": True, "melting_c": 180},
    "sealant_tpu93": {"stiffness": "elastic", "service_temp_c": 80, "hardness": "Shore 93A", "high_friction": True, "melting_c": 180},
    "sealant_tpv80": {"stiffness": "elastic", "service_temp_c": 120, "hardness": "Shore 80A", "high_friction": True, "melting_c": 165},
    "sealant_tpe": {"stiffness": "elastic", "service_temp_c": 70},
    "sealant_sebs": {"stiffness": "elastic", "service_temp_c": 70},
}
for _mid, _extra in _EXTRA.items():
    MATERIALS[_mid].update(_extra)
    # glass fibres stick out of the surface and file down a polymer counterpart (rollers, bushings, shafts)
    MATERIALS[_mid].setdefault("abrasive_filler", False)
    # "flexible" means a true elastomer; ductile plastics (PP) and hard TPU are not flexible
    MATERIALS[_mid]["flexible"] = _extra["stiffness"] == "elastic"
assert set(_EXTRA) == set(MATERIALS), "every material needs a stiffness class and service temperature"

# Stereotech materials of the slicer that are deliberately NOT in the knowledge base.
EXCLUDED_MATERIALS = {
    "contifiber_cpa": "непрерывное углеволокно — только армирование вторым экструдером в 5D, не основной материал",
    "metalcast_316l": "металлонаполненный филамент — нужна отгонка связующего и спекание, не для прямой печати детали",
    "metalcast_al99": "керамика — нужна отгонка связующего и спекание, не для прямой печати детали",
    "proto_pva": "водорастворимый материал поддержек",
}

RATING_KEYS = ("uv", "oils_fuels", "alkali", "acids", "alcohol_ipa", "abrasion")

REQUIREMENT_FIELDS = {
    "min_glass_or_service_temp_c": "max(tg_c, hdt_c, service_temp_c) >= value",
    "min_service_temp_c": "service_temp_c >= value (длительная рабочая температура)",
    "min_hdt_c": "max(hdt_c, vicat_c) >= value (только для жёстких материалов)",
    "min_melting_c": "кратковременный контакт с горячим: melting_c (у аморфных — max(tg_c, hdt_c)) >= value",
    "max_density": "density <= value",
    "max_water_absorption_pct": "water_absorption_pct <= value",
    "min_tensile_modulus_mpa": "tensile_modulus_mpa >= value",
    "max_tensile_modulus_mpa": "tensile_modulus_mpa <= value",
    "min_tensile_strength_mpa": "tensile_strength_mpa >= value",
    "min_elongation_pct": "elongation_pct >= value",
    "uv": "rating >= value (0..3)", "oils_fuels": "rating", "alkali": "rating", "acids": "rating",
    "alcohol_ipa": "rating", "abrasion": "rating",
    "elastic": "true — только эластомеры (пыльники, сильфоны, уплотнения); false — не эластомеры",
    "flexible": "синоним elastic",
    "stiffness": "elastic / semi_rigid / rigid",
    "food_contact": "true", "esd": "true", "low_friction": "true", "high_friction": "true",
    "non_abrasive": "true — без абразивного наполнителя (стекловолокна): деталь скользит по ответной полимерной детали",
}


def score_materials(requirements, available_ids=None):
    """Filter/rank materials against numeric and rating requirements.

    Returns a list sorted by: number of failed requirements, then rating margin over the requirements,
    then (for elastic parts) the softer material first, then the material id — so equal candidates
    always come out in the same order."""
    requirements = dict(requirements or {})
    if "flexible" in requirements and "elastic" not in requirements:
        requirements["elastic"] = requirements.pop("flexible")
    want_elastic = bool(requirements.get("elastic")) or requirements.get("stiffness") == "elastic"
    results, unknown = [], []
    for key in requirements:
        if key not in REQUIREMENT_FIELDS:
            unknown.append(key)
    for mid, m in MATERIALS.items():
        if available_ids is not None and mid not in available_ids:
            continue
        failed, passed = [], []
        deficit = 0.0  # how badly the failed requirements are missed, 0..1 per requirement
        for key, want in requirements.items():
            if want is None or key in unknown:
                continue
            ok = True
            have = None
            if key == "min_glass_or_service_temp_c":
                have = max(m.get("tg_c", 0), m.get("hdt_c", 0), m.get("service_temp_c", 0))
            elif key == "min_service_temp_c":
                have = m["service_temp_c"]
            elif key == "min_hdt_c":
                # HDT is not defined for elastomers: compare their service temperature instead
                have = m["service_temp_c"] if m["stiffness"] == "elastic" else max(m.get("hdt_c", 0), m.get("vicat_c", 0))
            elif key == "min_melting_c":
                # amorphous plastics have no melting point: they soften around Tg/HDT
                have = m.get("melting_c") or max(m.get("tg_c", 0), m.get("hdt_c", 0))
            elif key in ("min_tensile_modulus_mpa", "min_tensile_strength_mpa", "min_elongation_pct"):
                have = m[key[4:]]
            elif key in ("max_density", "max_water_absorption_pct", "max_tensile_modulus_mpa"):
                have = m[key[4:]]
            if have is not None:
                if key.startswith("max_"):
                    ok = have <= want
                    miss = (have - want) / float(want) if want else 1.0
                else:
                    ok = have >= want
                    miss = (want - have) / float(abs(want)) if want else 1.0
            elif key in RATING_KEYS:
                ok = m.get(key, 0) >= int(want)
                miss = (int(want) - m.get(key, 0)) / 3.0
            elif key == "elastic":
                ok = (m["stiffness"] == "elastic") == bool(want)
                miss = 1.0
            elif key == "stiffness":
                ok = m["stiffness"] == want
                miss = 0.5 if "semi_rigid" in (want, m["stiffness"]) else 1.0
            elif key in ("food_contact", "esd", "low_friction", "high_friction"):
                ok = bool(m.get(key, False)) == bool(want)
                miss = 1.0
            elif key == "non_abrasive":
                ok = (not m["abrasive_filler"]) == bool(want)
                miss = 1.0
            else:
                continue
            (passed if ok else failed).append(key)
            if not ok:
                deficit += min(1.0, max(0.0, miss))
        # how far above the required ratings the material is (ties are broken by real margin, not dict order)
        margin = sum(m.get(k, 0) - int(requirements[k]) for k in RATING_KEYS
                     if requirements.get(k) is not None and k not in unknown)
        props = {k: m[k] for k in ("stiffness", "hardness", "service_temp_c", "tg_c", "hdt_c", "density",
                                   "water_absorption_pct", "tensile_modulus_mpa", "tensile_strength_mpa",
                                   "elongation_pct", "melting_c", "abrasive_filler") + RATING_KEYS if k in m}
        results.append({"id": mid, "name": m["name"], "base": m["base"], "failed": failed, "passed": passed,
                        "deficit": round(deficit, 2), "score": margin, "properties": props, "notes": m["notes"]})
    results.sort(key=lambda r: (len(r["failed"]), r["deficit"], -r["score"],
                                MATERIALS[r["id"]]["tensile_modulus_mpa"] if want_elastic else 0, r["id"]))
    if unknown:
        for r in results:
            r["ignored_requirements"] = unknown
    return results


PRINT_RULES = u"""
ПРАВИЛА ВЫБОРА РЕЖИМА (Stereotech Hybrid 530 V5.2.4, используем только 3 режима):
- classic (3D): плоские детали, диски малой толщины (длина вдоль оси < ~0.35 диаметра: шестерни, крыльчатки-кольца),
  гибкие материалы (TPU/TPV/TPE — пыльники, уплотнения), декоративные модели без оси вращения.
- cylindrical_full (5D): тела вращения и валы, где важны прочность по окружности (нет расслоения между слоями
  под центробежной/циклической нагрузкой) или гладкая цилиндрическая рабочая поверхность без «ступенек» слоёв:
  колёса, ролики, рабочие колёса насосов, копирные валы/кулачки, втулки. Деталь ставится осью вращения
  вертикально, ось совпадает с осью поворотной платформы (X=0, Y=0). cylindrical_mode_base_diameter — диаметр
  цилиндрического основания, на котором печатается деталь: не больше диаметра осевого отверстия (обычно = отверстию
  с округлением вниз до 0.5 мм, минимум 4 мм); для сплошного вала — диаметр, меньший тонкой части вала.
- cylindrical (5D Spiral): та же печать вокруг оси, но непрерывной спиралью и без сплошного цилиндрического рафта
  (в cylindrical_full рафт на основании печатается автоматически). Подходит для тонкостенных тел вращения:
  трубы, втулки, кольца, оболочки, где толщина стенки мала относительно радиуса (примерно < 0.25 радиуса),
  и для деталей, где важна непрерывная намотка без шва между слоями.
- ВЫБОР МЕЖДУ 5D И 5D SPIRAL: для каждой 5D-детали рассмотри оба варианта. Массивные нагруженные тела вращения
  (колёса, рабочие колёса, валы, кулачки) — по умолчанию cylindrical_full. Тонкостенные оболочки — cylindrical.
  Решает analyze_model: cylindrical (Spiral) — ТОЛЬКО если spiral_candidate=true (каждый цилиндрический слой —
  замкнутое кольцо: труба, втулка, кольцо с постоянным отверстием). Лопасти, рёбра, гофры, спицы или переменный
  внутренний диаметр (пыльник, рабочее колесо, крыльчатка) — НЕ Spiral, даже если стенки тонкие.
  В итоге одной фразой объясни, почему не выбран другой 5D-режим. НЕ нарезай в двух режимах ради сравнения:
  5D-нарезка занимает несколько минут.
- Если пользователь явно указал режим — используй его. Если в имени файла/папки есть «3D» или «5D» — это подсказка.

ОРИЕНТАЦИЯ:
- 3D: orient_model(target=3d) кладёт деталь самой большой плоской гранью на стол с минимумом нависаний.
  Для шестерён и колёс — торцом на стол (ось вертикально): точнее эвольвента, нет «ступенек» на зубьях.
- 3D, тело вращения (analyze_model нашёл ось): ставь осью вертикально и проверь ОБА торца вниз
  (transform_model rotate 90° и -90° вокруг нужной оси, lay_on_plate=true, после каждого — analyze_model).
  Выбирай вариант с большей площадью контакта со столом (обычно широкий торец вниз). Положение «на боку»
  с контактом меньше ~200 мм² не принимай: деталь оторвётся от стола, особенно гибкая.
- 5D: orient_model(target=5d) — ось вращения вертикально и по центру стола.
- Масштаб не меняем: у деталей посадочные размеры.

НАСТРОЙКИ ПОД ТРЕБОВАНИЯ (значения — отправная точка, проверяй min/max через get_settings):
- Нагруженные детали (крутящий момент, удары): wall_line_count 4–6, top_layers/bottom_layers 5–8,
  infill_sparse_density 40–100 % (зубья/шпоночный паз — 100 %), layer_height 0.15–0.2.
- Термостойкость сравнивай по hdt_c (температура изгиба под нагрузкой). У частично-кристаллических PA и PP
  tg_c ниже рабочей температуры — это нормально и не повод отбрасывать материал.
- Точность посадок и профилей (±0.1–0.15 мм): layer_height 0.1–0.15, медленная внешняя стенка (speed_wall_0 20–30),
  xy_offset для компенсации усадки отверстий при необходимости.
- Внешний вид без видимых слоёв: layer_height 0.1 (или 5D), ironing_enabled для верхних граней,
  z_seam_type = sharpest_corner/back, без поддержек на видимых поверхностях; материал с матовой поверхностью.
- Гибкие материалы (TPU/TPV/TPE): speed_print 20–30, retraction_amount 0.5–2, wall_line_count 3–4,
  infill 20–40 % gyroid/lines, без «брима» при хорошей адгезии; герметичность — 3+ стенки и 4+ крышки.
- Материалы с усадкой (ABS, PC, PA, композиты): только в 3D (classic) adhesion_type brim. В 5D адгезию НЕ меняй:
  деталь печатается на цилиндрическом основании, рафт задаётся режимом. Обдув уже задан профилем материала
  (у ABS/PC/PA он 0 %) — отдельно его не выключай.
- Поддержки (support_enable) — только если нависания > ~100 мм² и их нельзя убрать ориентацией.
- Сплошной вал без осевого отверстия в cylindrical_full (analyze_model: has_axial_bore=false): ядро диаметром
  cylindrical_mode_base_diameter печатается в 3D на столе, остальное — цилиндрическими слоями вокруг него.
  Сквозного отверстия не будет — скажи это в итоге одной фразой. Если вал передаёт крутящий момент, задай
  cylindrical_mode_overlap = 1 мм (перекрытие ядра и 5D-оболочки), чтобы их граница не стала плоскостью среза.
- 5D-аналоги настроек имеют суффикс _cylindrical (speed_*_cylindrical, cool_fan_enabled_cylindrical,
  support_enable_cylindrical, cylindrical_layer_height). В 5D по умолчанию adhesion_type = raft.
- Температуры и обдув берутся из профиля материала; меняй их только с обоснованием.
"""

SYSTEM_PROMPT = u"""Ты — инженер-технолог аддитивного производства и ИИ-ассистент слайсера STE Slicer (Stereotech).
Ты управляешь слайсером только через инструменты. Отвечай по-русски, кратко и по делу.

ЦЕЛЬ: по описанию задачи/ТЗ и модели получить готовый проект: режим печати (3D/5D), профиль, материал,
ключевые настройки, ориентация и расположение модели, слайсинг, сохранение 3MF и G-code — и объяснить решения.

ПОРЯДОК РАБОТЫ:
1. get_scene_info — что на столе и какой принтер.
   - Если в сообщении есть строка «Приложена 3D-модель … путь для load_model: …» — это новая задача:
     на столе остались другие модели — delete_objects(object_id=all); в changed_settings остались правки
     от прошлой детали — reset_settings. Затем load_model с этим ПОЛНЫМ путём.
   - Если модели в сообщении нет, но на столе есть объект — работай с ним (object_id), повторно НЕ загружай.
   - Если нет ни приложенной модели, ни объекта на столе — попроси приложить STL/OBJ/3MF. Фото, чертёж
     или скан ТЗ — это не модель; из них бери только требования. Имена файлов не придумывай.
2. analyze_model — габариты, тело вращения, отверстие, нависания.
3. Выпиши требования ТЗ с числами (температура, химия, нагрузки, плотность, водопоглощение, гибкость, внешний вид)
   и вызови recommend_materials с этими требованиями. Выбирай материал ТОЛЬКО из материалов Stereotech
   из базы знаний (их возвращает recommend_materials; в list_materials у них in_knowledge_base=true).
   Профили generic_* не выбирай и не запрашивай: для них нет проверенных свойств.
   Если идеального нет — выбери ближайший и честно скажи, какое требование не закрыто.
   - Деталь работает на изгиб/растяжение с большой деформацией (пыльник, сильфон, гофра, мембрана, уплотнение,
     прокладка, «должен сохранять эластичность») — передай elastic=true. Полужёсткие TPU (D70, C5) и жёсткие
     материалы для таких деталей не подходят, даже если у них выше износостойкость.
   - Жёсткая нагруженная деталь (зубья, лопасти, вал, кулачок, посадка с допуском) — stiffness="rigid".
     Ролик или колесо с упругим протектором, манжета — stiffness="semi_rigid" (твёрдый TPU).
   - Требования передавай только те, что прямо написаны в ТЗ. Удары камней или стружки — это ударная вязкость
     и стойкость к разрыву (min_elongation_pct), а не абразивный износ: abrasion добавляй, только если в ТЗ
     есть трение, истирание или абразивная среда.
   - Кратковременный контакт с горячим (капли клея, расплав, пайка) при T °C — min_melting_c=T+20 (запас), а не
     рабочая температура: деталь не должна плавиться в момент контакта.
   - food_contact=true — только при прямом контакте детали с пищей. «Не выделять токсичных веществ» на упаковочном
     оборудовании без контакта с продуктом — не food_contact; упомяни это допущение в итоге.
   - «Гидрофобный», «не впитывает влагу», работа в тумане/воде или при влажности 80–100 % без числа в ТЗ —
     max_water_absorption_pct=0.3. Если в ТЗ есть число — передавай его.
   - Деталь скользит или катится по ответной ПОЛИМЕРНОЙ детали (ролики из POM/PA, пластиковый вал, втулка)
     и ТЗ требует не изнашивать её или низкого трения — non_abrasive=true и low_friction=true. Стекловолокно
     выступает на поверхности и стачивает ответную деталь, как напильник.
   - «Вязкость, чтобы тонкие элементы не отламывались» у жёсткой детали (фигурка, корпус, декор) — это
     stiffness="rigid" и min_elongation_pct=4, а не эластомер или полужёсткий TPU: TPU печатается в 2–3 раза
     медленнее, хуже держит мелкие элементы и поддержки.
4. set_print_mode (classic / cylindrical_full / cylindrical), затем set_material, set_profile, set_settings.
   Второй экструдер (1) нужен только для поддержек/армирования; если он не используется —
   set_extruder_enabled(extruder=1, enabled=false).
5. orient_model (3d или 5d), при нескольких разных моделях — arrange_all.
   ПАРТИЯ: если в ТЗ нужно несколько одинаковых деталей (партия, комплект, «N шт.»):
   - 3D: ПОСЛЕ orient_model вызови duplicate_model(count=N). Он сам считает, сколько деталей помещается с зазором,
     делит партию на равные запуски (например, 12 шт. при вместимости 8 — 2 запуска по 6) и раскладывает их.
     После него НЕ вызывай arrange_all и не двигай копии. Если после нарезки один запуск дольше ~24 ч —
     повтори duplicate_model с max_per_run поменьше (риск: при сбое теряется весь стол) и перенарежь.
   - 5D: не копируй — одна деталь за запуск на цилиндрическом основании; в итоге посчитай число запусков.
   Количество бери только из ТЗ или сообщения пользователя; если не указано — одна деталь.
   ВРЕМЯ ПАРТИИ: малую партию (до ~50 шт.) заказывают на FDM ради скорости и цены, поэтому время на всю партию —
   такое же требование, как прочность. Для ненагруженных деталей не замедляй печать сверх профиля материала,
   не ставь заполнение выше 10–15 % и стенки больше 3. Внешний вид без слоёв на высокой детали (> ~50 мм) —
   adaptive_layer_height_enabled=true на профиле Fine вместо Extra Fine. Если на всю партию выходит больше
   ~5 суток — назови это в итоге и предложи, что ещё ускорит печать.
6. slice — ОДИН раз, после того как выставлены режим, материал, настройки и ориентация (5D-нарезка идёт минутами;
   повторно нарезай только если слайсер выдал ошибку или результат неправдоподобен) → проверь результат (время, расход; если расход неправдоподобно мал относительно объёма модели —
   проверь ориентацию/режим). НЕ сохраняй файлы сам: save_project и export_gcode — только после того,
   как пользователь подтвердил сохранение (кнопка «Сохранить» или просьба в сообщении). Без подтверждения
   инструмент вернёт ошибку.
7. Итог: таблица «параметр → значение → почему (ссылка на требование ТЗ или геометрию)». Обязательные строки:
   принтер, режим, профиль качества, материал, ориентация и положение на столе, затем каждая изменённая настройка.
   После таблицы — время печати и расход материала. Для партии добавь строку: «Партия N шт.: M запусков по K шт.,
   на запуск — время/расход, на всю партию ≈ M × время» (время и расход слайсера — на один запуск). Вопрос о сохранении текстом не задавай: чат сам покажет
   пользователю кнопки «Сохранить / Не сохранять».
8. Когда пользователь подтвердил сохранение: save_project, export_gcode (path не указывай — папка по умолчанию),
   validate_gcode, затем коротко пути к файлам. Если вместо подтверждения пришли правки — внеси только их,
   перенарежь и снова спроси про сохранение. Правки после сохранения — так же, затем сохрани заново только
   после нового подтверждения.

ПРАВИЛА:
- Принтер: проекты готовятся для Stereotech Hybrid 530 V5.2.4 (hte530v5.2.4). Если get_scene_info вернул
  printer_warning — сразу скажи пользователю, какой принтер активен, и попроси выбрать Hybrid 530 V5.2.4
  в слайсере. Не настраивай проект на другом принтере, пока пользователь явно не подтвердит его.
- save_profile и create_profile вызывай только по просьбе пользователя: профиль качества должен оставаться
  штатным, а изменения — в пользовательских настройках проекта.
- Не выдумывай значения свойств материалов и настроек — бери их из инструментов. Элементы геометрии
  (отверстия, пазы, лыски) называй только если их вернул analyze_model, они видны на фото или описаны в ТЗ.
- Если инструмент вернул ошибку — объясни пользователю и предложи, что сделать.
- Не меняй масштаб модели без явной просьбы.
- Меняй только те настройки, для которых есть причина в ТЗ или геометрии. Не трогай то, что уже задано профилем
  материала или качества: каждая лишняя правка — расхождение с эталонным проектом.
- Инженерные требования ТЗ важнее пожеланий, не связанных с работой детали. Если пожелание пользователя
  противоречит ТЗ — выбери по ТЗ и коротко объясни почему.
- Тон деловой: без шуток, сленга и эмодзи, даже если пользователь пишет неформально (переписку оценивает жюри).
- compare_variants вызывай ТОЛЬКО если пользователь сам просит сравнить варианты («что быстрее?», «сравни
  прочно/экономно»). Сам по своей инициативе не вызывай: это несколько лишних нарезок (в 5D — минуты).
  После compare_variants G-code сброшен: перед save_project/export_gcode снова вызови slice. Без явного выбора
  пользователя оставляй настройки по ТЗ.
- Профили качества называй так, как их видит пользователь (name из list_profiles): quality_type normal — это
  «Fine», fast — «Normal», high — «Extra Fine».
- Не меняй настройки, которые при текущих значениях ни на что не влияют: при infill_sparse_density = 100 %
  не трогай infill_pattern и толщину крышек (деталь и так сплошная).
- Опирайся только на требования, которые прямо есть в ТЗ, не додумывай новые (например, щёлочь, если в ТЗ кислоты и соли).
- Называй экструдеры как в интерфейсе слайсера: «основной экструдер» и «второй экструдер» (не «экструдер 0/1»).
- Итоговый ответ компактный: таблица решений, результат слайсинга и 2–3 строки допущений.
  Не предлагай действий «вне слайсера», если их можно сделать настройкой слайсера.
- Не задавай лишних вопросов: если данных достаточно — действуй, допущения перечисли в итоге.
""" + PRINT_RULES
