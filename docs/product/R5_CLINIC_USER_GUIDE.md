# 本地玄医馆使用指南

默认命令继续使用离线 Fake Mentor，页面与 R5 保持一致。R6-P2b 新增的 `off/fake/deepseek` 显式模式、五类真实表达和付费门禁见 [R6 真实导师医馆离线装配]RR6_REAL_MENTOR_CLINIC_INTEGRATION.md)；真实 DeepSeek 医馆本轮未运行。

先创建存档目录，然后启动：

```powershell
New-Item -ItemType Directory -Force .\runtime_data\clinic
.\.venv\Scripts\xuanyi-clinic.exe --state-dir .\runtime_data\clinic
```

打开命令输出的 `http://127.0.0.1:<自动端口>` 地址，创建或恢复弟子；之后可从导航进入导师教学、病例、考试、传承和师评。界面只显示自然语言选项。关闭浏览器或按 `Ctrl+C` 停止服务器不会丢失最后一次成功行动；再次使用同一目录即可恢复。

推荐路线是完成旧纸伞、灰灶、月井，参加六题规则考试；条件不足时完成页面显示的固定补课，再申请“溯契还因”，随后完成双灯巷、雾渡客船与归契古祠。归契古祠没有传承时也可满分完成。

这是仅供本机单人游玩的架空产品，不构成现实医疗建议，也不提供公网账户或远程部署。
