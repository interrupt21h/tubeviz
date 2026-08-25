# SPDX-License-Identifier: Apache-2.0
from tubeviz.torch_device import resolve_torch_device


class _Cuda:
    def __init__(self, available=True, cap=(6,1), archs=None):
        self._available=available; self._cap=cap; self._archs=archs or ["sm_75","sm_80"]
    def is_available(self): return self._available
    def get_device_capability(self,index=0): return self._cap
    def get_arch_list(self): return list(self._archs)


class _MPS:
    def is_available(self): return False


class _Backends:
    mps=_MPS()


class FakeTorch:
    backends=_Backends()
    def __init__(self,cuda): self.cuda=cuda


def test_auto_falls_back_when_cuda_wheel_omits_gpu_architecture():
    device,warning=resolve_torch_device(FakeTorch(_Cuda(cap=(6,1),archs=["sm_75","sm_80"])),"auto")
    assert device=="cpu"
    assert "sm_61" in warning


def test_auto_uses_cuda_when_architecture_is_compiled():
    device,warning=resolve_torch_device(FakeTorch(_Cuda(cap=(6,1),archs=["sm_61","sm_75"])),"auto")
    assert device=="cuda"
    assert warning is None


def test_explicit_unsupported_cuda_is_an_error():
    try:
        resolve_torch_device(FakeTorch(_Cuda(cap=(6,1),archs=["sm_75"])),"cuda")
    except RuntimeError as exc:
        assert "sm_61" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
