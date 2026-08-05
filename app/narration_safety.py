"""Small, dependency-free narration safety helpers.

Keep this module importable in the base Python environment so capped-token
recovery can be tested without loading Chatterbox, torch, or CUDA.
"""


class RunawayGenerationError(RuntimeError):
    """Raised when a speech-token row repeatedly fails to emit EOS."""


def repair_capped_sequences(
    sequences,
    max_new_tokens,
    retry_one,
    *,
    max_attempts=3,
    on_retry=None,
):
    """Regenerate rows that consumed the entire decode budget.

    A sequence whose length equals ``max_new_tokens`` did not emit EOS: EOS is
    not appended to the returned sequence, so even EOS on the final decode step
    produces at most ``max_new_tokens - 1`` speech tokens. Such a row must not
    be vocoded because its tail becomes audible dead air.

    ``retry_one(row_index, attempt)`` performs an isolated one-row generation
    and returns its speech-token sequence. A repeatedly capped row fails the
    job and remains resumable instead of silently corrupting finished audio.
    """
    if max_new_tokens <= 0:
        raise ValueError("max_new_tokens must be positive")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    repaired = list(sequences)
    for row, sequence in enumerate(repaired):
        if len(sequence) < max_new_tokens:
            continue
        for attempt in range(1, max_attempts + 1):
            if on_retry:
                on_retry(row, attempt, len(sequence))
            candidate = retry_one(row, attempt)
            if len(candidate) < max_new_tokens:
                repaired[row] = candidate
                break
            sequence = candidate
        else:
            raise RunawayGenerationError(
                f"speech-token row {row} reached the {max_new_tokens}-token "
                f"cap on the original generation and {max_attempts} retries"
            )
    return repaired
