"""Spectral k-DPP sampling (Kulesza & Taskar 2012, sections 2.4.3 and 5.2.2).

https://www.alexkulesza.com/pubs/dpps_fnt12.pdf
Log elementary symmetric polynomials avoid overflow; QR updates the projection basis.
"""

import numpy as np

from ai_judge.phase1.errors import OperationError


def sample_k_dpp(kernel: np.ndarray, k: int, seed: int, tolerance: float = 1e-10) -> list[int]:
    matrix = np.asarray(kernel, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or not np.isfinite(matrix).all():
        raise OperationError("invalid_kernel")
    size = len(matrix)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= size:
        raise OperationError("invalid_k")
    if not np.isfinite(tolerance) or not 0 < tolerance < 1:
        raise OperationError("invalid_tolerance")
    scale = np.max(np.abs(matrix))
    if scale == 0:
        raise OperationError("insufficient_kernel_rank")
    matrix = matrix / scale  # Uniform scaling does not change a fixed-k distribution.
    if not np.allclose(matrix, matrix.T, rtol=tolerance, atol=tolerance):
        raise OperationError("non_symmetric_kernel")
    try:
        eigenvalues, eigenvectors = np.linalg.eigh((matrix + matrix.T) / 2)
    except np.linalg.LinAlgError:
        raise OperationError("kernel_eigendecomposition_failed") from None
    threshold = tolerance * max(float(eigenvalues.max()), 1.0)
    if eigenvalues.min() < -threshold:
        raise OperationError("non_psd_kernel")
    positive = eigenvalues > threshold
    if np.count_nonzero(positive) < k:
        raise OperationError("insufficient_kernel_rank")
    # Only roundoff-scale eigenvalues are discarded; no jitter or random fallback.
    eigenvalues = eigenvalues[positive]
    eigenvectors = eigenvectors[:, positive]
    log_values = np.log(eigenvalues / eigenvalues.max())
    count = len(eigenvalues)
    log_e = np.full((k + 1, count + 1), -np.inf)
    log_e[0, :] = 0
    for n in range(1, count + 1):
        for degree in range(1, min(k, n) + 1):
            log_e[degree, n] = np.logaddexp(
                log_e[degree, n - 1],
                log_values[n - 1] + log_e[degree - 1, n - 1],
            )
    rng = np.random.Generator(np.random.PCG64(seed))
    remaining, selected = k, []
    for n in range(count, 0, -1):
        if remaining == 0:
            break
        probability = float(
            np.exp(log_values[n - 1] + log_e[remaining - 1, n - 1] - log_e[remaining, n])
        )
        if remaining == n or rng.random() < np.clip(probability, 0, 1):
            selected.append(n - 1)
            remaining -= 1
    if remaining:
        raise OperationError("unstable_eigenvector_selection")
    basis = eigenvectors[:, selected]
    samples = []
    for dimension in range(k, 0, -1):
        probabilities = np.square(basis).sum(axis=1)
        probabilities[samples] = 0
        total = probabilities.sum()
        if not np.isfinite(total) or total <= 0:
            raise OperationError("unstable_projection")
        item = int(rng.choice(size, p=probabilities / total))
        samples.append(item)
        if dimension == 1:
            break
        pivot = int(np.argmax(np.abs(basis[item])))
        if abs(basis[item, pivot]) < np.finfo(float).eps:
            raise OperationError("unstable_projection")
        other = [column for column in range(dimension) if column != pivot]
        reduced = basis[:, other] - np.outer(
            basis[:, pivot] / basis[item, pivot],
            basis[item, other],
        )
        reduced[samples, :] = 0
        try:
            basis, _ = np.linalg.qr(reduced, mode="reduced")
        except np.linalg.LinAlgError:
            raise OperationError("unstable_projection") from None
    return samples
