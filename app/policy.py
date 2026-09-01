from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .corpus import Corpus
from .models import Candidate, CodeEntry, Evidence, Fact, FactStore, Guideline, ProblemResult


@dataclass(frozen=True)
class PolicyDecision:
    problems: tuple[ProblemResult, ...]
    trace: dict[str, object]


class CodingPolicy:
    """Evidence-constrained predicates over extracted facts.

    This layer deliberately does not assign a code from a keyword alone. Each
    rule has a positive definition, explicit exclusions, and a refusal path.
    Corpus records are selected by their meaning (title/text), so changing a
    record identifier does not change clinical behavior.
    """

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.codes = corpus.code_by_code
        self.guidelines = corpus.active_guidelines()
        self._used_guidelines: set[str] = set()

    def run(self, store: FactStore) -> PolicyDecision:
        self._used_guidelines = set()
        candidates: list[Candidate] = []
        rule_trace: list[str] = []
        candidates.extend(self._routine(store, rule_trace))
        candidates.extend(self._emergencies(store, rule_trace))
        candidates.extend(self._specific_rules(store, rule_trace))
        candidates.extend(self._explicit_diagnoses(store, rule_trace))

        # A single code should not be emitted twice when a general and a
        # specific predicate both fired. Keep the stronger candidate and keep
        # competing entries as candidates for reviewer visibility.
        by_code: dict[str, Candidate] = {}
        for candidate in candidates:
            previous = by_code.get(candidate.code.code)
            if previous is None or candidate.score > previous.score:
                by_code[candidate.code.code] = candidate
        candidates = sorted(by_code.values(), key=lambda item: (-item.score, item.code.code))

        # A supported complaint remains codable as a symptom only after no
        # underlying disease rule or explicit diagnosis was supported.
        gap_refusal = any("outside the supplied catalogue" in warning for warning in store.warnings)
        if not candidates and not gap_refusal:
            candidates.extend(self._symptom_fallback(store, rule_trace))

        if candidates:
            assignments, review_candidates = self._select(candidates)
            status = "accepted" if assignments else "unresolved"
            if assignments and any(item.provisional for item in assignments):
                status = "provisional"
            missing = sorted({item for candidate in candidates for item in candidate.missing})
            blockers = sorted({item for candidate in candidates for item in candidate.blockers})
            flags = sorted({item for candidate in candidates for item in candidate.safety_flags})
            if review_candidates:
                missing.extend(item for item in ("discriminating information for competing candidates",) if item not in missing)
                status = "unresolved" if not assignments else "review"
            problem = ProblemResult(
                problem_id="problem-1",
                span=None,
                status=status,
                assignments=assignments,
                candidates=review_candidates,
                missing_information=missing,
                unresolved_reasons=blockers,
                safety_flags=flags,
                evidence_ledger=self._ledger(candidates),
            )
            return PolicyDecision((problem,), {"rules_fired": rule_trace, "active_guidelines": sorted(self._used_guidelines)})

        reasons = list(store.warnings)
        reasons.append("no catalogue entry satisfied a complete rule definition")
        problem = ProblemResult(
            problem_id="problem-1",
            span=None,
            status="unresolved",
            missing_information=self._missing_for_unresolved(store),
            unresolved_reasons=reasons,
            safety_flags=["do_not_force_fit_to_nearest_catalogue_entry"],
            evidence_ledger=self._ledger(()),
        )
        return PolicyDecision((problem,), {"rules_fired": rule_trace, "active_guidelines": sorted(self._used_guidelines)})

    # --- Corpus and fact helpers -------------------------------------------------

    def _code(self, *terms: str) -> CodeEntry | None:
        normalized_terms = [term.casefold() for term in terms]
        target = " ".join(normalized_terms)
        exact_title = [entry for entry in self.corpus.catalogue if entry.title.casefold() == target]
        if exact_title:
            return exact_title[0]
        exact_synonym = [
            entry for entry in self.corpus.catalogue
            if any(synonym.casefold() == target for synonym in entry.synonyms)
        ]
        if exact_synonym:
            return exact_synonym[0]
        matches: list[tuple[int, int, CodeEntry]] = []
        for entry in self.corpus.catalogue:
            title = entry.title.casefold()
            haystack = f"{title} {' '.join(entry.synonyms).casefold()}"
            if all(term in haystack for term in normalized_terms):
                # Prefer the shortest title that contains a requested phrase;
                # this prevents a symptom such as "cough" selecting whooping
                # cough merely because it appears earlier in the catalogue.
                matches.append((0 if title.startswith(target) else 1, len(title), entry))
        return min(matches, key=lambda item: (item[0], item[1], item[2].code))[2] if matches else None

    def _guideline(self, *terms: str) -> Guideline:
        normalized_terms = [term.casefold() for term in terms]
        matches = [
            item for item in self.guidelines
            if all(term in f"{item.title} {item.text}".casefold() for term in normalized_terms)
        ]
        if matches:
            selected = sorted(matches, key=lambda item: (-item.effective_key, item.id))[0]
        else:
            selected = next(
                (item for item in self.guidelines if "confidence" in item.title.casefold()),
                self.guidelines[0],
            )
        self._used_guidelines.add(selected.id)
        return selected

    @staticmethod
    def _pos(store: FactStore, *concepts: str) -> bool:
        return store.any_positive(*concepts)

    @staticmethod
    def _fact(store: FactStore, *concepts: str) -> Fact | None:
        return store.first_positive(*concepts)

    @staticmethod
    def _historical(store: FactStore, concept: str) -> bool:
        return any(f.experiencer == "patient" and f.assertion in {"present", "historical"} for f in store.matching(concept))

    @staticmethod
    def _number(store: FactStore, concept: str) -> float | None:
        value = store.value(concept)
        if value is None and concept == "age_years":
            months = store.value("age_months")
            if isinstance(months, dict):
                months = months.get("value")
            if isinstance(months, (int, float)):
                return float(months) / 12.0
        if isinstance(value, dict):
            value = value.get("value")
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _at_most(store: FactStore, concept: str, threshold: float) -> bool:
        value = CodingPolicy._number(store, concept)
        return value is not None and value <= threshold

    @staticmethod
    def _at_least(store: FactStore, concept: str, threshold: float) -> bool:
        value = CodingPolicy._number(store, concept)
        return value is not None and value >= threshold

    def _candidate(
        self,
        store: FactStore,
        code_terms: tuple[str, ...],
        guideline_terms: tuple[str, ...],
        score: float,
        support: str,
        facts: Iterable[Fact] = (),
        *,
        confidence: str = "high",
        missing: Iterable[str] = (),
        blockers: Iterable[str] = (),
        flags: Iterable[str] = (),
        role: str = "primary",
        provisional: bool = False,
        problem: str = "encounter",
    ) -> Candidate | None:
        code = self._code(*code_terms)
        if code is None:
            return None
        guideline = self._guideline(*guideline_terms)
        evidence: list[Evidence] = [Evidence("catalogue", code.code, code.title, role="candidate catalogue entry")]
        evidence.append(Evidence("guideline", guideline.id, f"{guideline.title}: {guideline.text[:280]}", role="decision rule"))
        seen_spans: set[tuple[int, int]] = set()
        for fact in facts:
            if fact is None:
                continue
            if not fact.is_current_patient and fact.assertion != "historical":
                continue
            span = (fact.start, fact.end)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            evidence.append(Evidence("note", "note", fact.quote, span, role=fact.concept))
        return Candidate(
            code=code,
            guideline=guideline,
            score=score,
            support=support,
            confidence=confidence,
            evidence=tuple(evidence),
            missing=tuple(dict.fromkeys(missing)),
            blockers=tuple(dict.fromkeys(blockers)),
            safety_flags=tuple(dict.fromkeys(flags)),
            role=role,
            problem=problem,
            provisional=provisional,
        )

    @staticmethod
    def _ledger(candidates: Iterable[Candidate]) -> list[dict[str, object]]:
        ledger: list[dict[str, object]] = []
        for candidate in candidates:
            ledger.append({
                "code": candidate.code.code,
                "guideline_id": candidate.guideline.id,
                "support": candidate.support,
                "missing_information": list(candidate.missing),
                "blockers": list(candidate.blockers),
            })
        return ledger

    @staticmethod
    def _select(candidates: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
        viable = [item for item in candidates if not item.blockers and item.score >= 0.72]
        if not viable:
            return [], candidates
        # A high-risk branch can coexist with a source condition. Otherwise a
        # close score indicates a genuine ambiguity and must be shown.
        top = viable[0]
        competing = [item for item in viable[1:] if item.role == "primary" and top.role == "primary" and abs(item.score - top.score) < 0.08 and item.code.code != top.code.code]
        if competing and top.role == "primary":
            return [], viable
        selected = [top]
        for candidate in viable[1:]:
            if candidate.role == "complication" and candidate.code.code != top.code.code:
                selected.append(candidate)
        return selected, [item for item in candidates if item not in selected and (item.missing or item.blockers)]

    def _add(self, results: list[Candidate], candidate: Candidate | None, trace: list[str], name: str) -> None:
        if candidate is not None:
            results.append(candidate)
            trace.append(name)

    # --- high-consequence branches ---------------------------------------------

    def _emergencies(self, store: FactStore, trace: list[str]) -> list[Candidate]:
        results: list[Candidate] = []
        # Anaphylaxis takes precedence over isolated rash, wheeze or hypotension.
        if self._pos(store, "allergen_exposure") and self._pos(store, "skin_change", "mucosal_change") and self._pos(store, "respiratory_compromise", "hypotension"):
            facts = [self._fact(store, "allergen_exposure"), self._fact(store, "skin_change", "mucosal_change"), self._fact(store, "respiratory_compromise", "hypotension")]
            self._add(results, self._candidate(store, ("Anaphylaxis",), ("Anaphylaxis",), .99, "acute allergen exposure plus skin/mucosal involvement and respiratory or circulatory compromise", [f for f in facts if f], flags=("treat_first_emergency",)), trace, "anaphylaxis")

        if self._pos(store, "infection") and (self._pos(store, "altered_mentation", "oliguria", "raised_lactate") or self._at_most(store, "systolic_bp", 100) or self._at_least(store, "respiratory_rate", 22)):
            facts = [self._fact(store, "infection"), self._fact(store, "altered_mentation", "oliguria", "raised_lactate"), self._fact(store, "systolic_bp"), self._fact(store, "respiratory_rate")]
            shock = self._pos(store, "fluid_resuscitation") and self._pos(store, "vasopressors") and (self._pos(store, "hypotension") or self._at_most(store, "systolic_bp", 100))
            code_terms = ("Septic shock",) if shock else ("Sepsis", "without septic shock")
            self._add(results, self._candidate(store, code_terms, ("Sepsis",), .98 if shock else .91, "documented or strongly suspected infection with organ dysfunction" + (" and persistent hypotension requiring vasopressors" if shock else ""), [f for f in facts if f], flags=("time_critical",),), trace, "septic-shock" if shock else "sepsis")

        # The catalogue does not contain an acute-chest-syndrome entry; refusing
        # to label this as an uncomplicated sickle crisis is safer.
        if self._historical(store, "sickle_cell") and self._pos(store, "acute_chest_sign", "fever", "chest_pain"):
            self._add(results, self._candidate(store, ("Sickle cell", "crisis"), ("Sickle cell",), .60, "sickle cell disease with possible acute chest syndrome", [self._fact(store, "sickle_cell"), self._fact(store, "acute_chest_sign", "fever", "chest_pain")], confidence="low", blockers=("acute chest syndrome is not represented by a dedicated catalogue entry",), missing=("oxygenation, chest imaging and clinician confirmation",), flags=("urgent_review", "do_not_substitute_uncomplicated_crisis")), trace, "sickle-acute-chest")

        if self._pos(store, "saddle_anaesthesia", "bladder_bowel_disturbance", "bilateral_leg", "progressive_weakness"):
            self._add(results, self._candidate(store, ("Cauda equina",), ("Lower back pain",), .98, "back-pain red flag pattern requiring urgent spinal assessment", [self._fact(store, "saddle_anaesthesia", "bladder_bowel_disturbance", "bilateral_leg", "progressive_weakness")], flags=("urgent_review",)), trace, "cauda-equina")

        if self._pos(store, "stridor", "drooling", "trismus", "muffled_voice", "difficulty_swallowing_saliva"):
            airway_code = ("Epiglottitis",) if self._pos(store, "stridor", "difficulty_swallowing_saliva") else ("Peritonsillar abscess",)
            self._add(results, self._candidate(store, airway_code, ("Tonsillitis",), .96, "airway warning feature takes precedence over routine sore-throat coding", [self._fact(store, "stridor", "drooling", "trismus", "muffled_voice", "difficulty_swallowing_saliva")], flags=("airway_first", "urgent_review")), trace, "airway-warning")

        if self._pos(store, "head_injury") and self._pos(store, "focal_deficit", "repeated_vomiting", "convulsion", "anticoagulant", "persistent_deficit"):
            self._add(results, self._candidate(store, ("Intracranial injury",), ("Head injury",), .96, "head injury with an intracranial-injury warning feature", [self._fact(store, "head_injury"), self._fact(store, "focal_deficit", "repeated_vomiting", "convulsion", "anticoagulant", "persistent_deficit")], flags=("imaging_required", "urgent_review")), trace, "intracranial-injury")

        if self._pos(store, "pain_disproportionate", "rapid_progression", "skin_anaesthesia", "crepitus"):
            self._add(results, self._candidate(store, ("Bacterial skin infection",), ("Cellulitis",), .62, "soft-tissue red flags indicate a deeper necrotising process", [self._fact(store, "pain_disproportionate", "rapid_progression", "skin_anaesthesia", "crepitus")], confidence="low", blockers=("necrotising soft-tissue infection has no dedicated catalogue entry",), flags=("urgent_surgical_review",)), trace, "necrotising-soft-tissue-gap")
        return results

    # --- named guideline families -----------------------------------------------

    def _specific_rules(self, store: FactStore, trace: list[str]) -> list[Candidate]:
        results: list[Candidate] = []
        p = self._pos
        f = self._fact

        # Chest pain: reproducibility is a positive discriminator; cardiac
        # features are never inferred from the generic phrase "chest pain".
        if p(store, "chest_pain") and p(store, "chest_wall_tenderness") and p(store, "movement_worse", "deep_inspiration"):
            self._add(results, self._candidate(store, ("Costochondritis",), ("Reproducible chest wall pain",), .94, "localized chest pain reproduced over the chest wall with movement or inspiration", [f(store, "chest_pain"), f(store, "chest_wall_tenderness"), f(store, "movement_worse", "deep_inspiration")]), trace, "costochondritis")
        if p(store, "chest_pain") and p(store, "retrosternal", "exertional"):
            if p(store, "rest_pain", "increasing_frequency", "prolonged_pain"):
                missing = ("ECG, serial troponin and clinician documentation distinguishing unstable angina from infarction",)
                self._add(results, self._candidate(store, ("Unstable angina",), ("Exertional chest pain",), .64, "chest discomfort has an acute-coronary-syndrome feature", [f(store, "chest_pain"), f(store, "rest_pain", "increasing_frequency", "prolonged_pain")], confidence="low", missing=missing, blockers=("acute coronary syndrome subtype is not established by the note",), flags=("urgent_cardiac_review",)), trace, "acute-coronary-syndrome-uncertain")
            elif p(store, "rest_pain", "nitrate_relief") and (p(store, "exertional") or p(store, "retrosternal")):
                self._add(results, self._candidate(store, ("Angina pectoris",), ("Exertional chest pain",), .86, "retrosternal exertional discomfort relieved by rest or nitrate without acute warning features", [f(store, "chest_pain"), f(store, "exertional"), f(store, "nitrate_relief")]), trace, "stable-angina")

        if p(store, "loin_pain") and p(store, "groin_radiation") and p(store, "colicky") and p(store, "haematuria"):
            self._add(results, self._candidate(store, ("Calculus of kidney or ureter",), ("Renal colic",), .95, "unilateral colicky loin-to-groin pain with haematuria", [f(store, "loin_pain"), f(store, "groin_radiation"), f(store, "colicky"), f(store, "haematuria")]), trace, "renal-colic")

        if p(store, "periumbilical") and p(store, "right_iliac_fossa") and p(store, "pain_migration") and p(store, "mcburney", "guarding", "rebound"):
            self._add(results, self._candidate(store, ("Acute appendicitis",), ("Appendicitis",), .93, "migrating periumbilical to right-iliac-fossa pain with peritoneal findings", [f(store, "periumbilical"), f(store, "right_iliac_fossa"), f(store, "pain_migration"), f(store, "mcburney", "guarding", "rebound")]), trace, "appendicitis")

        if p(store, "otalgia") and p(store, "bulging_tm", "erythematous_tm", "opacified_tm"):
            self._add(results, self._candidate(store, ("Acute otitis media",), ("Acute otitis media",), .92, "acute otalgia with a qualifying tympanic-membrane finding", [f(store, "otalgia"), f(store, "bulging_tm", "erythematous_tm", "opacified_tm")]), trace, "acute-otitis-media")

        migraine_core = p(store, "unilateral") and p(store, "pulsating") and p(store, "moderate_severe") and p(store, "activity_aggravates") and (p(store, "nausea") or (p(store, "photophobia") and p(store, "phonophobia")))
        if migraine_core:
            self._add(results, self._candidate(store, ("Migraine",), ("Migraine features",), .93, "unilateral pulsating moderate-to-severe activity-aggravated headache with qualifying associated symptoms", [f(store, "unilateral"), f(store, "pulsating"), f(store, "moderate_severe"), f(store, "activity_aggravates"), f(store, "nausea", "photophobia")]), trace, "migraine")

        lower_uti = p(store, "dysuria") and p(store, "urinary_frequency", "urinary_urgency")
        upper_uti = p(store, "loin_pain", "cva_tenderness") or self._at_least(store, "temperature", 38.01)
        renal_colic = p(store, "loin_pain") and p(store, "groin_radiation") and p(store, "colicky") and p(store, "haematuria")
        if (lower_uti or p(store, "loin_pain", "cva_tenderness") or p(store, "asymptomatic_bacteriuria")) and not renal_colic:
            if p(store, "pregnancy"):
                self._add(results, self._candidate(store, ("Genitourinary infection in pregnancy",), ("Urinary tract infection: management",), .94, "urinary infection in pregnancy is assigned to the pregnancy-related entry", [f(store, "pregnancy"), f(store, "dysuria", "urinary_frequency", "urinary_urgency")]), trace, "pregnancy-uti")
            elif upper_uti:
                self._add(results, self._candidate(store, ("Acute pyelonephritis",), ("Urinary tract infection: management",), .93, "lower-tract symptoms with fever, loin pain or costovertebral-angle tenderness", [f(store, "dysuria", "urinary_frequency", "urinary_urgency"), f(store, "loin_pain", "cva_tenderness"), f(store, "temperature")]), trace, "upper-uti")
            else:
                recurrent = self._at_least(store, "episode_count", 3)
                male_without_prostate_workup = p(store, "male") and not p(store, "prostatitis", "prostatic_involvement")
                if recurrent or male_without_prostate_workup:
                    missing = ("structural-cause assessment for recurrent infection",) if recurrent else ("assessment for prostatic involvement",)
                    blockers = ("recurrent infection requires structural assessment before a simple lower-tract assignment",) if recurrent else ("male lower-tract symptoms require assessment for prostatic involvement",)
                    self._add(results, self._candidate(store, ("Acute cystitis",), ("Lower urinary tract infection",), .55, "lower-tract symptoms require additional recurrent/male-pathway discrimination", [f(store, "dysuria"), f(store, "urinary_frequency", "urinary_urgency")], confidence="low", missing=missing, blockers=blockers), trace, "lower-uti-needs-workup")
                else:
                    missing = ("adult sex and whether this is recurrent or complicated",) if not p(store, "female", "male") else ()
                    self._add(results, self._candidate(store, ("Acute cystitis",), ("Lower urinary tract infection",), .84, "dysuria with frequency or urgency and no upper-tract/systemic feature", [f(store, "dysuria"), f(store, "urinary_frequency", "urinary_urgency")], missing=missing), trace, "lower-uti")

        dka_features_present = sum(p(store, item) for item in ("hyperglycaemia", "ketones", "acidosis"))
        hhs_features_present = p(store, "hyperglycaemia") and p(store, "raised_osmolality") and p(store, "altered_mentation")
        if (p(store, "diabetes") or p(store, "type1_diabetes") or p(store, "type2_diabetes")) and not (dka_features_present >= 2 or hhs_features_present):
            if p(store, "type1_diabetes"):
                self._add(results, self._candidate(store, ("Type 1 diabetes",), ("Diabetes type attribution",), .94, "diabetes type is explicitly stated as type 1", [f(store, "type1_diabetes")]), trace, "type-1-diabetes")
            elif p(store, "type2_diabetes") or (p(store, "oral_agents") and p(store, "adult")):
                self._add(results, self._candidate(store, ("Type 2 diabetes",), ("Diabetes type attribution",), .90, "type 2 is documented or diabetes is managed on oral agents in an adult", [f(store, "type2_diabetes", "diabetes"), f(store, "oral_agents")]), trace, "type-2-diabetes")

        if p(store, "diarrhoea") and not p(store, "blood_stool", "pathogen"):
            self._add(results, self._candidate(store, ("Viral gastroenteritis",), ("Acute gastroenteritis",), .83, "acute diarrhoea with or without vomiting and no blood or documented pathogen", [f(store, "diarrhoea"), f(store, "vomiting")]), trace, "viral-gastroenteritis")
        if p(store, "diarrhoea") and p(store, "pathogen"):
            self._add(results, self._pathogen_candidate(store, trace), trace, "pathogen-gastroenteritis")

        # The age/frailty guidance adds documented complications to the
        # presenting gastrointestinal illness; it does not replace the source
        # illness.  Each complication is emitted as a secondary assignment.
        older_or_frail = self._at_least(store, "age_years", 70) or p(store, "frailty")
        if older_or_frail and p(store, "diarrhoea", "vomiting"):
            if p(store, "dehydration"):
                self._add(results, self._candidate(store, ("Dehydration",), ("Gastroenteritis in the older adult",), .80, "older or frail patient with gastrointestinal illness and documented volume depletion", [f(store, "dehydration")], role="complication", problem="gastrointestinal complication"), trace, "older-adult-dehydration")
            if p(store, "acute_kidney_injury"):
                self._add(results, self._candidate(store, ("Acute kidney injury",), ("Gastroenteritis in the older adult",), .79, "older or frail patient with gastrointestinal illness and documented acute kidney injury", [f(store, "acute_kidney_injury")], role="complication", problem="gastrointestinal complication"), trace, "older-adult-aki")
            if p(store, "confusion", "altered_mentation"):
                self._add(results, self._candidate(store, ("Altered mental status",), ("Gastroenteritis in the older adult",), .78, "new confusion in an older or frail patient indicates a systemic process", [f(store, "confusion", "altered_mentation")], role="complication", problem="gastrointestinal complication"), trace, "older-adult-confusion")

        # Malaria and dengue share a confirmation principle but have different
        # entries.  A positive test without species is not silently mapped to
        # the no-confirmation code.
        if p(store, "malaria"):
            malaria_facts = [f(store, "malaria"), f(store, "malaria_test"), f(store, "falciparum")]
            if p(store, "malaria_test") and p(store, "falciparum"):
                self._add(results, self._candidate(store, ("Plasmodium falciparum malaria",), ("Parasitological confirmation",), .93, "falciparum malaria with a positive blood film or rapid diagnostic test", [item for item in malaria_facts if item]), trace, "falciparum-confirmed")
            elif p(store, "malaria_test"):
                store.warnings.append("malaria is test-positive but species is not represented by a suitable confirmed catalogue entry")
                trace.append("malaria-species-gap")
            elif p(store, "endemic_area", "antimalarial_treatment"):
                self._add(results, self._candidate(store, ("Malaria without parasitological confirmation",), ("Parasitological confirmation",), .82, "malaria treated on clinical grounds in an endemic setting without a recorded test result", [f(store, "malaria"), f(store, "endemic_area", "antimalarial_treatment")], confidence="moderate", missing=("malaria film or rapid diagnostic test",)), trace, "malaria-unconfirmed")
            else:
                self._add(results, self._candidate(store, ("Malaria without parasitological confirmation",), ("Parasitological confirmation",), .55, "malaria is mentioned but neither a positive test nor clinical endemic-setting basis is recorded", [f(store, "malaria")], confidence="low", blockers=("test result or documented endemic-setting clinical treatment is missing",), missing=("malaria film/RDT and epidemiological context",)), trace, "malaria-uncertain")

        dengue_pattern = p(store, "fever") and p(store, "myalgia") and p(store, "retroorbital_pain") and p(store, "rash") and p(store, "thrombocytopenia")
        if p(store, "dengue") or dengue_pattern:
            severe_dengue = p(store, "warning_sign", "organ_dysfunction")
            if not p(store, "dengue_test"):
                self._add(results, self._candidate(store, ("Severe dengue",) if severe_dengue else ("Dengue fever",), ("Arboviral febrile illness",), .55, "dengue pattern is present but the required confirmation result is not recorded", [f(store, "dengue", "fever"), f(store, "warning_sign", "organ_dysfunction")], confidence="low", blockers=("dengue confirmation result is missing",), missing=("dengue laboratory confirmation",)), trace, "dengue-pending")
            elif dengue_pattern or p(store, "dengue"):
                self._add(results, self._candidate(store, ("Severe dengue",) if severe_dengue else ("Dengue fever",), ("Arboviral febrile illness",), .92, "confirmed dengue presentation" + (" with warning features" if severe_dengue else ""), [f(store, "dengue", "fever"), f(store, "dengue_test"), f(store, "warning_sign", "organ_dysfunction")], flags=("urgent_review",) if severe_dengue else ()), trace, "dengue-confirmed")

        septic_joint = p(store, "joint_swelling") and p(store, "fever") and p(store, "aspiration") and p(store, "synovial_culture", "synovial_microscopy")
        if septic_joint:
            self._add(results, self._candidate(store, ("Septic arthritis",), ("Crystal arthropathy",), .88, "febrile acutely swollen joint with synovial testing documented", [f(store, "joint_swelling"), f(store, "fever"), f(store, "aspiration"), f(store, "synovial_culture", "synovial_microscopy")], missing=("aspirate result",)), trace, "septic-arthritis")
        elif p(store, "first_mtp",) and p(store, "joint_swelling", "joint_erythema") and p(store, "exquisite_tenderness") and not p(store, "fever", "systemic_upset"):
            self._add(results, self._candidate(store, ("Gout",), ("Crystal arthropathy",), .87, "classic first-MTP inflammatory presentation without systemic features", [f(store, "first_mtp"), f(store, "joint_swelling", "joint_erythema"), f(store, "exquisite_tenderness")]), trace, "gout")
        elif p(store, "first_mtp", "joint_swelling") and p(store, "fever"):
            self._add(results, self._candidate(store, ("Gout",), ("Crystal arthropathy",), .58, "first-MTP swelling with fever is not safely distinguishable from septic arthritis", [f(store, "first_mtp"), f(store, "joint_swelling"), f(store, "fever")], confidence="low", blockers=("synovial microscopy and culture result required to distinguish crystal disease from septic arthritis",), missing=("aspiration result",), flags=("do_not_treat_classic_pattern_as_proof",)), trace, "gout-septic-ambiguity")

        if p(store, "hip_pain"):
            hip_age = self._number(store, "age_years")
            if hip_age is not None and hip_age >= 16 and p(store, "limp", "fever") and p(store, "inflammatory_markers"):
                if p(store, "aspiration"):
                    self._add(results, self._candidate(store, ("Septic arthritis",), ("Atraumatic painful hip",), .86, "acutely painful hip in an older child/adult with fever and raised inflammatory markers; aspiration documented", [f(store, "hip_pain"), f(store, "age_years"), f(store, "fever"), f(store, "inflammatory_markers"), f(store, "aspiration")], flags=("aspiration_before_antibiotics",)), trace, "septic-hip")
                else:
                    self._add(results, self._candidate(store, ("Septic arthritis",), ("Atraumatic painful hip",), .57, "painful hip meets the septic-arthritis work-up pattern but aspiration is not recorded", [f(store, "hip_pain"), f(store, "fever"), f(store, "inflammatory_markers")], confidence="low", blockers=("hip aspiration result is required before definitive assignment",), missing=("joint aspiration and culture",), flags=("urgent_review",)), trace, "septic-hip-pending")
            elif hip_age is not None and hip_age < 16 and p(store, "recent_viral_illness", "systemically_well") and p(store, "weight_bearing"):
                self._add(results, self._candidate(store, ("Transient synovitis of hip",), ("Atraumatic painful hip",), .86, "child with atraumatic hip pain after viral illness who is systemically well and weight-bearing", [f(store, "hip_pain"), f(store, "age_years"), f(store, "recent_viral_illness", "systemically_well"), f(store, "weight_bearing")]), trace, "transient-synovitis")
            else:
                self._add(results, self._candidate(store, ("Septic arthritis",), ("Atraumatic painful hip",), .52, "atraumatic hip pain is not safely classifiable from the documented findings", [f(store, "hip_pain")], confidence="low", blockers=("age, systemic state, inflammatory markers and ability to bear weight are unresolved",), missing=("age, fever, inflammatory markers and weight-bearing status")), trace, "hip-uncertain")

        if p(store, "jaw_claudication", "scalp_tenderness", "visual_disturbance") and self._at_least(store, "age_years", 50) and p(store, "inflammatory_markers"):
            store.warnings.append("large-vessel/giant-cell arteritis pattern is outside the supplied catalogue")
            trace.append("large-vessel-vasculitis-gap")

        if p(store, "focal_deficit"):
            if p(store, "persistent_deficit") and not p(store, "resolved_deficit"):
                self._add(results, self._candidate(store, ("Cerebral ischaemic stroke",), ("Transient focal neurological deficit",), .90, "focal neurological deficit persists at examination", [f(store, "focal_deficit"), f(store, "persistent_deficit")], flags=("urgent_review",)), trace, "persistent-stroke")
            elif p(store, "resolved_deficit"):
                if self._at_least(store, "episode_count", 2) or p(store, "recurrent_event"):
                    self._add(results, self._candidate(store, ("Cerebral ischaemic stroke",), ("Transient focal neurological deficit",), .68, "recurrent transient focal deficits form a high-risk cerebrovascular presentation", [f(store, "focal_deficit"), f(store, "resolved_deficit"), f(store, "episode_count", "recurrent_event")], confidence="low", blockers=("high-risk recurrent transient syndrome has no dedicated catalogue entry",), flags=("urgent_review",)), trace, "recurrent-tia-gap")
                else:
                    self._add(results, self._candidate(store, ("Transient ischaemic attack",), ("Transient focal neurological deficit",), .88, "focal deficit resolved completely with no residual sign", [f(store, "focal_deficit"), f(store, "resolved_deficit")]), trace, "tia")

        # Pneumonia uses the active confirmation revision. Clinical evidence is
        # deliberately provisional until consolidation is imaged.
        pneumonia_features = p(store, "fever") and p(store, "cough") and p(store, "crackles") and p(store, "dullness")
        if p(store, "pneumonia") or pneumonia_features:
            if p(store, "consolidation") and p(store, "chest_imaging", "radiology_confirmed"):
                self._add(results, self._candidate(store, ("Pneumonia",), ("Confirmation standard for pneumonia",), .91, "pneumonia supported by radiographic or point-of-care ultrasound consolidation", [f(store, "pneumonia"), f(store, "consolidation"), f(store, "chest_imaging", "radiology_confirmed")], role="source"), trace, "pneumonia-confirmed")
            elif pneumonia_features:
                self._add(results, self._candidate(store, ("Pneumonia",), ("Confirmation standard for pneumonia",), .76, "fever, productive cough and focal auscultatory findings support pneumonia but imaging confirmation is absent", [f(store, "fever"), f(store, "cough"), f(store, "crackles"), f(store, "dullness")], confidence="moderate", missing=("radiographic or point-of-care ultrasound confirmation of consolidation",), flags=("provisional_until_imaging",), provisional=True, role="source"), trace, "pneumonia-provisional")
            elif not (p(store, "infection") and (p(store, "altered_mentation", "oliguria", "raised_lactate") or self._at_most(store, "systolic_bp", 100) or self._at_least(store, "respiratory_rate", 22))):
                self._add(results, self._candidate(store, ("Pneumonia",), ("Confirmation standard for pneumonia",), .54, "pneumonia is mentioned without the active confirmation standard", [f(store, "pneumonia")], confidence="low", blockers=("imaging confirmation or qualifying clinical findings are missing",), missing=("chest imaging and complete respiratory examination",)), trace, "pneumonia-unsupported")

        known_asthma = self._historical(store, "asthma")
        if known_asthma and p(store, "wheeze") and p(store, "bronchodilator_response"):
            self._add(results, self._candidate(store, ("Acute asthma exacerbation",), ("Reversible and fixed airway obstruction",), .90, "established asthma with acute reversible obstruction", [f(store, "asthma"), f(store, "wheeze"), f(store, "bronchodilator_response")]), trace, "asthma-exacerbation")
        if p(store, "wheeze", "breathlessness") and self._at_least(store, "age_years", 40) and p(store, "smoking") and p(store, "fixed_obstruction"):
            self._add(results, self._candidate(store, ("COPD with acute exacerbation",), ("Reversible and fixed airway obstruction",), .89, "first adult wheeze/breathlessness presentation with smoking history and fixed obstruction", [f(store, "wheeze", "breathlessness"), f(store, "age_years"), f(store, "smoking"), f(store, "fixed_obstruction")]), trace, "fixed-airway-obstruction")
        if p(store, "wheeze") and p(store, "heart_failure_sign"):
            self._add(results, self._candidate(store, ("Acute decompensated heart failure",), ("Adult wheeze and the cardiac differential",), .88, "wheeze with pulmonary-congestion signs", [f(store, "wheeze"), f(store, "heart_failure_sign")]), trace, "cardiac-wheeze")

        triad = dka_features_present == 3
        hhs = hhs_features_present and not p(store, "ketones")
        if triad:
            self._add(results, self._candidate(store, ("Diabetic ketoacidosis",), ("Diabetic ketoacidosis",), .96, "hyperglycaemia, ketones and metabolic acidosis are documented together", [f(store, "hyperglycaemia"), f(store, "ketones"), f(store, "acidosis")], flags=("time_critical",)), trace, "dka")
        elif hhs:
            self._add(results, self._candidate(store, ("Hyperosmolar hyperglycaemic state",), ("Diabetic ketoacidosis",), .92, "marked hyperglycaemia with raised osmolality and altered mentation without significant ketones", [f(store, "hyperglycaemia"), f(store, "raised_osmolality"), f(store, "altered_mentation")]), trace, "hhs")
        elif sum(p(store, item) for item in ("hyperglycaemia", "ketones", "acidosis")) >= 2:
            self._add(results, self._candidate(store, ("Type 2 diabetes",), ("Diabetic ketoacidosis",), .55, "two DKA features support diabetes but do not establish the crisis triad", [f(store, item) for item in ("hyperglycaemia", "ketones", "acidosis") if f(store, item)], confidence="low", blockers=("third DKA criterion is missing",), missing=("complete glucose, ketone and acid-base results",)), trace, "partial-dka")

        # A pathogenic gastroenteritis entry is selected only when the organism
        # is actually named and present in the catalogue.
        if p(store, "pathogen") and p(store, "diarrhoea"):
            pass

        # Age- and context-qualified branches.
        if p(store, "convulsion") and p(store, "fever"):
            in_band = self._number(store, "age_years") is not None and 0.5 <= self._number(store, "age_years") <= 5
            if in_band and not p(store, "cns_infection", "prior_afebrile_seizure"):
                self._add(results, self._candidate(store, ("Febrile seizure",), ("Convulsion with fever",), .91, "fever-associated convulsion in the six-month-to-five-year band without CNS infection or prior afebrile seizure", [f(store, "convulsion"), f(store, "fever"), f(store, "age_years")]), trace, "febrile-seizure")
            elif not in_band:
                self._add(results, self._candidate(store, ("Seizure, unspecified",), ("Convulsion with fever",), .73, "febrile convulsion outside the febrile-seizure age band", [f(store, "convulsion"), f(store, "fever")], missing=("underlying cause of seizure",), flags=("investigate-underlying-cause",)), trace, "out-of-band-seizure")

        headache_days = self._at_least(store, "headache_days_per_month", 15)
        medication_days = self._at_least(store, "medication_days_per_month", 10)
        months = self._at_least(store, "duration_months", 3)
        if p(store, "headache") and p(store, "medication_overuse") and headache_days and medication_days and months:
            self._add(results, self._candidate(store, ("Medication-overuse headache",), ("Medication-overuse headache",), .94, "headache and medication-use frequency thresholds sustained for more than three months", [f(store, "headache"), f(store, "medication_overuse"), f(store, "headache_days_per_month"), f(store, "medication_days_per_month"), f(store, "duration_months")]), trace, "medication-overuse-headache")

        # Pregnancy bleeding and hypertensive disease.
        if p(store, "pregnancy") and p(store, "bleeding_early_pregnancy"):
            if p(store, "closed_os") and p(store, "viable_iup"):
                self._add(results, self._candidate(store, ("Threatened abortion",), ("Threatened miscarriage and ectopic",), .93, "early-pregnancy bleeding with closed os and viable intrauterine pregnancy", [f(store, "bleeding_early_pregnancy"), f(store, "closed_os"), f(store, "viable_iup")]), trace, "threatened-miscarriage")
            elif p(store, "pelvic_pain", "unilateral") and p(store, "haemodynamic_change", "orthostatic_change") and not p(store, "viable_iup"):
                self._add(results, self._candidate(store, ("Ectopic pregnancy",), ("Threatened miscarriage and ectopic",), .90, "early-pregnancy bleeding and unilateral pelvic pain with haemodynamic change before intrauterine visualisation", [f(store, "bleeding_early_pregnancy"), f(store, "pelvic_pain", "unilateral"), f(store, "orthostatic_change")], flags=("urgent_review",)), trace, "ectopic-pregnancy")
            else:
                self._add(results, self._candidate(store, ("Threatened abortion",), ("Threatened miscarriage and ectopic",), .55, "pregnancy bleeding does not yet distinguish threatened miscarriage from ectopic pregnancy", [f(store, "bleeding_early_pregnancy")], confidence="low", blockers=("cervical-os status, ultrasound location/viability and haemodynamic status are unresolved",), flags=("urgent_review",)), trace, "pregnancy-bleeding-uncertain")

        if p(store, "pregnancy") and p(store, "hypertension"):
            after20 = self._at_least(store, "gestational_weeks", 20.01)
            severe = self._at_least(store, "systolic_bp", 160) or self._at_most(store, "platelets", 99.99) or p(store, "pulmonary_oedema")
            preeclampsia = after20 and (p(store, "proteinuria", "headache", "visual_disturbance", "ruq_pain", "hyperreflexia") or p(store, "falling_platelets"))
            if preeclampsia:
                terms = ("Severe pre-eclampsia",) if severe else ("Pre-eclampsia",)
                self._add(results, self._candidate(store, terms, ("Hypertensive disorders of pregnancy",), .95 if severe else .91, "new hypertension after twenty weeks with proteinuria or a pre-eclampsia feature", [f(store, "pregnancy"), f(store, "hypertension"), f(store, "gestational_weeks"), f(store, "proteinuria", "headache", "visual_disturbance", "ruq_pain", "hyperreflexia")], flags=("urgent_review",) if severe else ()), trace, "severe-preeclampsia" if severe else "preeclampsia")
            elif after20:
                self._add(results, self._candidate(store, ("Gestational hypertension",), ("Hypertensive disorders of pregnancy",), .84, "new hypertension after twenty weeks without pre-eclampsia features", [f(store, "pregnancy"), f(store, "hypertension"), f(store, "gestational_weeks")], missing=("proteinuria and pre-eclampsia feature review",)), trace, "gestational-hypertension")
            else:
                self._add(results, self._candidate(store, ("Essential hypertension",), ("Hypertensive disorders of pregnancy",), .55, "hypertension before twenty weeks is chronic until clarified", [f(store, "pregnancy"), f(store, "hypertension")], confidence="low", blockers=("gestational age and pre-pregnancy blood-pressure history are required",)), trace, "chronic-hypertension-in-pregnancy")

        # Scrotal, biliary, back, skin, anaemia and injury pathways.
        if p(store, "scrotal_pain") and p(store, "unilateral"):
            if self._at_most(store, "duration_hours", 6) and p(store, "high_riding_testis", "absent_cremasteric"):
                self._add(results, self._candidate(store, ("Testicular torsion",), ("Acutely painful scrotum",), .96, "acute unilateral scrotal pain with torsion examination findings", [f(store, "scrotal_pain"), f(store, "unilateral"), f(store, "duration_hours"), f(store, "high_riding_testis", "absent_cremasteric")], flags=("urgent_review",)), trace, "testicular-torsion")
            elif p(store, "fever", "dysuria") and self._at_least(store, "duration_days", 1):
                self._add(results, self._candidate(store, ("Epididymo-orchitis",), ("Acutely painful scrotum",), .84, "gradual scrotal pain over days with fever or dysuria", [f(store, "scrotal_pain"), f(store, "duration_days"), f(store, "fever", "dysuria")]), trace, "epididymo-orchitis")
            else:
                self._add(results, self._candidate(store, ("Testicular torsion",), ("Acutely painful scrotum",), .55, "acute unilateral scrotal pain requires urgent torsion discrimination", [f(store, "scrotal_pain"), f(store, "unilateral")], confidence="low", blockers=("onset duration and testicular position/cremasteric reflex are missing",), flags=("urgent_review",)), trace, "scrotal-uncertain")

        if p(store, "ruq_pain") and p(store, "fatty_meal"):
            if p(store, "jaundice") and p(store, "rigors"):
                terms = ("Cholangitis",)
                name = "cholangitis"
            elif self._at_least(store, "duration_hours", 6) and p(store, "fever"):
                terms = ("Acute cholecystitis",)
                name = "acute-cholecystitis"
            elif not p(store, "fever"):
                terms = ("Cholelithiasis",)
                name = "biliary-colic"
            else:
                terms = ("Cholelithiasis",)
                name = "biliary-uncertain"
            self._add(results, self._candidate(store, terms, ("Right upper quadrant pain",), .92 if name != "biliary-uncertain" else .56, "right-upper-quadrant pain pattern" + (" with jaundice and rigors" if name == "cholangitis" else ""), [f(store, "ruq_pain"), f(store, "fatty_meal"), f(store, "jaundice", "rigors", "fever")], confidence="low" if name == "biliary-uncertain" else "high", blockers=("duration and infection features are insufficient to distinguish biliary diagnoses",) if name == "biliary-uncertain" else (), flags=("biliary_emergency",) if name == "cholangitis" else ()), trace, name)

        if p(store, "low_back_pain"):
            if p(store, "saddle_anaesthesia", "bladder_bowel_disturbance", "bilateral_leg", "progressive_weakness"):
                pass  # handled by the emergency branch above
            elif p(store, "night_pain", "weight_loss", "fever", "malignancy_history") or (self._at_least(store, "age_years", 50)):
                self._add(results, self._candidate(store, ("Low back pain",), ("Lower back pain and its red flags",), .56, "back pain has a red flag requiring investigation before mechanical assignment", [f(store, "low_back_pain"), f(store, "night_pain", "weight_loss", "fever", "malignancy_history"), f(store, "age_years")], confidence="low", blockers=("underlying cause of red-flag back pain is unresolved",), flags=("investigate-underlying-cause",)), trace, "back-red-flag")
            elif self._at_most(store, "age_years", 49) and not p(store, "focal_deficit", "fever", "weight_loss"):
                self._add(results, self._candidate(store, ("Low back pain",), ("Lower back pain and its red flags",), .82, "adult under fifty with mechanical low back pain and no documented red flag", [f(store, "low_back_pain"), f(store, "age_years")]), trace, "mechanical-back-pain")

        if p(store, "spreading_erythema") and p(store, "skin_warmth"):
            self._add(results, self._candidate(store, ("Bacterial skin infection",), ("Cellulitis",), .86, "spreading erythema and warm skin with an advancing edge", [f(store, "spreading_erythema"), f(store, "skin_warmth")]), trace, "cellulitis")

        hb = self._number(store, "haemoglobin_value")
        gestation = self._number(store, "gestational_weeks")
        if p(store, "pregnancy") and hb is not None:
            threshold = 10.5 if gestation is not None and 13 <= gestation <= 27 else 11.0
            if hb < threshold:
                self._add(results, self._candidate(store, ("Anaemia complicating pregnancy",), ("Anaemia in pregnancy",), .89, "haemoglobin below the pregnancy threshold", [f(store, "pregnancy"), f(store, "haemoglobin_value"), f(store, "gestational_weeks")]), trace, "anaemia-in-pregnancy")
            elif gestation is None and hb < 11:
                self._add(results, self._candidate(store, ("Anaemia complicating pregnancy",), ("Anaemia in pregnancy",), .53, "haemoglobin is in the trimester-dependent borderline range", [f(store, "pregnancy"), f(store, "haemoglobin_value")], confidence="low", blockers=("gestational age is required to apply the 10.5 versus 11 g/dL threshold",)), trace, "anaemia-trimester-uncertain")

        if p(store, "head_injury"):
            if p(store, "loss_awareness") and (self._at_most(store, "loss_awareness_seconds", 60) or p(store, "brief_loss")) and not p(store, "vomiting", "repeated_vomiting", "focal_deficit", "convulsion", "anticoagulant") and p(store, "normal_neurology"):
                self._add(results, self._candidate(store, ("Concussion",), ("Head injury",), .87, "head injury with brief loss of awareness, normal examination and no vomiting", [f(store, "head_injury"), f(store, "loss_awareness"), f(store, "normal_neurology")]), trace, "concussion")

        if p(store, "cough") and (self._at_least(store, "duration_days", 14) or self._at_least(store, "duration_weeks", 2) or p(store, "haemoptysis", "night_sweats", "weight_loss", "tb_contact", "tb")):
            if p(store, "tb_test"):
                self._add(results, self._candidate(store, ("Tuberculosis of the respiratory system",), ("Pulmonary tuberculosis",), .90, "characteristic pulmonary TB pathway with sputum or molecular test recorded", [f(store, "tb"), f(store, "cough"), f(store, "tb_test")]), trace, "pulmonary-tb-confirmed")
            else:
                self._add(results, self._candidate(store, ("Cough",), ("Pulmonary tuberculosis",), .55, "pulmonary tuberculosis is suspected but confirmation is not recorded", [f(store, "tb"), f(store, "cough")], confidence="low", blockers=("sputum microscopy or molecular testing result is missing",), missing=("TB test result",)), trace, "pulmonary-tb-pending")

        postpartum_days = self._number(store, "postpartum_days")
        fever_observations = len(store.positive("temperature"))
        if p(store, "puerperium") and p(store, "fever") and postpartum_days is not None and 1 < postpartum_days <= 10 and p(store, "uterine_tenderness", "offensive_lochia"):
            if fever_observations >= 2 or p(store, "fever_two_days") or self._at_least(store, "episode_count", 2):
                self._add(results, self._candidate(store, ("Puerperal sepsis",), ("Retained products and postpartum fever",), .92, "postpartum fever on at least two observations in the defined window with uterine or lochia infection feature", [f(store, "puerperium"), f(store, "fever"), f(store, "postpartum_days"), f(store, "uterine_tenderness", "offensive_lochia")], flags=("urgent_review",)), trace, "puerperal-sepsis")
            else:
                self._add(results, self._candidate(store, ("Puerperal sepsis",), ("Retained products and postpartum fever",), .54, "one qualifying postpartum fever is documented but the definition requires fever on two days", [f(store, "puerperium"), f(store, "fever"), f(store, "postpartum_days"), f(store, "uterine_tenderness", "offensive_lochia")], confidence="low", blockers=("a second qualifying fever observation/day is missing",), missing=("second fever observation within the first ten days",), flags=("urgent_review",)), trace, "puerperal-sepsis-incomplete")

        if p(store, "vertigo"):
            central = p(store, "new_deafness", "cranial_nerve_sign", "limb_ataxia", "unable_stand")
            if central:
                self._add(results, self._candidate(store, ("Dizziness",), ("Vertigo of peripheral origin",), .55, "vertigo has a central warning feature and is not safe to code as peripheral", [f(store, "vertigo"), f(store, "new_deafness", "cranial_nerve_sign", "limb_ataxia", "unable_stand")], confidence="low", blockers=("central cause and cerebrovascular risk require urgent assessment",), flags=("urgent_review",)), trace, "central-vertigo-uncertain")
            elif p(store, "positional_trigger") and p(store, "dix_hallpike") and p(store, "normal_neurology") and (self._at_most(store, "duration_seconds", 60) or self._at_most(store, "duration_minutes", 1)):
                self._add(results, self._candidate(store, ("Vertigo, peripheral",), ("Vertigo of peripheral origin",), .91, "brief positional vertigo with positive Dix-Hallpike and no central warning", [f(store, "vertigo"), f(store, "positional_trigger"), f(store, "dix_hallpike"), f(store, "duration_seconds")]), trace, "bppv")

        if p(store, "sore_throat") and p(store, "tonsillar_exudate") and p(store, "cervical_nodes") and p(store, "fever") and p(store, "absence_cough"):
            self._add(results, self._candidate(store, ("Tonsillitis",), ("Tonsillitis and the sore throat",), .90, "exudative sore throat with tender nodes, fever and absent cough", [f(store, "sore_throat"), f(store, "tonsillar_exudate"), f(store, "cervical_nodes"), f(store, "fever"), f(store, "absence_cough")]), trace, "tonsillitis")

        if self._historical(store, "sickle_cell") and p(store, "vaso_occlusive_pain") and not p(store, "acute_chest_sign", "fever", "chest_pain"):
            self._add(results, self._candidate(store, ("Sickle cell crisis",), ("Sickle cell painful crisis",), .89, "acute limb, back or chest pain in known sickle cell disease without an alternative explanation", [f(store, "sickle_cell"), f(store, "vaso_occlusive_pain")], flags=("time_critical_analgesia",)), trace, "sickle-crisis")

        return results

    def _pathogen_candidate(self, store: FactStore, trace: list[str]) -> Candidate | None:
        text = store.normalized
        organisms = (
            ("escherichia coli", ("Escherichia coli enteritis",), ("e coli", "escherichia coli")),
            ("salmonella", ("Salmonella enteritis",), ("salmonella",)),
            ("shigella", ("Shigellosis",), ("shigella",)),
            ("campylobacter", ("Campylobacter enteritis",), ("campylobacter",)),
            ("cholera", ("Cholera",), ("cholera",)),
            ("entamoeba", ("Amoebiasis",), ("entamoeba",)),
            ("giardia", ("Giardiasis",), ("giardia",)),
        )
        for label, code_terms, mentions in organisms:
            if any(re.search(rf"(?<!\w){re.escape(mention)}(?!\w)", text) for mention in mentions):
                fact = self._fact(store, "pathogen")
                candidate = self._candidate(store, code_terms, ("Specificity of assignment",), .88, f"{label} is documented as the causative organism for gastroenteritis", [fact] if fact else (), confidence="high")
                return candidate
        return None

    # --- routine encounters, symptoms, and explicit diagnoses -------------------

    def _routine(self, store: FactStore, trace: list[str]) -> list[Candidate]:
        if any(store.positive(concept) for concept in ("chest_pain", "headache", "cough", "diarrhoea", "vomiting", "dysuria", "sore_throat", "pain", "fever", "vertigo")):
            return []
        mapping = (
            ("screening", ("Antenatal screening",), "screening"),
            ("immunisation", ("Immunisation encounter",), "immunisation"),
            ("contraception", ("Contraceptive management",), "contraception"),
            ("routine_exam", ("General examination",), "routine examination"),
            ("follow_up", ("Follow-up examination",), "scheduled review"),
        )
        for concept, code_terms, label in mapping:
            fact = self._fact(store, concept)
            if fact:
                candidate = self._candidate(store, code_terms, ("Encounter records with no presenting complaint",), .90, f"{label} encounter with no new complaint documented", [fact])
                if candidate:
                    trace.append("routine-" + concept)
                    return [candidate]
        return []

    def _explicit_diagnoses(self, store: FactStore, trace: list[str]) -> list[Candidate]:
        text = store.normalized
        results: list[Candidate] = []
        assessment_markers = r"(?:assessment|impression|diagnosis|diagnosed|confirmed|documented|consistent with|final diagnosis)"
        for entry in self.corpus.catalogue:
            terms = (entry.title,) + entry.synonyms
            match = None
            for term in sorted(terms, key=len, reverse=True):
                if len(term) < 4:
                    continue
                found = re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", text)
                if found:
                    before = text[max(0, found.start() - 150):found.start()]
                    if re.search(assessment_markers, before) and not re.search(r"\b(?:rule out|query|possible|family history|no evidence of|denies)\b", before[-90:]):
                        match = found
                        break
            if match is None:
                continue
            # A specialized rule already carries higher confidence and more
            # context; this is only a broad documentation fallback.
            fact = Fact(entry.title, True, "present", "current", "patient", match.start(), match.end(), store.text[match.start():match.end()], confidence="moderate")
            candidate = self._candidate(store, (entry.title,), ("Specificity of assignment",), .78, "the condition is explicitly documented in the assessment/impression", [fact], confidence="moderate")
            if candidate:
                results.append(candidate)
        if results:
            trace.append("explicit-diagnosis-resolution")
        return results

    def _symptom_fallback(self, store: FactStore, trace: list[str]) -> list[Candidate]:
        mappings = (
            (("chest_pain",), ("Chest pain",), "presenting chest pain remains without an established underlying diagnosis"),
            (("headache",), ("Headache, unspecified",), "headache remains without an established primary or secondary diagnosis"),
            (("cough",), ("Cough",), "cough remains without an established underlying diagnosis"),
            (("breathlessness", "respiratory_compromise"), ("Dyspnoea",), "breathlessness remains without an established underlying diagnosis"),
            (("diarrhoea",), ("Abdominal pain",), "gastrointestinal complaint lacks a supported disease entry"),
            (("vertigo",), ("Dizziness",), "dizziness/vertigo lacks a supported cause"),
            (("convulsion",), ("Seizure, unspecified",), "convulsion lacks a supported underlying cause"),
        )
        for concepts, code_terms, support in mappings:
            fact = self._fact(store, *concepts)
            if fact:
                candidate = self._candidate(store, code_terms, ("Assigning a symptom code",), .73, support, [fact], confidence="low", missing=("clinician-confirmed underlying diagnosis",), flags=("symptom_code_only",))
                if candidate:
                    trace.append("symptom-fallback")
                    return [candidate]
        return []

    @staticmethod
    def _missing_for_unresolved(store: FactStore) -> list[str]:
        if not store.text.strip():
            return ["a non-empty clinical note"]
        return ["a documented assessment or enough discriminating clinical findings to satisfy a catalogue rule"]
