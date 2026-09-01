from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .models import Fact, FactStore


# These are search concepts, not code mappings. The same concepts are used by
# retrieval and by the reusable predicate evaluators in policy.py.
CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "chest_pain": ("chest pain", "chest discomfort", "pain in chest", "thoracic discomfort", "anterior thoracic discomfort", "anterior thoracic pain", "pressure behind sternum", "pressure behind the sternum"),
    "chest_wall_tenderness": ("chest wall tenderness", "costochondral tenderness", "tender over the chest wall", "reproducible tenderness", "reproducible by palpation over the costochondral junctions", "palpation over the costochondral junctions", "pressing the costochondral junction"),
    "movement_worse": ("worse with movement", "worsened by movement", "pain on movement", "trunk movement"),
    "deep_inspiration": ("deep inspiration", "deep breath", "deep breaths", "inspiration"),
    "retrosternal": ("retrosternal", "behind the breastbone", "behind sternum", "behind the sternum"),
    "exertional": ("on exertion", "with exertion", "exertional", "walking uphill", "exercise-induced"),
    "rest_pain": ("at rest", "rest pain", "while resting"),
    "nitrate_relief": ("relieved by nitrate", "relieved with nitrate", "responded to nitroglycerin", "relieved by glyceryl trinitrate", "relieved by rest", "settles with rest", "settled by rest"),
    "increasing_frequency": ("increasing frequency", "more frequent", "happening more often"),
    "prolonged_pain": ("beyond twenty minutes", "over 20 minutes", "more than 20 minutes", "lasting 20 minutes", "lasting thirty minutes"),
    "loin_pain": ("loin pain", "flank pain", "renal angle pain"),
    "groin_radiation": ("radiat* to the groin", "radiating into the groin", "shoots into the groin", "shooting into the groin", "to the groin"),
    "colicky": ("colicky", "colic", "comes in waves", "cramping waves"),
    "unable_settle": ("unable to settle", "cannot keep still", "restless with pain"),
    "haematuria": ("haematuria", "hematuria", "blood in urine", "bloody urine", "urine dip positive for blood", "urine dip is positive for blood", "dipstick haematuria", "dipstick positive for blood", "blood on dipstick"),
    "periumbilical": ("periumbilical", "around the umbilicus", "around the belly button", "around the navel"),
    "right_iliac_fossa": ("right iliac fossa", "right lower quadrant", "right lower abdomen", "right iliac region"),
    "pain_migration": ("migrated", "migration of pain", "pain moved", "pain shifted", "shifted"),
    "mcburney": ("mcburney", "mc burney"),
    "guarding": ("guarding", "involuntary guarding"),
    "rebound": ("rebound tenderness", "rebound"),
    "otalgia": ("otalgia", "ear pain", "earache"),
    "bulging_tm": ("bulging tympanic membrane", "bulging eardrum", "bulging drum"),
    "erythematous_tm": ("erythematous tympanic membrane", "red tympanic membrane", "red eardrum"),
    "opacified_tm": ("opacified tympanic membrane", "opaque tympanic membrane", "cloudy eardrum"),
    "perforated_tm": ("perforated tympanic membrane", "perforated eardrum", "ear drum perforation"),
    "ear_discharge": ("ear discharge", "otorrhoea", "otorrhea", "discharge from the ear"),
    "unilateral": ("unilateral", "one-sided", "on one side"),
    "pulsating": ("pulsating", "throbbing", "throbbing headache"),
    "moderate_severe": ("moderate to severe", "moderate-severe", "severe intensity", "severe headache"),
    "activity_aggravates": ("aggravated by activity", "worse with activity", "worse with routine activity", "worse on movement", "routine physical activity"),
    "nausea": ("nausea", "nauseated", "feeling sick"),
    "photophobia": ("photophobia", "light sensitivity", "sensitive to light"),
    "phonophobia": ("phonophobia", "sound sensitivity", "sensitive to sound"),
    "headache": ("headache", "head pain", "cephalalgia"),
    "dysuria": ("dysuria", "painful urination", "burning urination", "burning when passing urine"),
    "urinary_frequency": ("urinary frequency", "frequency of urination", "passing urine frequently", "frequent urination", "frequency"),
    "urinary_urgency": ("urinary urgency", "urgent urination", "urgency to urinate", "urgency"),
    "systemic_upset": ("systemically unwell", "systemic upset", "toxic", "malaise"),
    "cva_tenderness": ("costovertebral angle tenderness", "cva tenderness", "renal punch tenderness"),
    "pregnancy": ("pregnant", "pregnancy", "gestation", "antenatal", "intrauterine pregnancy"),
    "allergen_exposure": ("allergen", "allergic exposure", "after eating", "after an injection", "after a sting", "after sting", "after taking"),
    "skin_change": ("urticaria", "hives", "widespread rash", "skin changes", "flushing", "angioedema"),
    "mucosal_change": ("mucosal swelling", "swollen lips", "swollen tongue", "oral swelling", "mucosal changes"),
    "respiratory_compromise": ("respiratory compromise", "difficulty breathing", "airway compromise", "wheeze", "stridor", "shortness of breath"),
    "hypotension": ("hypotension", "low blood pressure", "shock", "collapsed with low pressure"),
    "diabetes": ("diabetes", "diabetic", "diabetes mellitus"),
    "type1_diabetes": ("type 1 diabetes", "type i diabetes", "t1dm", "insulin-dependent diabetes"),
    "type2_diabetes": ("type 2 diabetes", "type ii diabetes", "t2dm", "non-insulin-dependent diabetes"),
    "oral_agents": ("oral agents", "oral medication", "metformin", "tablets for diabetes"),
    "insulin": ("insulin", "insulin-treated"),
    "diarrhoea": ("diarrhoea", "diarrhea", "loose stools", "watery stools"),
    "vomiting": ("vomiting", "vomited", "emesis", "throwing up"),
    "blood_stool": ("blood in stool", "bloody stool", "haematochezia", "hematochezia", "melena", "melaena"),
    "pathogen": ("pathogen", "organism isolated", "culture grew", "stool culture", "positive culture"),
    "first_mtp": ("first metatarsophalangeal", "first mcp joint", "big toe joint", "great toe joint"),
    "joint_swelling": ("joint swelling", "swollen joint", "acutely swollen joint", "joint became suddenly swollen", "swelling", "swollen"),
    "joint_erythema": ("joint erythema", "red joint", "erythematous joint", "joint became red", "joint became suddenly swollen, red", "redness of the joint", "erythema"),
    "exquisite_tenderness": ("exquisite tenderness", "exquisitely tender", "tender to light touch"),
    "immunosuppression": ("immunosuppressed", "immunosuppression", "on immunosuppressants"),
    "recent_instrumentation": ("recent instrumentation", "instrumentation", "recent procedure"),
    "aspiration": ("aspiration", "aspirated", "joint aspirate"),
    "synovial_microscopy": ("synovial fluid microscopy", "crystals on microscopy", "crystal microscopy"),
    "synovial_culture": ("synovial fluid culture", "joint fluid culture", "culture of aspirate"),
    "jaw_claudication": ("jaw claudication", "jaw pain on chewing", "jaw discomfort on chewing"),
    "scalp_tenderness": ("scalp tenderness", "tender scalp"),
    "visual_disturbance": ("visual disturbance", "visual loss", "blurred vision", "vision changes"),
    "inflammatory_markers": ("raised inflammatory markers", "elevated esr", "raised esr", "raised crp", "elevated crp"),
    "focal_deficit": ("focal neurological deficit", "focal neurological weakness", "focal weakness", "facial droop", "speech difficulty", "unilateral weakness", "arm weakness"),
    "resolved_deficit": ("resolved completely", "fully resolved", "no residual deficit"),
    "persistent_deficit": ("persistent deficit", "deficit persists", "ongoing weakness", "residual weakness", "abnormal neurological examination"),
    "recurrent_event": ("recurrent", "repeated", "two episodes", "two events", "multiple episodes", "more than one episode"),
    "pneumonia": ("pneumonia", "community acquired pneumonia", "cap"),
    "cough": ("cough", "coughing"),
    "productive_cough": ("productive cough", "purulent sputum", "phlegm", "sputum"),
    "crackles": ("crackles", "crepitations", "creps"),
    "dullness": ("dullness to percussion", "dull percussion"),
    "consolidation": ("consolidation", "radiographic consolidation", "ultrasound consolidation"),
    "chest_imaging": ("chest x-ray", "chest radiograph", "radiograph", "xray", "x-ray", "point-of-care ultrasound", "lung ultrasound"),
    "asthma": ("asthma", "asthmatic"),
    "wheeze": ("wheeze", "wheezing"),
    "breathlessness": ("breathlessness", "shortness of breath", "dyspnoea", "dyspnea", "exertional breathlessness"),
    "bronchodilator_response": ("responded to bronchodilator", "improved after bronchodilator", "bronchodilator response", "reversible after bronchodilator", "improved after salbutamol", "improves after salbutamol", "improves markedly after salbutamol", "improved markedly after salbutamol", "response to salbutamol", "improved with inhaler"),
    "fixed_obstruction": ("fixed obstruction", "persistent obstruction after bronchodilator", "not reversible after bronchodilator", "persistent after inhaler", "persistent after the inhaler", "persists after inhaler", "persists after the inhaler", "not reversible"),
    "smoking": ("smoker", "smoking", "pack-year", "pack years", "cumulative smoking"),
    "hyperglycaemia": ("hyperglycaemia", "hyperglycemia", "high glucose", "markedly elevated glucose"),
    "ketones": ("ketonaemia", "ketonemia", "ketonuria", "ketones", "positive ketones"),
    "acidosis": ("metabolic acidosis", "acidosis", "low bicarbonate", "low ph"),
    "raised_osmolality": ("raised osmolality", "high osmolality", "hyperosmolar"),
    "altered_mentation": ("altered mentation", "altered mental status", "confusion", "reduced consciousness", "drowsy"),
    "oliguria": ("oliguria", "reduced urine output", "not passing much urine"),
    "raised_lactate": ("raised lactate", "elevated lactate", "lactate"),
    "infection": ("infection", "infected", "septic", "sepsis"),
    "vasopressors": ("vasopressor", "noradrenaline", "norepinephrine", "requiring pressors"),
    "fluid_resuscitation": ("fluid resuscitation", "after fluids", "despite fluids", "adequate fluids"),
    "malaria": ("malaria", "malarial", "plasmodium"),
    "falciparum": ("falciparum", "p. falciparum", "plasmodium falciparum"),
    "malaria_test": ("blood film", "malaria film", "malaria rdt", "rdt", "rapid diagnostic test", "malaria test"),
    "endemic_area": ("endemic area", "malaria endemic", "from an endemic area", "lives in an endemic area"),
    "antimalarial_treatment": ("treated for malaria", "antimalarial treatment", "treatment commenced", "treated clinically"),
    "dengue": ("dengue", "breakbone fever"),
    "myalgia": ("myalgia", "severe muscle pain", "muscle aches"),
    "retroorbital_pain": ("retro-orbital pain", "behind the eyes", "pain behind the eyes"),
    "rash": ("rash", "maculopapular rash"),
    "thrombocytopenia": ("thrombocytopenia", "low platelets", "falling platelet count"),
    "warning_sign": ("abdominal tenderness", "persistent vomiting", "mucosal bleeding", "lethargy", "rising haematocrit", "rising hematocrit"),
    "organ_dysfunction": ("organ dysfunction", "acute kidney injury", "respiratory failure", "lactate", "hypotension", "altered mentation", "oliguria"),
    "convulsion": ("convulsion", "seizure", "fit", "fitting"),
    "prior_afebrile_seizure": ("prior afebrile seizure", "previous seizure without fever", "history of afebrile seizure"),
    "cns_infection": ("central nervous system infection", "meningitis", "encephalitis"),
    "medication_overuse": ("regular symptomatic medication", "analgesics on", "painkillers on", "acetaminophen", "paracetamol", "medication overuse", "medication-overuse"),
    "bleeding_early_pregnancy": ("bleeding in early pregnancy", "first trimester bleeding", "vaginal bleeding in pregnancy", "vaginal bleeding"),
    "closed_os": ("closed cervical os", "cervix closed"),
    "viable_iup": ("viable intrauterine pregnancy", "viable intrauterine gestation", "live intrauterine pregnancy"),
    "pelvic_pain": ("pelvic pain", "unilateral pelvic pain", "left-sided pelvic pain", "right-sided pelvic pain", "left sided pelvic pain", "right sided pelvic pain"),
    "amenorrhoea": ("amenorrhoea", "amenorrhea", "weeks of amenorrhea"),
    "orthostatic_change": ("haemodynamic changes on standing", "hemodynamic changes on standing", "dizzy on standing", "dizziness on standing", "postural hypotension"),
    "proteinuria": ("proteinuria", "protein in urine"),
    "hyperreflexia": ("hyperreflexia", "brisk reflexes"),
    "ruq_pain": ("right upper quadrant", "ruq pain", "pain under the right ribs"),
    "fatty_meal": ("fatty meal", "after a fatty meal", "after eating fatty food", "after fatty food", "follows fatty food", "fatty food"),
    "jaundice": ("jaundice", "icterus", "yellow eyes"),
    "rigors": ("rigors", "shaking chills"),
    "saddle_anaesthesia": ("saddle anaesthesia", "saddle anesthesia"),
    "bladder_bowel_disturbance": ("bladder disturbance", "bowel disturbance", "urinary retention", "incontinence"),
    "bilateral_leg": ("bilateral leg symptoms", "both legs", "bilateral weakness"),
    "progressive_weakness": ("progressive weakness", "progressing weakness"),
    "night_pain": ("night pain", "pain at night"),
    "weight_loss": ("weight loss", "unintentional weight loss"),
    "malignancy_history": ("history of malignancy", "previous cancer", "known cancer"),
    "spreading_erythema": ("spreading erythema", "spreading redness", "expanding red", "advancing border", "advancing edge", "demarcated advancing edge"),
    "skin_warmth": ("skin warmth", "warm skin", "warmth"),
    "pain_disproportionate": ("pain disproportionate", "pain out of proportion", "disproportionate pain"),
    "rapid_progression": ("rapid progression", "progressing over hours", "rapidly progressive"),
    "skin_anaesthesia": ("skin anaesthesia", "skin anesthesia", "numb skin over"),
    "crepitus": ("crepitus", "crepitations in the soft tissue"),
    "haemoglobin": ("haemoglobin", "hemoglobin", "hb"),
    "heart_failure_sign": ("orthopnoea", "orthopnea", "paroxysmal nocturnal dyspnoea", "pnd", "raised jugular venous pressure", "jvp", "peripheral oedema", "peripheral edema", "bibasal crepitations"),
    "head_injury": ("head injury", "blow to the head", "blow to head", "hit head", "head trauma"),
    "loss_awareness": ("loss of awareness", "lost consciousness", "brief loss of consciousness", "brief loss of awareness"),
    "brief_loss": ("brief loss of awareness", "brief loss of consciousness", "briefly lost consciousness"),
    "fever_two_days": ("fever on two days", "febrile on two days", "two days of fever", "fever for two days", "fever occurred on postpartum days"),
    "repeated_vomiting": ("repeated vomiting", "recurrent vomiting", "multiple vomits"),
    "anticoagulant": ("anticoagulant", "warfarin", "apixaban", "rivaroxaban", "on blood thinners"),
    "tb": ("tuberculosis", "pulmonary tb", "tb"),
    "tb_test": ("sputum microscopy", "sputum afb", "molecular testing", "gene xpert", "genexpert", "xpert", "tb test"),
    "vertigo": ("vertigo", "room spinning", "room-spinning", "rotatory dizziness"),
    "positional_trigger": ("positional", "when turning in bed", "turning in bed", "turning the head", "changes in head position"),
    "dix_hallpike": ("dix-hallpike", "dix hallpike"),
    "new_deafness": ("new deafness", "new hearing loss"),
    "cranial_nerve_sign": ("cranial nerve sign", "cranial nerve palsy"),
    "limb_ataxia": ("limb ataxia", "ataxia"),
    "unable_stand": ("unable to stand unaided", "cannot stand unaided", "unable to walk unaided"),
    "screening": ("screening", "screening visit", "screening examination"),
    "immunisation": ("immunisation", "immunization", "vaccination", "vaccine visit"),
    "contraception": ("contraception", "contraceptive", "family planning"),
    "routine_exam": ("routine examination", "general examination", "check-up", "checkup"),
    "follow_up": ("follow-up", "follow up", "review appointment", "scheduled review"),
    "sore_throat": ("sore throat", "throat pain"),
    "tonsillar_exudate": ("tonsillar exudate", "exudative tonsils", "pus on tonsils"),
    "cervical_nodes": ("tender anterior cervical lymph nodes", "tender anterior cervical nodes", "tender cervical nodes", "cervical lymphadenopathy"),
    "absence_cough": ("absence of cough", "no cough"),
    "stridor": ("stridor", "noisy breathing"),
    "drooling": ("drooling", "drools"),
    "trismus": ("trismus", "difficulty opening the mouth"),
    "muffled_voice": ("muffled voice", "hot potato voice"),
    "difficulty_swallowing_saliva": ("unable to swallow saliva", "cannot swallow saliva", "drooling saliva"),
    "sickle_cell": ("sickle cell disease", "sickle cell anaemia", "sickle cell anemia", "hbss"),
    "acute_chest_sign": ("acute chest syndrome", "chest signs", "hypoxia", "low oxygen", "oxygen saturation low"),
    "vaso_occlusive_pain": ("vaso-occlusive crisis", "painful crisis", "acute limb pain in sickle cell", "acute limb pain", "sickle pain crisis"),
    "frailty": ("frail", "frailty"),
    "confusion": ("confusion", "confused", "new confusion"),
    "dehydration": ("dehydration", "volume depletion", "dry mucous membranes"),
    "acute_kidney_injury": ("acute kidney injury", "aki", "acute renal failure"),
    "prostatitis": ("prostatitis", "prostatic involvement", "prostate involvement"),
    "asymptomatic_bacteriuria": ("asymptomatic bacteriuria", "bacteria in urine without symptoms"),
    "hypertension": ("hypertension", "high blood pressure", "raised blood pressure"),
    "hypertensive": ("hypertensive",),
    "pulmonary_oedema": ("pulmonary oedema", "pulmonary edema", "acute pulmonary oedema"),
    "falling_platelets": ("falling platelets", "platelets falling", "declining platelet count"),
    "haemodynamic_change": ("haemodynamic change", "hemodynamic change", "haemodynamic changes", "hemodynamic changes"),
    "scrotal_pain": ("scrotal pain", "testicular pain", "painful scrotum"),
    "high_riding_testis": ("high-riding testis", "high riding testis", "transversely lying testis"),
    "absent_cremasteric": ("absent cremasteric reflex", "absent cremasteric"),
    "uterine_tenderness": ("uterine tenderness", "tender uterus"),
    "offensive_lochia": ("offensive lochia", "foul-smelling lochia", "foul smelling lochia"),
    "low_back_pain": ("low back pain", "mechanical back pain", "lumbago"),
    "hip_pain": ("hip pain", "painful hip", "atraumatic hip pain"),
    "limp": ("limp", "limping", "antalgic gait"),
    "recent_viral_illness": ("recent viral illness", "recent viral infection"),
    "systemically_well": ("systemically well", "well appearing", "well-appearing"),
    "weight_bearing": ("weight-bearing", "weight bearing", "able to bear weight"),
    "night_sweats": ("night sweats", "drenching night sweats"),
    "tb_contact": ("contact with a known case", "tb contact", "tuberculosis contact"),
    "normal_neurology": ("normal neurological examination", "normal neurologic examination", "neurologically normal", "normal neuro exam", "normal neurological exam", "neuro exam is normal", "neurologic exam is normal"),
    "loss_awareness_seconds": ("loss of awareness for", "loss of consciousness for"),
    "headache_days_per_month": ("headache days per month", "headache on days per month"),
    "medication_days_per_month": ("medication days per month", "analgesics on days per month", "painkillers on days per month"),
    "dengue_test": ("dengue test", "dengue pcr", "ns1", "dengue serology", "positive dengue test"),
    "pain": ("pain",),
}


NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "seventy": 70,
    "one hundred": 100,
}


def normalize_for_search(text: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return unicodedata.normalize("NFKC", text).casefold()


def _parse_num(value: str) -> float | None:
    value = value.strip().casefold()
    if value in NUMBER_WORDS:
        return float(NUMBER_WORDS[value])
    try:
        return float(value)
    except ValueError:
        return None


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left_candidates = [text.rfind(mark, 0, start) for mark in ".!?\n"]
    left = max(left_candidates) + 1
    right_candidates = [index for mark in ".!?\n" for index in (text.find(mark, end),) if index >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    return left, right


def _assertion(normalized: str, sentence_start: int, start: int) -> tuple[str, str, str]:
    before = normalized[sentence_start:start]
    # A new comma/semicolon often starts a separate assertion scope, e.g.
    # "no fever, possible pneumonia". Keep the local clause primary while
    # retaining a short wider window for constructions such as "without
    # fever or loin pain".
    clause = re.split(r"[,;:]", before)[-1]
    compact = clause[-140:]
    wider = before[-140:]
    # Most specific scopes first.
    if re.search(r"\b(?:family history of|mother has|father has|sibling has|relative with)\s*$", compact):
        return "family_history", "current", "other"
    if re.search(r"\b(?:history of|past medical history|previous|prior|old episode|known)\s*$", compact):
        return "historical", "prior", "patient"
    if re.search(r"\b(?:if|should|when|unless|in case|on developing)\s*$", compact):
        return "conditional", "future_or_conditional", "patient"
    if re.search(r"\b(?:request|requested|please|consider|query)\b", compact) and re.search(r"\b(?:treat|treated|septic|sepsis)\b", compact):
        return "possible", "current", "patient"
    if re.search(r"\b(?:no|not|denies|denied|without|absent|absence of|negative for|negative|never|afebrile|nil)\b[^.!?\n]{0,75}$", compact):
        return "absent", "current", "patient"
    if re.search(r"\b(?:possible|probable|suspected|query|consider|rule out)\b", compact) or re.search(r"\?\s*$", compact):
        return "possible", "current", "patient"
    # Carry a leading "without" across a short comma-separated list.
    if re.search(r"\bwithout\b[^.!?\n]{0,90}$", wider) and not re.search(r"\b(?:but|however|although)\b", wider):
        return "absent", "current", "patient"
    return "present", "current", "patient"


def _add_fact(store: FactStore, concept: str, value: Any, start: int, end: int, assertion: str = "present", temporality: str = "current", experiencer: str = "patient", confidence: str = "moderate") -> None:
    sentence_start, sentence_end = _sentence_bounds(store.text, start, end)
    quote = store.text[sentence_start:sentence_end].strip()
    store.add(Fact(
        concept=concept,
        value=value,
        assertion=assertion,  # type: ignore[arg-type]
        temporality=temporality,
        experiencer=experiencer,
        start=start,
        end=end,
        quote=quote[:300],
        confidence=confidence,
    ))
    store.material_spans.append((sentence_start, sentence_end, concept, assertion))


def _add_alias_facts(store: FactStore) -> None:
    # Keep overlapping concepts: "wheeze" is both an airway finding and one
    # possible form of respiratory compromise.  Deduplicate only the same
    # concept/span pair.
    occupied: set[tuple[str, int, int]] = set()
    for concept, aliases in CONCEPT_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            # '*' in an alias means a deliberately loose word boundary, e.g.
            # radiat*; it is not exposed as a user-facing regex rule.
            if alias.endswith("*"):
                pattern = re.escape(alias[:-1]) + r"\w*"
            else:
                pattern = re.escape(alias)
            for match in re.finditer(rf"(?<!\w){pattern}(?!\w)", store.normalized):
                span = (match.start(), match.end())
                key = (concept, match.start(), match.end())
                if key in occupied:
                    continue
                occupied.add(key)
                sentence_start, _ = _sentence_bounds(store.normalized, *span)
                assertion, temporality, experiencer = _assertion(store.normalized, sentence_start, match.start())
                confidence = "high" if alias in (concept.replace("_", " "),) else "moderate"
                _add_fact(store, concept, True, match.start(), match.end(), assertion, temporality, experiencer, confidence)


def _add_number_fact(store: FactStore, concept: str, value: float, start: int, end: int, unit: str | None = None) -> None:
    sentence_start, _ = _sentence_bounds(store.normalized, start, end)
    assertion, temporality, experiencer = _assertion(store.normalized, sentence_start, start)
    stored_value: Any = {"value": value, "unit": unit}
    _add_fact(store, concept, stored_value, start, end, assertion, temporality, experiencer, "high")


def _add_numeric_facts(store: FactStore) -> None:
    text = store.normalized
    num = r"(?:\d+(?:\.\d+)?|" + "|".join(re.escape(word) for word in NUMBER_WORDS) + r")"
    patterns: list[tuple[str, str, str | None]] = [
        (rf"\b(?:aged?|age)\s*[:=]?\s*({num})\s*months?\b", "age_months", "months"),
        (rf"\b(?:aged?|age)\s*[:=]?\s*({num})\s*(?:years?|yrs?)\b", "age_years", "years"),
        (rf"\bat\s+age\s+({num})\b", "age_years", "years"),
        (rf"\b({num})[- ]month[- ]old\b", "age_months", "months"),
        (rf"\b({num})[- ]year[- ]old\b", "age_years", "years"),
        (rf"\b({num})\s*(?:y/o|yo)\b", "age_years", "years"),
        (rf"\b({num})\s*weeks?\s*(?:of\s+)?(?:pregnant|gestation|amenorrh(?:oe|ea))\b", "gestational_weeks", "weeks"),
        (rf"\b(?:pregnant|gestation|amenorrh(?:oe|ea))[^.!?\n]{{0,12}}\b({num})\s*weeks?\b", "gestational_weeks", "weeks"),
        (rf"\b({num})\s*weeks?\b", "duration_weeks", "weeks"),
        (rf"\b(?:at|of)\s*({num})\s*weeks?\s*(?:gestation|pregnancy|amenorrh(?:oe|ea))\b", "gestational_weeks", "weeks"),
        (rf"\b({num})\s*days?\s*(?:postpartum|after delivery|after birth)\b", "postpartum_days", "days"),
        (rf"\b(?:postpartum|post-partum|after delivery|after birth)\s*(?:day|days?)\s*({num})\b", "postpartum_days", "days"),
        (rf"\b(?:systolic|sbp)\s*(?:blood pressure|bp)?\s*(?:is|=|:)?\s*({num})\b", "systolic_bp", "mmHg"),
        (rf"\b(?:bp|blood pressure)\s*[:=]?\s*({num})\s*/\s*{num}\b", "systolic_bp", "mmHg"),
        (rf"\b(?:temperature|temp|fever|pyrexia|t)\s*(?:of|is|=|:)?\s*({num})\s*(?:degrees?|deg|\u00b0)?\s*(?:c|f)?\b", "temperature", "degrees"),
        (rf"\b(?:haemoglobin|hemoglobin|hb)\s*[:=]?\s*({num})\s*(g/?dl|g/l)?\b", "haemoglobin_value", "g/dL"),
        (rf"\b(?:platelets?|plt)\s*[:=]?\s*({num})\s*(?:x\s*10\^?9/l|10\^?9/l)?\b", "platelets", "10^9/L"),
        (rf"\b(?:glucose|blood sugar|random glucose)\s*[:=]?\s*({num})\s*(mg/dl|mmol/l)?\b", "glucose", None),
        (rf"\b(?:osmolality|osmolarity)\s*[:=]?\s*({num})\s*(?:mosm/kg)?\b", "osmolality", "mOsm/kg"),
        (rf"\bfor\s*({num})\s*(hours?|hrs?|h)\b", "duration_hours", "hours"),
        (rf"\bfor\s*({num})\s*(days?|d)\b", "duration_days", "days"),
        (rf"\bfor\s*({num})\s*(months?|mos?)\b", "duration_months", "months"),
        (rf"\b({num})\s*(?:or more|\+)\s*(?:episodes?|attacks?|events?)\b", "episode_count", "episodes"),
        (rf"\b({num})\s*(?:episodes?|attacks?|events?)\b", "episode_count", "episodes"),
        (rf"\b({num})\s*pack[- ]years?\b", "pack_years", "pack-years"),
        (rf"\b({num})\s*(?:minutes?|mins?)\b", "duration_minutes", "minutes"),
        (rf"\b({num})[- ](?:seconds?|secs?)\b", "duration_seconds", "seconds"),
        (rf"\b({num})\s*(?:seconds?|secs?)\b", "duration_seconds", "seconds"),
        (rf"\b({num})\s*(?:days?|d)\s*(?:of headache|headache days?)\s*(?:per month|a month|each month)\b", "headache_days_per_month", "days/month"),
        (rf"\b(?:headache|headaches)\s*(?:on|for|occurs on|occur on)?\s*({num})\s*days?\s*(?:per month|a month|each month)\b", "headache_days_per_month", "days/month"),
        (rf"\b(?:analgesics?|painkillers?|acetaminophen|paracetamol|symptomatic medication|medication)(?:\s+is)?\s*(?:taken\s+)?(?:on|for)?\s*({num})\s*days?\s*(?:per month|a month|each month)\b", "medication_days_per_month", "days/month"),
        (rf"\b(?:respiratory rate|rr)\s*[:=]?\s*({num})\b", "respiratory_rate", "breaths/min"),
        (rf"\b(?:loss of (?:awareness|consciousness))\s*(?:for|lasting)?\s*({num})\s*(?:seconds?|secs?)\b", "loss_awareness_seconds", "seconds"),
    ]
    for pattern, concept, unit in patterns:
        for match in re.finditer(pattern, text):
            value = _parse_num(match.group(1))
            if value is not None:
                _add_number_fact(store, concept, value, match.start(), match.end(), unit)
                if concept == "glucose":
                    unit_text = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
                    high = value >= 11 if "mmol" in unit_text or not unit_text else value >= 200
                    if high:
                        sentence_start, _ = _sentence_bounds(text, match.start(), match.end())
                        assertion, temporality, experiencer = _assertion(text, sentence_start, match.start())
                        _add_fact(store, "hyperglycaemia", True, match.start(), match.end(), assertion, temporality, experiencer, "high")
                if concept == "systolic_bp" and value >= 140:
                    sentence_start, _ = _sentence_bounds(text, match.start(), match.end())
                    assertion, temporality, experiencer = _assertion(text, sentence_start, match.start())
                    _add_fact(store, "hypertension", True, match.start(), match.end(), assertion, temporality, experiencer, "high")


def _add_context_facts(store: FactStore) -> None:
    text = store.normalized
    context_patterns = {
        "male": r"\b(?:male|man|boy|gentleman)\b",
        "female": r"\b(?:female|woman|girl|lady)\b",
        "adult": r"\b(?:adult|grown[- ]up)\b",
        "frail": r"\b(?:frail|frailty)\b",
        "puerperium": r"\b(?:puerperium|postpartum|after delivery|after birth)\b",
        "fever": r"\b(?:fever|febrile|pyrexia|temperature)\b",
        "fever_two_days": r"\b(?:fever|febrile)\b[^.!?\n]{0,90}\b(?:two days|days?\s+\d+\s+and\s+\d+|postpartum days?\s+\d+\s+and\s+\d+)\b",
        "organism_confirmed": r"\b(?:confirmed|isolated|positive|grew|detected)\b[^.!?\n]{0,80}\b(?:organism|pathogen|culture|film|test|pcr|rt-?pcr)\b",
        "radiology_confirmed": r"\b(?:x-?ray|xray|radiograph|ultrasound|imaging|scan)\b[^.!?\n]{0,100}\b(?:shows?|confirmed|demonstrates?|evidence of)\b[^.!?\n]{0,80}\b(?:consolidation|pneumonia|collection|stone)\b",
    }
    for concept, pattern in context_patterns.items():
        for match in re.finditer(pattern, text):
            sentence_start, _ = _sentence_bounds(text, match.start(), match.end())
            assertion, temporality, experiencer = _assertion(text, sentence_start, match.start())
            _add_fact(store, concept, True, match.start(), match.end(), assertion, temporality, experiencer, "moderate")


def extract_facts(note_text: str) -> FactStore:
    normalized = normalize_for_search(note_text)
    store = FactStore(text=note_text, normalized=normalized)
    if not note_text.strip():
        store.warnings.append("empty_note")
        return store
    _add_alias_facts(store)
    _add_numeric_facts(store)
    _add_context_facts(store)
    # Repeated facts are common in copied templates; preserve their spans but
    # report a warning so the decision engine does not count them independently.
    keys = {(fact.concept, repr(fact.value), fact.assertion, fact.temporality) for fact in store.facts}
    if len(store.facts) > len(keys):
        store.warnings.append("repeated_or_copy_forward_facts")
    if "assessment" in normalized and "history" in normalized:
        store.warnings.append("section_context_present")
    return store
