"""Classify historical OCR evidence of one source file without reading storage.

The OCR processing update and the read-only assessment command call `classify_file` with
the same evidence, so the assessment counts the work that execution does. The caller reads
the rows and objects. This module only compares values.

The evidence of one file has these parts.

* `FileEvidence` names the dataset, the content hash, the source kind and the source
  revision. The source kind is `image`, `original` or `preview`.
* `eligible` lists the one-based physical pages that automatic OCR examines. It is `None`
  when the source has no prepared page list, because then no physical page identity exists.
* `Detection` is the stored detection result of one eligible page. Its state is `current`,
  `missing`, `outdated` or `failed`.
* `Candidate` is one stored recognition result. Its form is a `raw_ocr_results` row, a
  `pdf_ocr_parts` variant, a saved raster PDF, an overlay PDF without page text, or
  automatic plan output.
* A candidate keeps the engine and the exact language string of its execution. It also
  keeps the physical pages that it completed, a digest of each page text, and its artifacts.
* `retired` is not empty when a later publication already replaced the result.
* `AppliedPlan` is the newest published or applied automatic plan of the file.
* `Contract` holds the captured installed models and the requested policy and capability
  identity. It also tells whether searchable PDFs are required.

`classify_file` returns a `FileDecision`. Each eligible page has one primary action:

| Action | Meaning |
|---|---|
| `keep_current` | The current publication satisfies the contract. No work. |
| `reuse_text` | Accepted historical text needs publication under its canonical identity. |
| `artifact_only` | The text is published. Only a searchable PDF needs reconstruction. |
| `no_text` | Detection found no text and no historical text exists. |
| `no_text_replace` | Detection found no text. Historical text is replaced by the empty result. |
| `new_ocr` | No historical result is compatible. The automatic planner selects the pass. |
| `require_detection` | Current detection is missing, outdated or failed. |
| `unresolved` | A required page identity or artifact cannot be recovered without OCR. |

A page with accepted text lists the extra work in `work`. One page can need text
publication and PDF reconstruction together. The file action is the page action with the
highest rank in `ACTION_ORDER`.

These identity rules apply.

* Language membership is an exact code in the stored language string. Script models, script
  groups and substrings are no proof of a language.
* Simplified and traditional Han, and Serbian Cyrillic and Latin, are separate identities.
* The canonical identity keeps the original engine and uses the engine code of the detected
  language. A historical `eng+deu` page with detected `de` publishes as `tesseract` `deu`.
* When more than one candidate gives the same canonical identity, an exact language set
  wins over a superset. A tie uses `FORM_RANK`, then the candidate identity.
  The other candidates stay in `duplicates`.
* An unknown language keeps each recoverable result under its original identity.
* A candidate identity includes a digest of its page texts. A candidate whose pages do not
  match its recorded digest is rejected.
"""

import dataclasses
import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Optional

from tasks.automatic_ocr import (EASY_SCRIPT_GROUPS, LANGUAGE_SCRIPTS, POLICY_VERSION, TESSERACT_LANGUAGES,
                                 choose_pass, digest, document_script)
from tasks.text_sources import (ENGINE_EASYOCR, ENGINE_TESSERACT, ocr_extracted_by, pdf_ocr_extracted_by,
                                split_languages)

#: The version of the classification rules. A manifest records it with each adoption.
RECOVERY_POLICY_VERSION = 1

DETECTION_CURRENT = "current"
DETECTION_MISSING = "missing"
DETECTION_OUTDATED = "outdated"
DETECTION_FAILED = "failed"

#: Stored historical forms, in the order that breaks a tie between equal candidates.
FORM_AUTOMATIC = "automatic"
FORM_PDF_PARTS = "pdf_parts"
FORM_RAW_IMAGE = "raw_image"
FORM_RASTER_PDF = "raster_pdf"
FORM_OVERLAY_PDF = "overlay_pdf"
FORM_RANK = {FORM_AUTOMATIC: 0, FORM_PDF_PARTS: 1, FORM_RAW_IMAGE: 2, FORM_RASTER_PDF: 3, FORM_OVERLAY_PDF: 4}

KEEP_CURRENT = "keep_current"
REUSE_TEXT = "reuse_text"
ARTIFACT_ONLY = "artifact_only"
NO_TEXT = "no_text"
NO_TEXT_REPLACE = "no_text_replace"
NEW_OCR = "new_ocr"
REQUIRE_DETECTION = "require_detection"
UNRESOLVED = "unresolved"
#: File actions by rank. The highest page action names the file action.
ACTION_ORDER = (REQUIRE_DETECTION, UNRESOLVED, NEW_OCR, NO_TEXT_REPLACE, REUSE_TEXT, ARTIFACT_ONLY,
                NO_TEXT, KEEP_CURRENT)

WORK_TEXT = "text_publication"
WORK_INDEX = "dependent_indexing"
WORK_PDF_WORDS = "pdf_from_word_boxes"
WORK_PDF_PAGES = "pdf_from_saved_pages"

ARTIFACT_PRESENT = "present"
ARTIFACT_UNCHECKED = "unchecked"
ARTIFACT_MISSING = "missing"
ARTIFACT_TRUNCATED = "truncated"
ARTIFACT_WRONG_OWNER = "wrong_owner"

#: The `model` of a detection row for an image that the service cannot decode.
UNDECODABLE = "undecodable"
#: The character that text layer version 1 wrote for a letter outside Windows-1252.
BLACK_SQUARE = "■"
#: The text layer version that keeps every character.
CURRENT_TEXT_LAYER = 2
#: An image PDF needs at least this many qualifying words, as in automatic image output.
IMAGE_PDF_MIN_WORDS = 5

_TESSERACT_IDENTITY = {code: (language, "") for language, code in TESSERACT_LANGUAGES.items()}
_TESSERACT_IDENTITY.update({"chi_sim": ("zh", "HanS"), "chi_tra": ("zh", "HanT"),
                            "srp": ("sr", "Cyrillic"), "srp_latn": ("sr", "Latin")})
_EASYOCR_IDENTITY = {code: (code, "") for codes in EASY_SCRIPT_GROUPS.values() for code in codes}
_EASYOCR_IDENTITY.update({"ch_sim": ("zh", "HanS"), "ch_tra": ("zh", "HanT"),
                          "rs_cyrillic": ("sr", "Cyrillic"), "rs_latin": ("sr", "Latin")})
_IDENTITIES = {ENGINE_TESSERACT: _TESSERACT_IDENTITY, ENGINE_EASYOCR: _EASYOCR_IDENTITY}


def text_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _qualifying_words(text: str) -> int:
    from tasks.P3_parse_files.image_pdf import qualifying_words
    return qualifying_words(text)


@dataclass(frozen=True)
class PageText:
    """Properties of one recovered physical page text. The text itself stays with the caller."""
    page_id: int
    digest: str
    chars: int = 0
    words: int = 0
    squares: bool = False
    cp1252: bool = True

    @classmethod
    def of(cls, page_id: int, text: str) -> "PageText":
        text = text or ""
        try:
            text.encode("cp1252")
            cp1252 = True
        except UnicodeEncodeError:
            cp1252 = False
        return cls(int(page_id), text_digest(text), len("".join(text.split())), _qualifying_words(text),
                   BLACK_SQUARE in text, cp1252)


@dataclass(frozen=True)
class Artifact:
    """A stored searchable PDF that covers physical pages `first_page` to `last_page`."""
    bucket: str
    key: str
    first_page: int
    last_page: int
    size_bytes: int = 0
    state: str = ARTIFACT_UNCHECKED
    #: 0 when the record does not store the version.
    text_layer: int = 0


@dataclass(frozen=True)
class Candidate:
    form: str
    #: The stored record identity without its content, for example `pdf_ocr_parts|1|3`.
    record: str
    engine: str
    languages: str
    source_kind: str
    pages: tuple = ()
    content_digest: str = ""
    retired: str = ""
    word_boxes: bool = False
    artifacts: tuple = ()
    #: The reason that the page texts are not recovered, for example `raster_not_read`. It is empty after recovery.
    recovery: str = ""
    plan_digest: str = ""

    @property
    def candidate_id(self) -> str:
        return digest([self.form, self.record, self.source_kind, self.engine, self.languages,
                       self.content_digest])[:32]

    def page(self, page_id: int) -> Optional[PageText]:
        return next((page for page in self.pages if page.page_id == page_id), None)


def pages_digest(pages: Iterable[PageText]) -> str:
    """The content digest of a candidate: its physical pages and their text digests."""
    return digest(sorted([page.page_id, page.digest] for page in pages))


def make_candidate(**values) -> Candidate:
    """Build a candidate and record the digest of the supplied page texts."""
    pages = tuple(sorted(values.pop("pages", ()), key=lambda page: page.page_id))
    return Candidate(pages=pages, content_digest=pages_digest(pages), **values)


@dataclass(frozen=True)
class Detection:
    page_id: int
    state: str = DETECTION_CURRENT
    has_text: bool = False
    script: str = ""
    model: str = ""
    language: str = "und"
    detector_version: int = 0

    def row(self) -> dict:
        """The detection fields in the shape that the automatic planner reads."""
        return dict(page_id=self.page_id, has_text=int(self.has_text), script=self.script,
                    language=self.language, detector_version=self.detector_version, model=self.model)

    @property
    def digest(self) -> str:
        return digest(self.row())


@dataclass(frozen=True)
class AppliedPlan:
    plan_digest: str
    state: str
    policy_version: int
    capability_digest: str
    source_revision: str
    #: page_id -> (detector digest, status, ((engine, languages), ...))
    pages: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Contract:
    capabilities: dict
    #: The requested capability identity. Empty when an applied marker cannot prove that its
    #: output satisfies the requested contract, as after a stage version change.
    capability_digest: str = ""
    policy_version: int = POLICY_VERSION
    searchable_pdf: bool = True


@dataclass(frozen=True)
class FileEvidence:
    collection_dataset: str
    file_hash: str
    source_kind: str
    source_revision: str
    eligible: Optional[tuple] = None
    detections: tuple = ()
    candidates: tuple = ()
    applied: Optional[AppliedPlan] = None
    #: The OCR `extracted_by` values of the file that `text_content` holds now.
    published: tuple = ()
    #: The current source ranges as `(first_page, last_page)`.
    source_ranges: tuple = ()


@dataclass
class Accepted:
    candidate_id: str
    form: str
    engine: str
    original_languages: str
    canonical_languages: str
    extracted_by: str
    reason: str
    empty: bool = False
    work: list = field(default_factory=list)
    missing: list = field(default_factory=list)


@dataclass
class PageDecision:
    page_id: int
    action: str
    reason: str
    detection: str
    accepted: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    replaced: list = field(default_factory=list)
    retained: list = field(default_factory=list)
    retired_compatible: list = field(default_factory=list)
    planned: list = field(default_factory=list)
    work: list = field(default_factory=list)
    missing: list = field(default_factory=list)


@dataclass
class FileDecision:
    collection_dataset: str
    file_hash: str
    source_kind: str
    source_revision: str
    policy_version: int
    action: str
    reason: str
    pages: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    #: Historical text on pages outside the eligible list, as page counts by candidate.
    outside_eligible: dict = field(default_factory=dict)
    decision_digest: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def language_identity(engine: str, code: str) -> Optional[tuple]:
    """`(language, variant)` of one stored engine code, or None for a script model or unknown code."""
    return _IDENTITIES.get(engine, {}).get(code)


def detected_identity(found: Detection) -> Optional[tuple]:
    """`(language, variant)` of a detected page, or None when detection names no reliable language."""
    language, script = found.language or "und", found.script or ""
    if language == "und":
        return None
    if language == "sr":
        return ("sr", "Latin" if script == "Latin" else "Cyrillic") if script in ("Latin", "Cyrillic") else None
    if LANGUAGE_SCRIPTS.get(language) != script:
        return None
    if language == "zh":
        return "zh", "HanT" if found.model == "HanT" else "HanS"
    return language, ""


def _extractor(source_kind: str):
    return ocr_extracted_by if source_kind == "image" else pdf_ocr_extracted_by


def _sort_key(candidate: Candidate, exact: bool) -> tuple:
    return (0 if exact else 1, FORM_RANK.get(candidate.form, 9), candidate.candidate_id)


def _usable(candidate: Candidate, page_id: int) -> Optional[str]:
    """Return the reason the candidate cannot supply this page, or None."""
    if candidate.recovery:
        return candidate.recovery
    page = candidate.page(page_id)
    if page is None:
        return "page_not_covered"
    if page.squares:
        return "text_has_black_squares"
    return None


def _artifact_for(candidate: Candidate, page_id: int) -> Optional[Artifact]:
    return next((item for item in candidate.artifacts if item.first_page <= page_id <= item.last_page and item.key), None)


def _artifact_work(evidence: FileEvidence, contract: Contract, candidate: Candidate, accepted: Accepted, page_id: int):
    """Add the searchable PDF work and missing evidence of one accepted page."""
    if not contract.searchable_pdf:
        return
    page = candidate.page(page_id)
    if evidence.source_kind == "image" and page.words < IMAGE_PDF_MIN_WORDS:
        return
    if evidence.source_kind != "image" and page.chars == 0:
        return
    artifact = _artifact_for(candidate, page_id)
    usable = artifact is not None and artifact.state in (ARTIFACT_PRESENT, ARTIFACT_UNCHECKED)
    layer_ok = usable and (artifact.text_layer >= CURRENT_TEXT_LAYER or page.cp1252)
    if evidence.source_kind == "image":
        if usable and layer_ok and candidate.retired == "":
            return
        if candidate.word_boxes:
            accepted.work.append(WORK_PDF_WORDS)
        elif artifact is not None and not usable:
            accepted.missing.append("artifact_" + artifact.state)
        else:
            accepted.missing.append("word_boxes_missing")
        return
    if artifact is None:
        accepted.missing.append("artifact_missing")
    elif not usable:
        accepted.missing.append("artifact_" + artifact.state)
    elif not layer_ok:
        accepted.missing.append("text_layer_defective")
    elif (candidate.retired or candidate.languages != accepted.canonical_languages
          or (artifact.first_page, artifact.last_page) not in evidence.source_ranges):
        accepted.work.append(WORK_PDF_PAGES)


def _accept(evidence, contract, candidate, page_id, canonical, reason) -> Accepted:
    page = candidate.page(page_id)
    extracted_by = _extractor(evidence.source_kind)(candidate.engine, canonical)
    accepted = Accepted(candidate.candidate_id, candidate.form, candidate.engine, candidate.languages,
                        canonical, extracted_by, reason, empty=page.chars == 0)
    if extracted_by not in evidence.published or candidate.retired:
        accepted.work += [WORK_TEXT, WORK_INDEX]
    _artifact_work(evidence, contract, candidate, accepted, page_id)
    return accepted


def _language_matches(candidate: Candidate, wanted: tuple) -> Optional[tuple]:
    """`(canonical code, exact)` when the stored language set holds the detected language."""
    codes = split_languages(candidate.languages)
    for code in codes:
        if language_identity(candidate.engine, code) == wanted:
            return code, len(codes) == 1
    return None


def _applied_page(evidence: FileEvidence, contract: Contract, found: Detection, planned: dict) -> Optional[str]:
    """The reason the applied automatic plan already satisfies this page, or None."""
    applied = evidence.applied
    if applied is None or applied.source_revision != evidence.source_revision:
        return None
    stored = applied.pages.get(found.page_id)
    if stored is None or stored[0] != found.digest:
        return None
    if (applied.state == "applied" and contract.capability_digest
            and applied.capability_digest == contract.capability_digest
            and applied.policy_version == contract.policy_version):
        return "applied_plan_current"
    passes = tuple(tuple(item) for item in stored[2])
    wanted = tuple((item["engine"], item["languages"]) for item in planned.get("passes", []))
    if stored[1] == planned.get("status") and passes == wanted:
        return "applied_pass_matches_plan"
    return None


def classify_page(evidence: FileEvidence, contract: Contract, found: Detection,
                  candidates: list, fallback: dict) -> PageDecision:
    """Decide one eligible page. `candidates` holds valid candidates of the file's source kind."""
    detection = found.state
    if found.state == DETECTION_CURRENT:
        detection = ("current_no_text" if not found.has_text else
                     "current_unknown_language" if (found.language or "und") == "und" else "current_text")
    decision = PageDecision(found.page_id, "", "", detection)
    live = [item for item in candidates if not item.retired and _usable(item, found.page_id) is None]
    with_text = [item for item in live if item.page(found.page_id).chars > 0]
    if found.state != DETECTION_CURRENT:
        decision.action, decision.reason = REQUIRE_DETECTION, "detection_" + found.state
        decision.retained = sorted(item.candidate_id for item in live)
        return decision
    if found.model == UNDECODABLE and not found.has_text:
        if with_text:
            decision.action, decision.reason = UNRESOLVED, "undecodable_with_historical_text"
            decision.retained = sorted(item.candidate_id for item in with_text)
        else:
            decision.action, decision.reason = NO_TEXT, "detected_undecodable"
        return decision
    planned = choose_pass(found.row(), contract.capabilities, fallback)
    current = _applied_page(evidence, contract, found, planned)
    if current:
        decision.action, decision.reason = KEEP_CURRENT, current
        _note_retired(decision, candidates, found)
        return decision
    if not found.has_text:
        if with_text:
            decision.action, decision.reason = NO_TEXT_REPLACE, "detected_no_text_replaces_history"
            decision.replaced = sorted(item.candidate_id for item in with_text)
        else:
            decision.action, decision.reason = NO_TEXT, "detected_no_text"
        return decision
    wanted = detected_identity(found)
    groups = {}
    for candidate in live:
        if wanted is not None:
            match = _language_matches(candidate, wanted)
            if match:
                groups.setdefault((candidate.engine, match[0]), []).append((candidate, match[1], "detected_language"))
                continue
        pass_ids = [(item["engine"], item["languages"]) for item in planned.get("passes", [])]
        if planned.get("status") == "ready" and (candidate.engine, candidate.languages) in pass_ids:
            groups.setdefault((candidate.engine, candidate.languages), []).append((candidate, True, "planned_pass"))
        elif wanted is None and (found.language or "und") == "und":
            groups.setdefault((candidate.engine, candidate.languages), []).append(
                (candidate, True, "unknown_language_retained"))
    for (engine, canonical), members in sorted(groups.items()):
        members.sort(key=lambda member: _sort_key(member[0], member[1]))
        chosen, exact, reason = members[0]
        if reason == "detected_language":
            reason = "detected_language_exact" if exact else "detected_language_superset"
        decision.accepted.append(_accept(evidence, contract, chosen, found.page_id, canonical, reason))
        decision.duplicates += [member[0].candidate_id for member in members[1:]]
    accepted_ids = {item.candidate_id for item in decision.accepted} | set(decision.duplicates)
    decision.replaced = sorted(item.candidate_id for item in with_text if item.candidate_id not in accepted_ids)
    _note_retired(decision, candidates, found)
    if not decision.accepted:
        unverified = sorted((item.recovery, item.candidate_id) for item in candidates
                            if not item.retired and item.recovery and _could_match(item, wanted, found))
        if unverified:
            decision.action, decision.reason = UNRESOLVED, unverified[0][0]
            decision.retained = [candidate_id for _, candidate_id in unverified]
            decision.missing = sorted({reason for reason, _ in unverified})
        elif planned.get("status") != "ready":
            decision.action, decision.reason = UNRESOLVED, "planner_" + planned.get("reason", "unavailable")
        else:
            decision.action = NEW_OCR
            decision.reason = ("language_script_mismatch" if wanted is None and found.language != "und"
                               else "no_compatible_history")
            decision.planned = [dict(engine=item["engine"], languages=item["languages"]) for item in planned["passes"]]
        return decision
    for item in decision.accepted:
        decision.work += [work for work in item.work if work not in decision.work]
        decision.missing += [missing for missing in item.missing if missing not in decision.missing]
    if decision.missing:
        decision.action, decision.reason = UNRESOLVED, decision.missing[0]
    elif WORK_TEXT in decision.work:
        decision.action, decision.reason = REUSE_TEXT, decision.accepted[0].reason
    elif decision.work:
        decision.action, decision.reason = ARTIFACT_ONLY, decision.accepted[0].reason
    else:
        decision.action, decision.reason = KEEP_CURRENT, "historical_result_published"
    return decision


def _could_match(candidate: Candidate, wanted: Optional[tuple], found: Detection) -> bool:
    """Whether a result without recovered page text has a language set that fits the page."""
    if wanted is not None:
        return _language_matches(candidate, wanted) is not None
    return (found.language or "und") == "und"


def _note_retired(decision: PageDecision, candidates: list, found: Detection) -> None:
    """List retired results that would match this page. A later publication already replaced them."""
    wanted = detected_identity(found)
    for item in candidates:
        if not item.retired or _usable(item, found.page_id) is not None:
            continue
        if item.page(found.page_id).chars == 0:
            continue
        if wanted is None or _language_matches(item, wanted):
            decision.retired_compatible.append(item.candidate_id)
    decision.retired_compatible.sort()


def _validate(evidence: FileEvidence, candidate: Candidate) -> Optional[str]:
    if candidate.source_kind != evidence.source_kind:
        return "source_kind_mismatch"
    if candidate.content_digest != pages_digest(candidate.pages):
        return "content_digest_mismatch"
    if len({page.page_id for page in candidate.pages}) != len(candidate.pages):
        return "duplicate_page_identity"
    return None


def classify_file(evidence: FileEvidence, contract: Contract) -> FileDecision:
    """Classify every eligible page of one source. The result does not depend on input order."""
    decision = FileDecision(evidence.collection_dataset, evidence.file_hash, evidence.source_kind,
                            evidence.source_revision, RECOVERY_POLICY_VERSION, "", "")
    candidates = []
    for candidate in sorted(evidence.candidates, key=lambda item: item.candidate_id):
        problem = _validate(evidence, candidate)
        if problem:
            decision.rejected.append([candidate.candidate_id, problem])
        else:
            candidates.append(candidate)
    if evidence.eligible is None:
        decision.action, decision.reason = REQUIRE_DETECTION, "source_not_prepared"
    else:
        eligible = sorted(set(evidence.eligible))
        found = {item.page_id: item for item in evidence.detections}
        current = [item.row() for item in found.values() if item.state == DETECTION_CURRENT]
        fallback = document_script(current)
        for page_id in eligible:
            decision.pages.append(classify_page(evidence, contract, found.get(page_id, Detection(page_id, DETECTION_MISSING)),
                                                candidates, fallback))
        for candidate in candidates:
            outside = [page.page_id for page in candidate.pages if page.page_id not in eligible and page.chars > 0]
            if outside:
                decision.outside_eligible[candidate.candidate_id] = len(outside)
        actions = [page.action for page in decision.pages]
        if not actions:
            decision.action, decision.reason = KEEP_CURRENT, "no_eligible_pages"
        else:
            decision.action = next(action for action in ACTION_ORDER if action in actions)
            decision.reason = next(page.reason for page in decision.pages if page.action == decision.action)
    decision.decision_digest = digest({key: value for key, value in decision.as_dict().items() if key != "decision_digest"})
    return decision
