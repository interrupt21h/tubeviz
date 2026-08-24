# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import numpy as np

from tubeviz.audio_ai import ClapSemanticAnalyzer


class FakeTensor:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)
        self.ndim = self.values.ndim

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class BaseModelOutputLike:
    def __init__(self, pooled):
        self.pooler_output = pooled


class ProjectionOutputLike:
    def __init__(self, *, text=None, audio=None):
        self.text_embeds = text
        self.audio_embeds = audio


def test_clap_current_base_model_output_uses_pooler_output():
    output = BaseModelOutputLike(FakeTensor([[3.0, 4.0], [0.0, 2.0]]))
    values = ClapSemanticAnalyzer._feature_array(output, modality="text")
    assert values.shape == (2, 2)
    np.testing.assert_allclose(np.linalg.norm(values, axis=1), [1.0, 1.0], atol=1e-6)
    np.testing.assert_allclose(values[0], [.6, .8], atol=1e-6)


def test_clap_legacy_direct_tensor_is_supported():
    tensor = FakeTensor([[1.0, 0.0, 0.0]])
    values = ClapSemanticAnalyzer._feature_array(tensor, modality="audio")
    np.testing.assert_allclose(values, [[1.0, 0.0, 0.0]], atol=1e-6)


def test_clap_projection_output_explicit_embeddings_are_supported():
    output = ProjectionOutputLike(text=FakeTensor([[0.0, 5.0]]))
    values = ClapSemanticAnalyzer._feature_array(output, modality="text")
    np.testing.assert_allclose(values, [[0.0, 1.0]], atol=1e-6)


def test_clap_tuple_output_prefers_two_dimensional_embedding():
    hidden = FakeTensor(np.zeros((2, 4, 8), dtype=np.float32))
    pooled = FakeTensor([[3.0, 4.0], [4.0, 3.0]])
    values = ClapSemanticAnalyzer._feature_array((hidden, pooled), modality="audio")
    assert values.shape == (2, 2)
    np.testing.assert_allclose(values[0], [.6, .8], atol=1e-6)
