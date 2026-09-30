"""Train the LSTM autoencoder with JAX.

The forward pass is `models.lstm_ae_forward`, the same function the Lambda runs with
NumPy. Only the gradient computation needs JAX, so there is no weight conversion step.
"""
from __future__ import annotations

import jax
import jax.numpy as jnp
import numpy as np

from .models import lstm_ae_forward


def init_params(n: int, hidden: int, latent: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)

    def glorot(shape):
        lim = np.sqrt(6.0 / (shape[0] + shape[1]))
        return rng.uniform(-lim, lim, shape)

    def gate_bias():
        b = np.zeros(4 * hidden)
        b[hidden:2 * hidden] = 1.0            # forget-gate bias 1 helps early training
        return b

    return {
        "enc_wx": glorot((n, 4 * hidden)), "enc_wh": glorot((hidden, 4 * hidden)), "enc_b": gate_bias(),
        "lat_w": glorot((hidden, latent)), "lat_b": np.zeros(latent),
        "dec_wx": glorot((latent, 4 * hidden)), "dec_wh": glorot((hidden, 4 * hidden)), "dec_b": gate_bias(),
        "out_w": glorot((hidden, n)), "out_b": np.zeros(n),
    }


def train_autoencoder(x: np.ndarray, *, hidden: int = 16, latent: int = 4, epochs: int = 15,
                      batch: int = 256, lr: float = 3e-3, seed: int = 0,
                      x_val: np.ndarray | None = None, log=print) -> tuple[dict, list]:
    """x: standardised windows (N, T, n). Returns NumPy parameters and the loss history."""
    params = {k: jnp.asarray(v, dtype=jnp.float32) for k, v in init_params(x.shape[2], hidden, latent, seed).items()}

    def loss_fn(p, xb):
        return jnp.mean((lstm_ae_forward(p, xb, jnp) - xb) ** 2)

    b1, b2, eps = 0.9, 0.999, 1e-8

    @jax.jit
    def step(p, m, v, t, xb):
        loss, grads = jax.value_and_grad(loss_fn)(p, xb)
        m = jax.tree_util.tree_map(lambda a, g: b1 * a + (1 - b1) * g, m, grads)
        v = jax.tree_util.tree_map(lambda a, g: b2 * a + (1 - b2) * g * g, v, grads)
        mhat = jax.tree_util.tree_map(lambda a: a / (1 - b1 ** t), m)
        vhat = jax.tree_util.tree_map(lambda a: a / (1 - b2 ** t), v)
        p = jax.tree_util.tree_map(lambda w, a, c: w - lr * a / (jnp.sqrt(c) + eps), p, mhat, vhat)
        return p, m, v, loss

    val_loss = jax.jit(loss_fn)
    m = jax.tree_util.tree_map(jnp.zeros_like, params)
    v = jax.tree_util.tree_map(jnp.zeros_like, params)
    rng = np.random.default_rng(seed)
    x = x.astype(np.float32)
    history, t = [], 0
    for epoch in range(epochs):
        order = rng.permutation(len(x))
        losses = []
        for start in range(0, len(x) - batch + 1, batch):
            t += 1
            params, m, v, loss = step(params, m, v, t, x[order[start:start + batch]])
            losses.append(float(loss))
        entry = {"epoch": epoch + 1, "train_loss": float(np.mean(losses))}
        if x_val is not None:
            entry["val_loss"] = float(val_loss(params, x_val[:5000].astype(np.float32)))
        history.append(entry)
        log(f"      epoch {entry['epoch']:2d}  train {entry['train_loss']:.4f}"
            + (f"  val {entry['val_loss']:.4f}" if "val_loss" in entry else ""))
    return {k: np.asarray(v, dtype=np.float64) for k, v in params.items()}, history
