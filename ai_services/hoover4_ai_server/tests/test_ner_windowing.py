"""Verify complete NER input coverage with the installed Transformers pipeline."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from fastapi import HTTPException
from transformers import BertConfig, BertForTokenClassification, BertTokenizerFast, pipeline
from transformers.modeling_outputs import TokenClassifierOutput

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hoover4_ai_server as server


class NerWindowingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        vocabulary = [
            "[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]",
            "text", "Maria", "Popescu", "București", "Київ", "café",
        ]
        path = Path(self.directory.name) / "vocab.txt"
        path.write_text("\n".join(vocabulary) + "\n")
        tokenizer = BertTokenizerFast(vocab_file=str(path), do_lower_case=False,
                                      model_max_length=16)
        labels = {0: "O", 1: "B-PER", 2: "I-PER", 3: "B-LOC"}
        model = BertForTokenClassification(BertConfig(
            vocab_size=len(vocabulary), hidden_size=8, num_hidden_layers=1,
            num_attention_heads=1, intermediate_size=8, max_position_embeddings=16,
            id2label=labels, label2id={value: key for key, value in labels.items()},
        ))
        self.calls = []
        self.fail_call = None

        def forward(_model, input_ids, **kwargs):
            self.calls.append(tuple(input_ids.shape))
            if self.fail_call == len(self.calls):
                raise RuntimeError("Injected later-window failure")
            logits = torch.full((*input_ids.shape, len(labels)), -10.0)
            logits[..., 0] = 10.0
            for token, label in [("Maria", 1), ("Popescu", 2), ("București", 3), ("Київ", 3)]:
                mask = input_ids == vocabulary.index(token)
                logits[mask] = -10.0
                logits[..., label][mask] = 10.0
            return TokenClassifierOutput(logits=logits)

        model.forward = types.MethodType(forward, model)
        self.pipeline = pipeline("ner", model=model, tokenizer=tokenizer,
                                 aggregation_strategy="simple", device=-1)
        for name, value in {
            "ner_model": self.pipeline,
            "ner_stride": server.configure_ner_windowing(self.pipeline),
            "OPTIMAL_BATCH_SIZE": 2,
        }.items():
            context = patch.object(server, name, value)
            context.start()
            self.addCleanup(context.stop)

    def request(self, text, **kwargs):
        return server.extract_entities(server.NERRequest(input=text, **kwargs))

    def test_beginning_boundary_middle_and_tail_keep_original_offsets(self):
        text = " ".join(["Maria", "Popescu"] + ["text"] * 11
                        + ["Maria", "Popescu", "café", "București"]
                        + ["text"] * 36 + ["Київ"])
        result = self.request(text)
        self.assertEqual((result.coverage_version, result.processed_inputs), (2, 1))
        spans = [(entity.label, text[entity.start:entity.end]) for entity in result.data]
        self.assertEqual(spans, [("PER", "Maria Popescu"), ("PER", "Maria Popescu"),
                                 ("LOC", "București"), ("LOC", "Київ")])
        identities = [(entity.start, entity.end, entity.label) for entity in result.data]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertTrue(all(entity.text_index is None for entity in result.data))
        self.assertGreater(len(self.calls), 1)
        self.assertTrue(all(batch <= 2 and tokens <= 16 for batch, tokens in self.calls))

    def test_multiple_inputs_keep_their_indices_and_entity_filter(self):
        texts = ["text " * 40 + "Maria Popescu", "café " * 40 + "Київ"]
        result = self.request(texts, entity_types=["LOC"], include_confidence=False)
        self.assertEqual((result.coverage_version, result.processed_inputs), (2, 2))
        self.assertEqual(len(result.data), 1)
        entity = result.data[0]
        self.assertEqual(entity.text_index, 1)
        self.assertEqual(texts[1][entity.start:entity.end], "Київ")
        self.assertIsNone(entity.confidence)

    def test_later_window_failure_returns_no_partial_result_and_can_retry(self):
        text = "Maria Popescu " + "text " * 50 + "Київ"
        self.fail_call = 2
        with self.assertRaises(HTTPException) as caught:
            self.request(text)
        self.assertEqual(caught.exception.status_code, 500)
        self.assertIn("Injected later-window failure", caught.exception.detail)
        self.fail_call = None
        self.calls.clear()
        result = self.request(text)
        self.assertEqual([text[entity.start:entity.end] for entity in result.data],
                         ["Maria Popescu", "Київ"])

    def test_complete_input_without_entities_returns_empty_result(self):
        self.assertEqual(self.request("text " * 50).data, [])
        self.assertGreater(len(self.calls), 1)

    def test_window_configuration_refuses_unsupported_tokenizers(self):
        candidate = types.SimpleNamespace(tokenizer=types.SimpleNamespace(is_fast=False))
        with self.assertRaisesRegex(ValueError, "fast tokenizer"):
            server.configure_ner_windowing(candidate)


if __name__ == "__main__":
    unittest.main()
