# 对象快照保留演练台

数据湖值班工程师可在工作台上传来源 CSV，对照规则判断差异，签发合格批次或记录暂缓意见。

基于活动快照、保留期和合法保全计算可回收对象。

## 启动

```sh
docker compose up --build -d --wait
```

打开 <http://localhost:18311>。页面预览带异常样例。选中阶段查看计算证据；回收演练面板展示将释放容量、留存对象及依据，并给出“先释放”“等齐后整批”“整批签发”三个执行选择。执行批次后可提交复核意见。

## 核验

```sh
docker compose exec -T app pytest -q
```

[输入字段](docs/DATA-DICTIONARY.md) · [阶段接口](docs/HTTP.md) · [操作步骤](docs/OPERATIONS.md) · [规则与测试](docs/DEPTH.md)
