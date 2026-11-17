# Shadowrocket：常用服务直连，其他域名代理

本仓库为固定的本地分流配置生成两份可自动更新的远程列表。没有代理节点、账号、密钥或机场订阅。

| 请求 | 策略 |
| --- | --- |
| 局域网及本地 IPv4 / IPv6 | DIRECT |
| 命中广告列表的域名 | REJECT |
| 已审核的国内常用服务域名 | DIRECT |
| 其他域名，包括国内小众网站 | PROXY |
| 仅能识别为 IP 的中国公网请求 | DIRECT |
| 其他公网 IP | PROXY |

DIRECT 使用当前网络的出口。PROXY 使用 Shadowrocket 当前选中的国外节点。分类依据是客户端能识别到的域名或 IP。

## 安装与自动更新

1. 下载 [本地配置文件](https://raw.githubusercontent.com/aiStone-pro/shadowrocket-rules/main/profiles/sr_cn_popular_direct_others_proxy_auto.conf)，通过文件导入 Shadowrocket，启用它，全局路由选择“配置”。
2. 点击“编译配置”或“使用配置”，在“规则集 URL”页面确认 `ads.list` 和 `direct.list` 均下载成功。
3. 在 Shadowrocket 的“设置 → 配置”中开启“自动后台更新”，更新间隔可设为 1 天。设备版本不同，入口名称可能略有差异。
4. 在系统设置中允许 Shadowrocket 后台 App 刷新。iOS 调度不保证准点执行，强制结束 App 也会影响后台更新。

本地配置不含 `update-url`。请保留这一点：自动刷新只更新两份规则集，不替换主配置。不要把旧版 h2y 配置的更新地址加回来。节点订阅和 GeoIP 数据库是独立的更新设置。

刷新机制参考：[Shadowrocket 使用手册：自动更新](https://github.com/LOWERTOP/Shadowrocket#自动更新)。

## 更新的两层流程

- GitHub Actions 每天约 04:17（Asia/Tokyo）抓取上游、筛选、验证，并发布规则。GitHub 的定时任务可能延迟；公开仓库长期没有活动时，GitHub 也可能暂停定时工作流，可在 Actions 中恢复或手动运行。
- Shadowrocket 按设备上的后台更新设置重新下载本仓库发布的两个列表。

资源地址：

- [广告列表](https://raw.githubusercontent.com/aiStone-pro/shadowrocket-rules/main/rules/ads.list)
- [直连列表](https://raw.githubusercontent.com/aiStone-pro/shadowrocket-rules/main/rules/direct.list)
- [最近成功构建的时间、数量和来源摘要](rules/status.json)
- [更新任务](https://github.com/aiStone-pro/shadowrocket-rules/actions/workflows/update.yml)

## 筛选边界

`policy/approved-direct.json` 保存现有 219 条已审核的域名范围。脚本读取服务列表，仅接受 `DOMAIN` / `DOMAIN-SUFFIX` 条件，生成其与已审核范围的交集。

例如，上游新增 `another-company.cn`、`aliyuncs.com`、`myqcloud.com` 或宽泛的 `.cn`，不会让这些范围自动直连。即使上游出现比已审核范围更宽的后缀，输出也只能收窄到已审核范围。新增根域名或第三方 CDN 接口需要先审核并修改本地策略文件，不会仅凭服务名称或关键词自动放行。

这意味着“自动更新”不等于“自动扩大直连白名单”。名单范围内的上游变动可自动同步；范围外的新服务/新资源仍走代理。农行三个已核实的域名作为显式固定例外保留，来源记录在策略文件中。

主配置、已审核范围、验证脚本不会被每日更新任务修改。失败的下载、异常格式、关键服务丢失、越界匹配或广告误拦回归样例都会使任务失败，保留最后一次成功发布的规则。首次导入仍需要成功下载两份列表；不能将尚未下载到规则的状态视为安装完成。

## 本地维护

需要 Python 3.10 或更新版本，无第三方 Python 依赖。

```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/update_rules.py
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

每次修改审核范围都应检查完整的规则差异和回归结果。原有 5,720 条静态广告规则已由持续维护的 anti-AD 域名列表替代；没有将旧广告规则永久叠加，以便上游删除或修正的规则能生效。

## 来源与许可证

- 常用服务域名参考 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)，遵循 GPL-2.0。完整来源 URL 及抓取内容的 SHA-256 在 `rules/status.json` 中。
- 广告来源为 [privacy-protection-tools/anti-AD](https://github.com/privacy-protection-tools/anti-AD)，MIT 许可原文保存在 `LICENSES/anti-AD-MIT.txt`。
- 本仓库生成脚本、配置及经筛选的直连规则使用 GPL-2.0-only，见 `LICENSE`。广告数据保留上游 MIT 许可。
