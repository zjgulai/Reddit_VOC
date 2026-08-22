     Reddit内容洞察飞书多维表自动化工作流分享 \* { margin: 0; padding: 0; outline: 0; } body { font-family: "PingFang SC", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif; line-height: 1.6; } .\_\_page\_content\_\_ { max-width: 667px; margin: 0 auto; padding: 20px; text-size-adjust: 100%; color: rgba(0, 0, 0, 0.9); padding-bottom: 64px; } .title { user-select: text; font-size: 22px; line-height: 1.4; margin-bottom: 14px; font-weight: 500; } .\_\_meta\_\_ { color: rgba(0, 0, 0, 0.3); font-size: 15px; line-height: 20px; hyphens: auto; word-break: break-word; margin-bottom: 50px; } .\_\_meta\_\_ .nick\_name { color: #576B95; } .\_\_meta\_\_ .copyright { color: rgba(0, 0, 0, 0.3); background-color: rgba(0, 0, 0, 0.05); padding: 0 4px; margin: 0 10px 10px 0; } blockquote.source { padding: 10px; margin: 30px 0; border-left: 5px solid #ccc; color: #333; font-style: italic; word-wrap: break-word; } blockquote.source a { cursor: pointer; text-decoration: underline; } .item\_show\_type\_0 > section { margin-top: 0; margin-bottom: 24px; } a { color: #576B95; text-decoration: none; cursor: default; } .text\_content { margin-bottom: 50px; user-select: text; font-size: 17px; white-space: pre-wrap; word-wrap: break-word; line-height: 28px; hyphens: auto; } .picture\_content .picture\_item { margin-bottom: 30px; } .picture\_content .picture\_item .picture\_item\_label { text-align: center; } img { max-width: 100%; } .pay\_subscribe\_notice { margin: 30px 0; padding: 20px; background: #fffbe6; border: 1px solid #ffe58f; border-radius: 8px; } .pay\_subscribe\_badge { display: inline-block; padding: 4px 12px; background: #faad14; color: #fff; border-radius: 4px; font-size: 14px; font-weight: 500; margin-bottom: 12px; } .pay\_subscribe\_desc { font-size: 15px; line-height: 1.8; color: rgba(0, 0, 0, 0.7); margin-bottom: 12px; } .pay\_subscribe\_hint { font-size: 13px; color: rgba(0, 0, 0, 0.4); } .\_\_bottom-bar\_\_ { display: flex; justify-content: space-between; align-items: center; position: fixed; bottom: 0; left: 0; right: 0; height: 64px; padding: 8px 20px; background: white; box-sizing: border-box; border-top: 1px solid rgba(0, 0, 0, 0.2); } .\_\_bottom-bar\_\_ .left { display: flex; align-items: center; font-size: 15px; white-space: nowrap; } .\_\_bottom-bar\_\_ .right { display: flex; } .\_\_bottom-bar\_\_ .sns\_opr\_btn { display: flex; align-items: center; user-select: none; background: transparent; border: 0; color: rgba(0, 0, 0, 0.9); font-size: 14px; } .\_\_bottom-bar\_\_ .sns\_opr\_btn:not(:last-child) { margin-right: 16px; } .\_\_bottom-bar\_\_ .sns\_opr\_btn > img { margin-right: 4px; }

Reddit内容洞察飞书多维表自动化工作流分享
=======================

原创 Lisa Lisa的AI生活流 2026-06-17 12:00 广东

> 原文地址: [https://mp.weixin.qq.com/s/pqqNefmXDP2tGSxeHYHWUw](https://mp.weixin.qq.com/s/pqqNefmXDP2tGSxeHYHWUw)

**Lisa的AI生活流**

**记录AI时代的表达日常**

  

  

用飞书多维表，把 Reddit 原话变成内容洞察看板
==========================

最近用飞书多维表做了一套 Reddit 的内容洞察系统，能很直观地得到用户需求的细分。

把公开讨论先变成一张原始数据表，再用飞书多维表做内容洞察，最后沉淀成一个可以持续看的仪表盘。

这篇我用一个小案例讲完整流程：收集 DIY 无人机相关 subreddit **r/diydrones** 的少量原始数据，包括帖子正文、评论正文、总评论数和点赞数，然后直接放进飞书多维表里分析。

整条链路很简单：

Reddit 原话采集 → 飞书多维表沉淀 → lark-CLI 生成洞察表 → 仪表盘跟踪需求

第一步，先收集原始讨论
-----------

最稳的方式是申请 Reddit API，然后按 subreddit、关键词、时间范围去拉数据。

这个阶段不用一上来采几万条，根据自己的数据量需求，拿近期时间段的帖子和评论做小样本就够了。

我会保留这些字段：

字段

用途

帖子标题

判断用户提出的问题

帖子内容

看完整场景

评论内容

找真实经验和反驳

总评论数

判断讨论热度

点赞数

判断社区共鸣

发布时间

看问题是否还新

最近更新时间

看讨论是否还在延续

来源社区

后面做社区对比

比如 DIY 无人机场景里，用户可能会讨论飞控调参、电池续航、零件兼容、入门套件、法规限制、炸机维修、图传延迟。

这些词本身不是洞察。真正有用的是：新手为什么卡住，老手为什么不满，哪些问题反复出现但没有好答案。

![](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibxWOAhsHoqnrHN2LKgibsqjnEwWeJsC0DljDnotxNBnjzd26CcTGHluic4U218YyrrUHRJuuKfBm4wNO8fKEhWFslZ0gwHJk625U/640?wx_fmt=png&from=appmsg)

第二步，用飞书 CLI 生成内容洞察表
-------------------

原始表只是素材池。

我真正想看的，是每条讨论背后反映了什么需求。

所以我会用飞书 CLI 读取原始表，再把帖子和评论交给模型分析，生成一张“内容洞察表”。这张表的字段可以这样设计：

字段

说明

洞察标题

一句话概括需求

需求类型

入门、选型、故障、成本、安全、法规等

用户场景

用户在什么情况下遇到问题

痛点描述

具体卡点

用户原话摘要

保留原始表达的味道

来源社区

来自哪个 subreddit

典型情绪

焦虑、困惑、挫败、兴奋、怀疑

需求强度

低、中、高

洞察状态

待确认、已验证、可转内容、可转产品

另外还可以统计这些证据字段：

相关帖子数、相关评论数、总投票数、总评论数、负面评论数、帖子发表时间、最近更新时间。

最后再加几个计算维度：

证据数 / 讨论强度 / 痛点强度 / 需求热度

这里的重点不是让 AI 替你下结论，而是让它先把散乱的原话整理成可以复盘的结构。

如果是在网页端，则直接使用飞书多维表“通过AI创建即可”

![](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibyzWCMpia7JbeaB6yCTEVOHxkuHpEPj6HyEehqCNicnNrHZwk3uxlBgicNanERibgsOv8WxlibXBfdqay45LOdPwvt48JCokctbwgLQ/640?wx_fmt=png&from=appmsg)

我会给模型类似这样的 prompt：

    你是内容洞察分析师。请基于 Reddit 原始帖子和评论，提炼用户需求。 

跑完以后，你看到的就不是一堆帖子了，而是一张需求地图。

![飞书文档 - 图片](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibyhIcZCbUNlgC6yd1HYUicl82C2NsDFzfCnAN9j91naxdEowK0Gcqr4ftuODI08Pg5YtnjkSArh6oNvibdJAwWegWWqDEvTrWDX4/640?wx_fmt=png&from=appmsg)

比如原始评论里有很多人说“新手不知道该买哪种飞控”“教程太碎”“炸机后不知道怎么排查”，洞察表里就可能合并成一条：

> 新手缺少从选件到首飞的完整排错路径。

这条洞察后面可以变成文章、视频、清单、模板，甚至是一套入门产品包。

第三步，把洞察表变成仪表盘
-------------

内容洞察如果只停留在表格里，还是不够直观。

我会在飞书多维表里给它做一个四层仪表盘。

![飞书文档 - 图片](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibw2rrdXWUJ1ZgDN3pAbRW2UrtAkIaXZC846Swxcp8dZ9Jv58EaZWBm9CfoWFccdQgRuh7pqDw4lRxsjwLibc6FJPPeacmt4bZrc/640?wx_fmt=png&from=appmsg)

### 第一层：总览

*   洞察总数
    
*   高强度需求数
    
*   待确认洞察数
    
*   总证据数
    

这一层回答：现在我们到底发现了多少需求，哪些值得先看。

### 第二层：用户需求地图

*   需求类型分布
    
*   需求热度排行
    
*   需求类型 → 典型情绪 → 需求强度 
    

这一层回答：社区里的需求主要集中在哪里，哪些情绪正在推动讨论。

![](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibyfcOu3VjXoOvKpwYnKhnNaTw8jSCqkeChDlVcmNq9NDiaGbcerDAtNj4SficLzDYyOmNxGUh44kwHtG0T4gAApLZjSbiaDQgjvdw/640?wx_fmt=png&from=appmsg)

### 第三层：痛点与机会

*   痛点强度排行
    
*   需求热度 × 痛点强度散点图
    
*   高热高痛需求列表
    

这一层最适合做选题和产品机会判断。高热高痛的需求，通常不只是“有人聊”，而是“很多人反复卡在这里”。

![](https://mmbiz.qpic.cn/mmbiz_png/DkXl1OHLLibzLotp5icgv6icdgpKuTBRqGxxO5ZDTibMAz06hCoKiahzv2PfTO8OyPnjgPZW6R3ic08gRRAXveleUdzFfZj6m3ZLBA1YAX61yTMFY/640?wx_fmt=png&from=appmsg)

痛点强度=负面评论/总评论数

![](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibzhPiafrR5ic4aNj82R6D6muYEia7ckYKJ4JJ5lBuXAwyAwxEZRLTJ86VvVeyElu24CSrEp2ViaSndEv7Sx4IDR2Zicnk5ia8Og5Wia1E/640?wx_fmt=png&from=appmsg)

需求热度=\[相关帖子数\]\*2+\[相关评论数\]\*1.5+\[负面评论数\]\*3+\[总投票数\]\*0.2

### 第四层：证据可信度

*   证据数排行
    
*   证据类型分布：帖子为主、评论为主、均衡
    
*   低证据高热度需求列表
    

这一层用来防止自己被少数高情绪样本带偏。

![](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibyxicZnA5jclETGwrLmbunZsdI5Cn5dl0dgzzIQeLTYdYBuGeENXnJ3E3COfRC4I0rKMTqFvDxOlGZ6pOZDabPiaayu2utXDu21Q/640?wx_fmt=png&from=appmsg)

如果一条需求热度很高，但证据数很低，我会先把它标成“待确认”，继续收集更多帖子和评论，而不是马上拿去做判断。

最后可以让表格自己总结
-----------

飞书多维表还有一个很实用的点：智能总结。

![](https://mmbiz.qpic.cn/mmbiz_gif/DkXl1OHLLibzAVUXdiceNOQuAWWKTmYJ3n0dBtAMSXFyHUj5g7asm5D54g5HO8eAYQz2DJZP0YnnIJ5ZCzcgoLOSRqdqqr17NA96duibX9yKUw/640?wx_fmt=gif&from=appmsg)

当内容洞察表跑起来之后，可以直接让它总结最近一批 Reddit 数据里最常见的需求、最强的痛点、最值得追踪的主题。

这套方法不复杂，但它解决了一个很具体的问题：

我们不再靠刷 Reddit 的感觉做判断，而是把用户原话、互动数据、情绪、痛点和证据数量放到同一张表里。

对于内容团队来说，它可以变成选题库。

对于产品团队来说，它可以变成需求池。

对于创业者来说，它可以变成一个小型市场雷达。

如果你想试，不用一开始做大系统。

先找一个或几个你熟悉的 subreddit，获取原贴和评论数据，放进飞书多维表，跑出第一版内容洞察。

看到第一张“高热高痛需求列表”的时候，你就会知道：Reddit 里真正有价值的，不是热闹本身，而是热闹背后那些反复出现的具体问题。

飞书多维表新注册优惠
----------

最后，我也跟飞书官方争取到了新注册优惠，通过以下邀请码新注册，可直接获得**全网专属、价值百元的飞书多维表格 3 个月专业版免费使用**，享受 2 万行单表大数据容量、获得每月 5 万次自动化流程、实现跨表无缝联动。

飞书多维表官网：https://www.feishu.cn/product/base

邀请码：Code2z4tYku9Ru

公众号后台回复“**飞书**”，可以直接联系到飞书官方客服，了解更多飞书优惠以及飞书多维表的相关教程。

![飞书文档 - 图片](https://mmbiz.qpic.cn/mmbiz_png/DkXl1OHLLibzODKZNlJ0VIibca2tV4xC7Qhib0k7Cgj196YU7Y4NNNAkLdlpZYPZGNrplP0r3xcQpUn6amtBG9aogOOia8HibGl5LDibiaQqN02O2w/640?wx_fmt=png&from=appmsg)

别客气，点个关注

咱们一起折腾 AI！(๑˃̵ᴗ˂̵)و

  

  

往期回顾：

[Reddit提问型内容为什么容易获得评论](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484811&idx=1&sn=feb87ead91c80a0570884f130d39efb5&scene=21#wechat_redirect)

[Reddit 故事型内容如何降低营销感？](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484806&idx=1&sn=83008b536e12c15555242eada35a9c3b&scene=21#wechat_redirect)

[Reddit 标题怎么写，才更容易被点开？](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484800&idx=1&sn=2246fb5074b7b248b09ce5e9e2962460&scene=21#wechat_redirect)

[如何建立品牌监听型Subreddit清单](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484795&idx=1&sn=0e6d59a0a474b03927deace11c7e21a5&scene=21#wechat_redirect)

[经验分享型内容怎么写才真实？](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484790&idx=1&sn=450d7de7455f7358bbe661a9506bff5c&scene=21#wechat_redirect)

  

![](https://mmbiz.qpic.cn/mmbiz_png/DkXl1OHLLibwncQYAypjDs9TibDdSCBElWvXNXKcLaCBZ8cUSva6HDtibK9VuMOAzWntMUc1dVPmcict2m117ZqV5uRMxT6CseDTcbQ62puLLwc/640?wx_fmt=png&from=appmsg)

![](http://mmbiz.qpic.cn/mmbiz_png/hptuRIfkTlfzc43xusjZ2DSy1n6zsO3tgJI7PIqg671tfPhzllT8p2RmlH0nYY2ggiaP6y2o8NVAicia9PvQ9icg6g/0?wx_fmt=png) Lisa的AI生活流

 ![](<data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E%3C!-- Icon from Lucide by Lucide Contributors - https://github.com/lucide-icons/lucide/blob/main/LICENSE --%3E%3Cg fill='none' stroke='%23888888' stroke-linecap='round' stroke-linejoin='round' stroke-width='2'%3E%3Cpath d='M2.062 12.348a1 1 0 0 1 0-.696a10.75 10.75 0 0 1 19.876 0a1 1 0 0 1 0 .696a10.75 10.75 0 0 1-19.876 0'/%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3C/g%3E%3C/svg%3E>) 阅读![](<data:image/svg+xml,%3Csvg width='25' height='24' viewBox='0 0 25 24' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath fill-rule='evenodd' clip-rule='evenodd' d='M16.154 6.797l-.177 2.758h4.009c1.346 0 2.359 1.385 2.155 2.763l-.026.148-1.429 6.743c-.212.993-1.02 1.713-1.977 1.783l-.152.006-13.707-.006c-.553 0-1-.448-1-1v-8.58a1 1 0 0 1 1-1h2.44l1.263-.03.417-.018.168-.015.028-.005c1.355-.315 2.39-2.406 2.58-4.276l.01-.16.022-.572.022-.276c.074-.707.3-1.54 1.08-1.883 2.054-.9 3.387 1.835 3.274 3.62zm-2.791-2.52c-.16.07-.282.294-.345.713l-.022.167-.019.224-.023.604-.014.204c-.253 2.486-1.615 4.885-3.502 5.324l-.097.018-.204.023-.181.012-.256.01v8.218l9.813.004.11-.003c.381-.028.72-.304.855-.709l.034-.125 1.422-6.708.02-.11c.099-.668-.354-1.308-.87-1.381l-.098-.007h-5.289l.26-4.033c.09-1.449-.864-2.766-1.594-2.446zM7.5 11.606l-.21.005-2.241-.001v8.181l2.45.001v-8.186z' fill='%23000'/%3E%3C/svg%3E>) 赞 ![](<data:image/svg+xml;charset=utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E  %3Cg fill='none' fill-rule='evenodd'%3E    %3Cpath d='M0 0h24v24H0z'/%3E    %3Cpath fill='%23576B95' d='M13.707 3.288l7.171 7.103a1 1 0 0 1 .09 1.32l-.09.1-7.17 7.104a1 1 0 0 1-1.705-.71v-3.283c-2.338.188-5.752 1.57-7.527 5.9-.295.72-1.02.713-1.177-.22-1.246-7.38 2.952-12.387 8.704-13.294v-3.31a1 1 0 0 1 1.704-.71zm-.504 5.046l-1.013.16c-4.825.76-7.976 4.52-7.907 9.759l.007.287c1.594-2.613 4.268-4.45 7.332-4.787l1.581-.132v4.103l6.688-6.623-6.688-6.623v3.856z'/%3E  %3C/g%3E%3C/svg%3E>) 分享 ![](<data:image/svg+xml;charset=utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='24' height='24' viewBox='0 0 24 24'%3E  %3Cdefs%3E    %3Cpath id='a62bde5b-af55-42c8-87f2-e10e8a48baa0-a' d='M0 0h24v24H0z'/%3E  %3C/defs%3E  %3Cg fill='none' fill-rule='evenodd'%3E    %3Cmask id='a62bde5b-af55-42c8-87f2-e10e8a48baa0-b' fill='%23fff'%3E      %3Cuse xlink:href='%23a62bde5b-af55-42c8-87f2-e10e8a48baa0-a'/%3E    %3C/mask%3E    %3Cg mask='url\(%23a62bde5b-af55-42c8-87f2-e10e8a48baa0-b\)'%3E      %3Cg transform='translate\(0 -2.349\)'%3E        %3Cpath d='M0 2.349h24v24H0z'/%3E        %3Cpath fill='%23576B95' d='M16.45 7.68c-.954 0-1.94.362-2.77 1.113l-1.676 1.676-1.853-1.838a3.787 3.787 0 0 0-2.63-.971 3.785 3.785 0 0 0-2.596 1.112 3.786 3.786 0 0 0-1.113 2.687c0 .97.368 1.938 1.105 2.679l7.082 6.527 7.226-6.678a3.787 3.787 0 0 0 .962-2.618 3.785 3.785 0 0 0-1.112-2.597A3.687 3.687 0 0 0 16.45 7.68zm3.473.243a4.985 4.985 0 0 1 1.464 3.418 4.98 4.98 0 0 1-1.29 3.47l-.017.02-7.47 6.903a.9.9 0 0 1-1.22 0l-7.305-6.73-.008-.01a4.986 4.986 0 0 1-1.465-3.535c0-1.279.488-2.56 1.465-3.536A4.985 4.985 0 0 1 7.494 6.46c1.24-.029 2.49.4 3.472 1.29l.01.01L12 8.774l.851-.85.01-.01c1.046-.951 2.322-1.434 3.59-1.434 1.273 0 2.52.49 3.472 1.442z'/%3E      %3C/g%3E    %3C/g%3E  %3C/g%3E%3C/svg%3E>) 推荐 ![](<data:image/svg+xml,%3Csvg width='25' height='24' viewBox='0 0 25 24' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M22.242 7a2.5 2.5 0 0 0-2.5-2.5h-14a2.5 2.5 0 0 0-2.5 2.5v8.5a2.5 2.5 0 0 0 2.5 2.5h2.5v1.59a1 1 0 0 0 1.707.7l1-1a.569.569 0 0 0 .034-.03l1.273-1.273a.6.6 0 0 0-.8-.892v-.006L9.441 19.1l.001-2.3h-3.7l-.133-.007A1.3 1.3 0 0 1 4.442 15.5V7l.007-.133A1.3 1.3 0 0 1 5.742 5.7h14l.133.007A1.3 1.3 0 0 1 21.042 7v4.887a.6.6 0 1 0 1.2 0V7z' fill='%23000' fill-opacity='.9'/%3E%3Crect x='14.625' y='16.686' width='7' height='1.2' rx='.6' fill='%23000' fill-opacity='.9'/%3E%3Crect x='18.725' y='13.786' width='7' height='1.2' rx='.6' transform='rotate\(90 18.725 13.786\)' fill='%23000' fill-opacity='.9'/%3E%3C/svg%3E>) 留言