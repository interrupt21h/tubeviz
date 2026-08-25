# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations


def cuda_arch_supported(torch, index: int = 0) -> tuple[bool, str]:
    """Return whether this torch build has code for the selected CUDA GPU.

    torch.cuda.is_available() only proves that the runtime can initialize. A
    wheel may still omit kernels for an older GPU (for example sm_61 Pascal).
    """
    if not torch.cuda.is_available():
        return False, "CUDA runtime is unavailable"
    try:
        major, minor = torch.cuda.get_device_capability(index)
        wanted = f"sm_{major}{minor}"
        archs = set(torch.cuda.get_arch_list())
        if not archs:
            return True, f"GPU {wanted}; torch did not report a compiled architecture list"
        if wanted in archs:
            return True, f"GPU {wanted} is supported"
        # Some wheels carry PTX for a compute target. Only accept an exact
        # compute capability because forward PTX compatibility does not make a
        # newer cubin runnable on an older device.
        return False, f"GPU requires {wanted}; installed torch supports {', '.join(sorted(archs))}"
    except Exception as exc:
        return False, f"unable to verify CUDA architecture compatibility: {exc}"


def resolve_torch_device(torch, requested: str = "auto") -> tuple[str, str | None]:
    if requested != "auto":
        if str(requested).startswith("cuda"):
            index = 0
            if ":" in str(requested):
                try:
                    index = int(str(requested).split(":", 1)[1])
                except ValueError:
                    pass
            ok, reason = cuda_arch_supported(torch, index)
            if not ok:
                raise RuntimeError(f"requested CUDA device is not usable: {reason}")
        return requested, None
    if torch.cuda.is_available():
        ok, reason = cuda_arch_supported(torch, 0)
        if ok:
            return "cuda", None
        warning = reason
    else:
        warning = None
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", warning
    return "cpu", warning
