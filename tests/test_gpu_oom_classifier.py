import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from gpu_oom import bisect_cuda_oom, configure_memory_limit, is_cuda_oom, recover_cuda_after_oom


class FakeTorchOom(RuntimeError):
    pass


def fake_torch(empty_cache=None):
    return SimpleNamespace(cuda=SimpleNamespace(
        OutOfMemoryError=FakeTorchOom,
        empty_cache=empty_cache or mock.Mock(),
    ))


class CudaOomClassifierTests(unittest.TestCase):
    def test_accepts_brandon_exact_runtime_error_form(self):
        exc = RuntimeError("CUDA error: out of memory")
        self.assertTrue(is_cuda_oom(exc, fake_torch()))

    def test_accepts_pytorch_oom_class_regardless_of_message(self):
        self.assertTrue(is_cuda_oom(FakeTorchOom("allocation failed"), fake_torch()))

    def test_rejects_unrelated_cuda_runtime_error(self):
        exc = RuntimeError("CUDA error: an illegal memory access was encountered")
        self.assertFalse(is_cuda_oom(exc, fake_torch()))

    def test_rejects_unqualified_out_of_memory_runtime_error(self):
        self.assertFalse(is_cuda_oom(RuntimeError("CPU out of memory"), fake_torch()))
        self.assertFalse(is_cuda_oom(RuntimeError("out of memory"), fake_torch()))
        self.assertFalse(is_cuda_oom(RuntimeError("notcuda out of memory"), fake_torch()))

    def test_rejects_non_runtime_exception_with_same_words(self):
        self.assertFalse(is_cuda_oom(ValueError("CUDA error: out of memory"), fake_torch()))


class MemoryBudgetTests(unittest.TestCase):
    def test_budget_accounts_for_card_size_free_memory_and_workers(self):
        for total_gb, free_gb, workers, expected_gb in [
            (24, 23, 1, 19.2), (16, 15, 1, 12.6), (8, 7, 1, 5.8),
            (24, 12, 1, 8.4), (24, 23, 2, 9.6),
        ]:
            with self.subTest(total_gb=total_gb, free_gb=free_gb, workers=workers):
                cuda = fake_torch().cuda
                cuda.mem_get_info = lambda: (int(free_gb * 1024**3), int(total_gb * 1024**3))
                cuda.set_per_process_memory_fraction = mock.Mock()
                budget = configure_memory_limit(SimpleNamespace(cuda=cuda), workers)
                self.assertAlmostEqual(budget / 1024**3, expected_gb, places=6)
                cuda.set_per_process_memory_fraction.assert_called_once_with(budget / (total_gb * 1024**3))

    def test_busy_gpu_fails_before_model_load(self):
        cuda = fake_torch().cuda
        cuda.mem_get_info = lambda: (1024**3, 24 * 1024**3)
        cuda.set_per_process_memory_fraction = mock.Mock()
        with self.assertRaises(FakeTorchOom):
            configure_memory_limit(SimpleNamespace(cuda=cuda))
        cuda.set_per_process_memory_fraction.assert_not_called()


class CudaOomBisectionTests(unittest.TestCase):
    def test_runtime_error_bisection_preserves_order(self):
        torch_module = fake_torch()
        calls = []

        def operation(items):
            calls.append(tuple(items))
            if len(items) > 1:
                raise RuntimeError("CUDA error: out of memory")
            return [items[0] * 10]

        result = bisect_cuda_oom([1, 2, 3, 4], operation, torch_module)

        self.assertEqual(result, [10, 20, 30, 40])
        self.assertEqual(calls, [
            (1, 2, 3, 4), (1, 2), (1,), (2,), (3, 4), (3,), (4,),
        ])
        self.assertEqual(torch_module.cuda.empty_cache.call_count, 3)

    def test_single_item_reraises_original_oom(self):
        torch_module = fake_torch()
        original = RuntimeError("CUDA error: out of memory")

        def fail(_items):
            raise original

        with self.assertRaises(RuntimeError) as raised:
            bisect_cuda_oom([1], fail, torch_module)
        self.assertIs(raised.exception, original)
        torch_module.cuda.empty_cache.assert_called_once_with()

    def test_unrelated_runtime_error_is_not_split_or_cleared(self):
        torch_module = fake_torch()
        calls = []

        def fail(items):
            calls.append(tuple(items))
            raise RuntimeError("CUDA error: device-side assert triggered")

        with self.assertRaisesRegex(RuntimeError, "device-side assert"):
            bisect_cuda_oom([1, 2], fail, torch_module)
        self.assertEqual(calls, [(1, 2)])
        torch_module.cuda.empty_cache.assert_not_called()

    def test_cache_cleanup_failure_does_not_mask_original_oom(self):
        torch_module = fake_torch(mock.Mock(side_effect=RuntimeError("sticky CUDA state")))
        recover_cuda_after_oom(torch_module)


if __name__ == "__main__":
    unittest.main()
