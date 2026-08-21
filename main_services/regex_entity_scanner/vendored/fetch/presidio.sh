#!/usr/bin/env bash
# Microsoft Presidio — MIT.
# Not our engine — it is Python, it has neither money nor units, and it emits spans for redaction
# rather than canonical values. Its predefined recognisers are still the best available checklist of
# PII entity types and per-country identifier formats, each declaring whether it validates by
# pattern, by checksum or by context.
#
# The recogniser test modules come with them, and they are the reason this snapshot is larger than
# the recognisers alone: each one is a parametrised list of free-text fragments with the spans
# upstream asserts are in them, including the fragments upstream asserts hold nothing. That is the
# shape of the question this service is asked — an identifier inside a sentence — rather than a
# validator called on a bare token, so it is the conformance corpus for the rules whose subjects
# only ever appear in prose. The model-backed recogniser tests are left behind: they assert against
# spaCy, Stanza, transformer and cloud back-ends and carry no pattern data.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/microsoft/presidio.git presidio)"
target="${REFERENCE}/presidio"
replace_dir "$target"
cp -r "${src}/presidio-analyzer/presidio_analyzer/predefined_recognizers" "${target}/"

mkdir -p "${target}/tests"
for test in "${src}"/presidio-analyzer/tests/test_*_recognizer.py; do
    case "$(basename "$test")" in
        test_ahds_* | test_azure_* | test_basic_langextract_* | test_gliner_* \
            | test_huggingface_* | test_lm_* | test_medical_ner_* | test_spacy_* \
            | test_stanza_* | test_transformers_*) continue ;;
    esac
    cp "$test" "${target}/tests/"
done

cp "${src}/LICENSE" "${LICENSES}/presidio.LICENSE"
stamp "$target" "https://github.com/microsoft/presidio" "$(git_head "$src")"
note "$(find "${target}/predefined_recognizers" -name '*.py' | wc -l) recogniser modules"
note "$(find "${target}/tests" -name '*.py' | wc -l) recogniser test modules"
