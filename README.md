# mystock - A股收盘价预测系统

基于 PyTorch + Baostock + Tkinter 的 A 股个股收盘价预测分析工具。

## 功能特点

- **数据获取**：通过 Baostock 获取 A 股历史行情数据，支持多种复权方式和频率
- **模型选择**：支持 LSTM、GRU、Transformer 三种模型架构
- **可调参数**：所有关键参数均可在界面中调整
- **实时进度**：训练过程实时显示损失变化和进度条
- **图表展示**：Matplotlib 绘制预测值与实际值对比图
- **模型持久化**：模型可保存和加载，下次直接调用

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

## 可调参数

### 数据参数
- 股票代码（如 sh.600036, sz.000001）
- 起始/结束日期
- 复权方式（不复权/前复权/后复权）
- 数据频率（日K/周K/月K/分钟线）
- 特征列（逗号分隔，如 open,high,low,close,volume,amount,turn）
- 目标列（默认 close）
- 序列长度（时间窗口大小）
- 训练集比例

### 模型参数
- 模型类型：LSTM / GRU / Transformer
- 隐藏层大小
- 网络层数
- Dropout
- 双向（LSTM/GRU）
- Transformer 头数
- 前馈维度

### 训练参数
- 训练轮数
- 批次大小
- 学习率
- 优化器：Adam / SGD / AdamW
- 损失函数：MSE / MAE / Huber
- 早停耐心值

## 项目结构

```
mystock/
├── main.py           # 入口文件
├── requirements.txt  # 依赖列表
├── data/             # 数据缓存
├── models/           # 模型保存
└── src/
    ├── __init__.py
    ├── data_loader.py  # 数据加载与预处理
    ├── model.py        # PyTorch 模型定义
    ├── trainer.py      # 训练与预测
    └── gui.py          # Tkinter 图形界面
```
