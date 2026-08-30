"""Pydantic schemas for FastAPI request/response."""
from __future__ import annotations

from typing import Any, List, Optional, Dict
from pydantic import BaseModel, Field


# =============== Predict (训练/预测) ===============
class PredictParams(BaseModel):
    framework: str = Field("pytorch", pattern="^(pytorch|tensorflow)$")
    stock_code: str = "sh.600036"
    start_date: str = "2018-01-01"
    end_date: str = ""
    adjustflag: str = "2"            # 1=后复权 2=前复权 3=不复权
    frequency: str = "d"             # d/w/m/5/15/30/60
    feature_cols: str = "open,high,low,close,volume,amount,turn"
    target_col: str = "close"
    seq_len: int = 60
    train_ratio: float = 0.8

    model_type: str = Field("LSTM", pattern="^(LSTM|GRU|Transformer)$")
    hidden_size: int = 128
    num_layers: int = 2
    dropout: float = 0.2
    bidirectional: bool = False
    d_model: int = 128
    nhead: int = 4
    dim_feedforward: int = 256

    epochs: int = 80
    batch_size: int = 32
    learning_rate: float = 1e-3
    optimizer_type: str = Field("Adam", pattern="^(Adam|SGD|AdamW)$")
    loss_type: str = Field("MSE", pattern="^(MSE|MAE|Huber)$")
    early_stopping_patience: int = 15
    model_name: Optional[str] = None   # 保存名；空 = 自动生成


class TrainProgress(BaseModel):
    task_id: str
    stage: str                    # data/build/train/done/error
    epoch: int = 0
    total_epochs: int = 0
    train_loss: Optional[float] = None
    val_loss: Optional[float] = None
    message: str = ""


class TrainResult(BaseModel):
    task_id: str
    status: str                   # success/error
    save_path: Optional[str] = None
    train_losses: List[float] = []
    val_losses: List[float] = []
    metrics: Dict[str, Any] = {}
    actual: List[float] = []      # 测试集实际值（可视化用）
    predicted: List[float] = []   # 测试集预测值
    dates: List[str] = []
    error: Optional[str] = None


# =============== ST 摘帽 ===============
class STScanParams(BaseModel):
    months_back: int = 10
    before_days: int = 30
    after_days: int = 30


class GenericScanParams(BaseModel):
    months_back: int = 24


# =============== 板块热度 / 热门股票 ===============
class MarketDateParams(BaseModel):
    trade_date: str = ""   # YYYYMMDD 或 空=最近交易日
    use_cache: bool = True


class HotStocksParams(MarketDateParams):
    sort_by: str = Field("pct_chg", pattern="^(pct_chg|amount|vol)$")
    top_n: int = 50
    filter_keyword: str = ""


# =============== 自选股 ===============
class FavoriteEvent(BaseModel):
    title: str
    due_date: str                 # YYYY-MM-DD


class FavoriteStock(BaseModel):
    id: Optional[int] = None
    code: str
    name: str
    buy_date: str = ""
    buy_price: Optional[float] = None
    current_price: Optional[float] = None
    note: str = ""
    events: List[FavoriteEvent] = []


# =============== 可转债 ===============
class CBondParams(BaseModel):
    category: str = Field("subscribe", pattern="^(subscribe|listing|review)$")


# =============== 要约收购 ===============
class TenderParams(BaseModel):
    market: str = Field("cn", pattern="^(cn|hk)$")


# =============== 通用响应 ===============
class DataResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: Any = None
    cache_hit: bool = False
