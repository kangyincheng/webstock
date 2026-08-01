"""TensorFlow Keras 版本的股票预测模型（LSTM/GRU/Transformer）。

对应 PyTorch 版 model.py 的 StockLSTM/StockGRU/StockTransformer 与 build_model。
"""


def _import_tf():
    """延迟导入 TensorFlow，未安装时给出明确错误。"""
    try:
        import tensorflow as tf  # noqa: F401
        return tf
    except ImportError:
        raise ImportError(
            "未安装 tensorflow，请先执行：pip install tensorflow>=2.10.0")


def build_model(model_type, input_size, seq_len=60, **kwargs):
    """构建 Keras Functional 模型。

    Args:
        model_type: "LSTM" | "GRU" | "Transformer"
        input_size: int，特征维度（feature_cols 数量）
        seq_len: int，时间窗口长度
        **kwargs: hidden_size/num_layers/dropout/bidirectional
                  d_model/nhead/num_layers/dim_feedforward/dropout

    Returns:
        keras.Model，输入 shape (None, seq_len, input_size)，输出 shape (None, 1)
    """
    tf = _import_tf()
    from tensorflow import keras
    from tensorflow.keras import layers

    hidden_size = int(kwargs.get("hidden_size", 128))
    num_layers = int(kwargs.get("num_layers", 2))
    dropout = float(kwargs.get("dropout", 0.2))
    bidirectional = bool(kwargs.get("bidirectional", False))
    d_model = int(kwargs.get("d_model", kwargs.get("hidden_size", 128)))
    nhead = int(kwargs.get("nhead", 4))
    dim_feedforward = int(kwargs.get("dim_feedforward", 256))

    inputs = keras.Input(shape=(seq_len, input_size))

    if model_type in ("LSTM", "GRU"):
        rnn_cls = layers.LSTM if model_type == "LSTM" else layers.GRU
        x = inputs
        for i in range(num_layers):
            return_sequences = (i < num_layers - 1)
            layer = rnn_cls(
                units=hidden_size,
                return_sequences=return_sequences,
                dropout=(dropout if num_layers > 1 else 0.0),
                recurrent_dropout=0.0,
                kernel_initializer="glorot_uniform",
            )
            if bidirectional:
                layer = layers.Bidirectional(layer)
            x = layer(x)
        if num_layers == 0:
            # Fallback: 展平 + 全连接
            x = layers.Flatten()(inputs)
        else:
            x = layers.Dropout(dropout)(x)
        x = layers.Dense(hidden_size // 2, activation="relu")(x)
        x = layers.Dropout(dropout)(x)
        outputs = layers.Dense(1)(x)

    elif model_type == "Transformer":
        # 1) 输入投影到 d_model
        x = layers.Dense(d_model)(inputs)  # (B, seq_len, d_model)
        # 2) 位置编码（固定正弦/余弦，与 PyTorch 版对齐）
        x = x + _positional_encoding(seq_len, d_model)
        x = layers.Dropout(dropout)(x)
        # 3) MultiHeadAttention 堆叠
        for _ in range(num_layers):
            x = _transformer_block(x, d_model, nhead, dim_feedforward, dropout)
        # 4) 取最后时间步
        x = layers.Lambda(lambda t: t[:, -1, :])(x)
        x = layers.Dropout(dropout)(x)
        x = layers.Dense(d_model // 2, activation="relu")(x)
        x = layers.Dropout(dropout)(x)
        outputs = layers.Dense(1)(x)

    else:
        raise ValueError(f"未知模型类型: {model_type}")

    return keras.Model(inputs=inputs, outputs=outputs)


# ---------------- 辅助函数 ----------------

def _positional_encoding(seq_len, d_model):
    """固定正弦/余弦位置编码（返回 constant tensor shape (1, seq_len, d_model)）。"""
    import numpy as np
    tf = _import_tf()
    position = np.arange(seq_len)[:, None]  # (seq_len, 1)
    div_term = np.exp(
        np.arange(0, d_model, 2) * (-np.log(10000.0) / d_model)
    )  # (d_model//2,)
    pe = np.zeros((1, seq_len, d_model), dtype=np.float32)
    pe[0, :, 0::2] = np.sin(position * div_term)
    if d_model % 2 == 0:
        pe[0, :, 1::2] = np.cos(position * div_term)
    else:
        pe[0, :, 1::2] = np.cos(position * div_term)[:, :-1]
    return tf.constant(pe)


def _transformer_block(x, d_model, nhead, dim_feedforward, dropout):
    """单层 Transformer Encoder Block（Pre-Norm，与主流实现一致）。"""
    tf = _import_tf()
    from tensorflow.keras import layers

    # 用合适的 key_dim：确保 d_model 能被 nhead 整除
    key_dim = max(1, d_model // nhead)
    attn = layers.MultiHeadAttention(
        num_heads=nhead, key_dim=key_dim, dropout=dropout)
    ln1 = layers.LayerNormalization(epsilon=1e-6)
    ln2 = layers.LayerNormalization(epsilon=1e-6)

    x_norm = ln1(x)
    a, _ = attn(x_norm, x_norm, return_attention_scores=True)
    a = layers.Dropout(dropout)(a)
    x = layers.Add()([x, a])

    x_norm = ln2(x)
    ff = layers.Dense(dim_feedforward, activation="relu")(x_norm)
    ff = layers.Dropout(dropout)(ff)
    ff = layers.Dense(d_model)(ff)
    ff = layers.Dropout(dropout)(ff)
    x = layers.Add()([x, ff])
    return x
