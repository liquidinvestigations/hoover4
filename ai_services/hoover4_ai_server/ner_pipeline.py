"""NER token grouping with the Python work limited to the tokens that form entities."""

import numpy as np
from transformers import TokenClassificationPipeline
from transformers.pipelines.token_classification import AggregationStrategy


class EntityTokenPipeline(TokenClassificationPipeline):
    """Build token records only for tokens that can change the grouped entities.

    The stock `gather_pre_entities` builds one Python record for each token, and that work
    holds the interpreter lock while the GPU waits. The `simple` strategy drops `O` groups,
    so one `O` token after each entity is enough to keep the two sides apart.
    """

    def gather_pre_entities(self, sentence, input_ids, scores, offset_mapping, special_tokens_mask,
                            aggregation_strategy, word_ids=None, word_to_chars_map=None):
        if aggregation_strategy != AggregationStrategy.SIMPLE or offset_mapping is None or word_ids is not None:
            return super().gather_pre_entities(sentence, input_ids, scores, offset_mapping, special_tokens_mask,
                                               aggregation_strategy, word_ids=word_ids,
                                               word_to_chars_map=word_to_chars_map)
        entity = scores.argmax(axis=-1) != self.model.config.label2id["O"]
        after_entity = ~entity & np.concatenate(([True], entity[:-1]))
        keep = np.flatnonzero((entity | after_entity) & (special_tokens_mask == 0))
        ids = np.asarray(input_ids)[keep].tolist()
        words = self.tokenizer.convert_ids_to_tokens(ids)
        offsets = np.asarray(offset_mapping)[keep].tolist()
        unknown = self.tokenizer.unk_token_id
        return [{"word": sentence[start:end] if token_id == unknown else word, "scores": scores[index],
                 "start": start, "end": end, "index": int(index), "is_subword": False}
                for index, token_id, word, (start, end) in zip(keep, ids, words, offsets)]
