"""Conservative CUDA out-of-memory recognition and recovery helpers.

This module deliberately does not import torch so its safety behavior can be
regression-tested in the base environment. Callers pass their torch module.
"""

import gc
import re
import traceback


def configure_memory_limit(torch_module, workers=1):
    """Leave physical VRAM headroom before loading models or creating tensors.

    The input-token bucket budget cannot bound generated speech or KV-cache
    growth. An allocator limit makes oversized batches raise CUDA OOM before
    Windows has to back those allocations with shared system memory.
    """
    if workers < 1:
        raise ValueError("workers must be positive")
    free, total = torch_module.cuda.mem_get_info()
    headroom = max(1024 ** 3, int(total * 0.15))
    allowed = min(int(total * 0.80) // workers, (free - headroom) // workers)
    if allowed <= 0:
        raise torch_module.cuda.OutOfMemoryError(
            "CUDA out of memory: insufficient free VRAM to reserve narration headroom"
        )
    torch_module.cuda.set_per_process_memory_fraction(allowed / total)
    return allowed


def is_cuda_oom(exc, torch_module=None):
    """True only for PyTorch's OOM type or a CUDA-qualified OOM RuntimeError."""
    cuda = getattr(torch_module, "cuda", None)
    oom_type = getattr(cuda, "OutOfMemoryError", None)
    if isinstance(oom_type, type) and isinstance(exc, oom_type):
        return True
    if not isinstance(exc, RuntimeError):
        return False
    message = " ".join(str(exc).lower().split())
    return re.search(r"\bcuda\b", message) is not None and "out of memory" in message


def recover_cuda_after_oom(torch_module, exc=None):
    """Drop Python references and clear cached allocations without masking OOM.

    Do not synchronize here. A CUDA error can be reported asynchronously, and
    forcing a synchronization may raise another device error that obscures the
    original recoverable OOM. empty_cache is best-effort for the same reason.
    """
    if exc is not None:
        try:
            traceback.clear_frames(exc.__traceback__)
        except Exception:
            pass
    gc.collect()
    try:
        torch_module.cuda.empty_cache()
    except Exception:
        pass


def bisect_cuda_oom(items, operation, torch_module, on_split=None):
    """Run an ordered batch, recursively halving only on classified CUDA OOM.

    A failing single item is a hard limit and its original exception is raised.
    Successful halves are concatenated left-to-right, preserving chunk order.
    """
    items = list(items)
    try:
        return list(operation(items))
    except Exception as exc:
        if not is_cuda_oom(exc, torch_module):
            raise
        recover_cuda_after_oom(torch_module, exc)
        if len(items) <= 1:
            raise
        mid = len(items) // 2
        if on_split is not None:
            on_split(len(items), len(items[:mid]), len(items[mid:]), exc)
        return (
            bisect_cuda_oom(items[:mid], operation, torch_module, on_split)
            + bisect_cuda_oom(items[mid:], operation, torch_module, on_split)
        )
