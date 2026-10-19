# 陕西企业政策监测（西安优先）

每日采集陕西省和西安市官方企业政策，生成可检索日报，通过现有企业微信机器人推送。范围包括项目申报、数字化改造、补贴奖补、科技创新、绿色制造、产业扶持和涉企税收政策。排除日常采购招标、人事任免与机构备案公告。

- [最新日报](https://business-unit-for-enterprise-service.github.io/shaanxi-policy-monitor/)
- [采集来源](config/sources.json)：8 个启用栏目，来自西安市工信局、科技局及陕西省工信厅、科技厅、发改委、财政厅、省政府。西安市发改委、财政局暂因 HTTPS 核验问题列为待接入。
- 每天北京时间 **08:35** 启动采集，**09:05** 由 BidScout 发送政策日报；10:05、11:05 检查漏发并补发。GitHub 定时任务可能延迟，时间为计划时间。
- 推送使用 `Business-Unit-for-BidScout/crawler` 的独立 `policy-daily.yml` 工作流，并且必须与 `Business-Unit-for-Energy-Saving/industry-monitor` 使用同一个企业微信机器人。本项目不复制或存储机器人凭据；需要将 BidScout 仓库的 `WECOM_WEBHOOK_URL` 配置为节能项目所使用的同一 Webhook，GitHub 不会自动同步两个仓库的 Secret。与招采日报使用独立发送记录，每个机器人每个报告日期最多确认发送一次。

## 报告口径

报告是当天采集时点的政策快照。新收录按首次发现时间统计，原文发布日期单独显示。每个来源首次扫描及其未完成队列属于“首次建档”，不伪装成今日发布的新政策。当天重跑保留当天发现事件。更新按原文标题、正文和附件链接的哈希判断，不保存正文。

企业申报截止、项目完成日期、主管部门推荐、补正、公示日期分别提取。只将明确的企业申报截止用于到期提醒；缺少年份时标明按发布日期推定，跨年歧义、多个截止或附件中的日期保留为待核实。日期未到不意味着正在受理，也不意味着满足申报条件。用户给出的第四批数字化改造申报通知为固定种子：企业截止 2026-09-25，补正截止 2026-10-08，首次日报时已过期。

仅检查已配置栏目首页，每个来源每次最多 12 篇文章，持久化待处理队列；新文章优先，旧文章轮换复查（脱离首页的已收录文章至少每 7 天进入复查队列，实际复查取决于预算和可访问性）。不承诺全省全量历史回溯。栏目或正文结构变化、403/429、TLS 和 robots 限制明确呈现在覆盖表，不当作“无新增”。整站失败仍发布包含失败说明的日报，沿用已有记录并展示最近核对时间。

## 运行

```sh
python -m venv .venv
# Activate the environment for your platform, then:
python -m pip install -e '.[test]'
pytest -q
python -m shaanxi_policy --state data/state.json --output site
```

GitHub Actions 在 `main` 执行代码，`policy-data` 保存 `state.json` 和 `site/` 的日报归档；GitHub Pages 使用 Actions 部署。初次安装需创建包含空状态的 `policy-data` 分支，然后在 Settings → Pages 选择 GitHub Actions。手动运行 `Collect Shaanxi policies and publish daily report` 可重试采集/发布；确认当天页面可用后，可手动运行 BidScout 的政策日报推送工作流。

## 采集边界

使用固定提交版本的 `industry-monitor-core` 安全 HTTP 客户端：验证 TLS、遵守 robots、限定官方域名、每主机请求至少间隔 2 秒、限制超时和响应大小、不绕过验证码或拦截。HTML 只在内存中解析；包括 `noarchive` 页面在内，均不保存原始 HTML 或全文。公开产物仅含标题、来源、短摘录、日期依据和原文/附件链接；遇到 `nosnippet` 不输出摘录，`noindex` 不收录。附件只链接，不自动下载。关键词和规则提取存在遗漏，企业应核对原文及最新延期通知。
