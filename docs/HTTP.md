# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`balance` 阶段起报告包含 `release` 演练：`capacity`（将释放字节、对象数和分组）、`reclaimable`（可回收对象及依据）、`retained`（留存对象、原因和依据）、`quarantined`（按源行号隔离的行）、`reconciliation`（源行、保留行、可回收行、隔离行等对账）、`options`（`PARTIAL`、`HELD`、`APPROVED` 的可用性和阻挡项）以及 `needs_choice`。演练只给结论，不删除对象。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。同一来源内容重跑返回原批次（含已签发结论），不会新增演练。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED`（整批签发）、`PARTIAL`（先释放已确认安全的对象）或 `HELD`（等齐或暂缓）。`APPROVED` 和 `PARTIAL` 只能选择当次演练标为可用的选项，且任一核对不一致时都会被挡住。冲突返回 409，客户端读取新版本后重试。签发和先释放都是终态，失败时原批次和旧版依据原样保留。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据、回收演练和复核信息的 JSON。
