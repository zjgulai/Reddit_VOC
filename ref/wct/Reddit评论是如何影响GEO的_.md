     Reddit评论是如何影响GEO的？ \* { margin: 0; padding: 0; outline: 0; } body { font-family: "PingFang SC", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif; line-height: 1.6; } .\_\_page\_content\_\_ { max-width: 667px; margin: 0 auto; padding: 20px; text-size-adjust: 100%; color: rgba(0, 0, 0, 0.9); padding-bottom: 64px; } .title { user-select: text; font-size: 22px; line-height: 1.4; margin-bottom: 14px; font-weight: 500; } .\_\_meta\_\_ { color: rgba(0, 0, 0, 0.3); font-size: 15px; line-height: 20px; hyphens: auto; word-break: break-word; margin-bottom: 50px; } .\_\_meta\_\_ .nick\_name { color: #576B95; } .\_\_meta\_\_ .copyright { color: rgba(0, 0, 0, 0.3); background-color: rgba(0, 0, 0, 0.05); padding: 0 4px; margin: 0 10px 10px 0; } blockquote.source { padding: 10px; margin: 30px 0; border-left: 5px solid #ccc; color: #333; font-style: italic; word-wrap: break-word; } blockquote.source a { cursor: pointer; text-decoration: underline; } .item\_show\_type\_0 > section { margin-top: 0; margin-bottom: 24px; } a { color: #576B95; text-decoration: none; cursor: default; } .text\_content { margin-bottom: 50px; user-select: text; font-size: 17px; white-space: pre-wrap; word-wrap: break-word; line-height: 28px; hyphens: auto; } .picture\_content .picture\_item { margin-bottom: 30px; } .picture\_content .picture\_item .picture\_item\_label { text-align: center; } img { max-width: 100%; } .pay\_subscribe\_notice { margin: 30px 0; padding: 20px; background: #fffbe6; border: 1px solid #ffe58f; border-radius: 8px; } .pay\_subscribe\_badge { display: inline-block; padding: 4px 12px; background: #faad14; color: #fff; border-radius: 4px; font-size: 14px; font-weight: 500; margin-bottom: 12px; } .pay\_subscribe\_desc { font-size: 15px; line-height: 1.8; color: rgba(0, 0, 0, 0.7); margin-bottom: 12px; } .pay\_subscribe\_hint { font-size: 13px; color: rgba(0, 0, 0, 0.4); } .\_\_bottom-bar\_\_ { display: flex; justify-content: space-between; align-items: center; position: fixed; bottom: 0; left: 0; right: 0; height: 64px; padding: 8px 20px; background: white; box-sizing: border-box; border-top: 1px solid rgba(0, 0, 0, 0.2); } .\_\_bottom-bar\_\_ .left { display: flex; align-items: center; font-size: 15px; white-space: nowrap; } .\_\_bottom-bar\_\_ .right { display: flex; } .\_\_bottom-bar\_\_ .sns\_opr\_btn { display: flex; align-items: center; user-select: none; background: transparent; border: 0; color: rgba(0, 0, 0, 0.9); font-size: 14px; } .\_\_bottom-bar\_\_ .sns\_opr\_btn:not(:last-child) { margin-right: 16px; } .\_\_bottom-bar\_\_ .sns\_opr\_btn > img { margin-right: 4px; }

Reddit评论是如何影响GEO的？
==================

原创 Lisa Lisa的AI生活流 2026-06-19 12:00 广东

> 原文地址: [https://mp.weixin.qq.com/s/hbz-CIQDVS7wsep9VIHuzQ](https://mp.weixin.qq.com/s/hbz-CIQDVS7wsep9VIHuzQ)

**Lisa的AI生活流**

**记录AI时代的表达日常**

  

  

Deep Research 带引用，也可能被一条 Reddit 评论带偏
====================================

我最近看到一篇挺适合所有 AI 重度用户读的论文。

它研究的不是“AI 会不会胡说八道”，而是另一个更容易被忽略的问题：

AI 明明认真上网查了资料，明明给了引用，最后还是可能被一条 Reddit 评论带偏。

这篇论文叫《Deep-Research Agents Can Be Poisoned via User-Generated Content》，2026 年 5 月发在 arXiv 上。

作者看的是 Deep Research 这一类智能体：它们不是简单回答问题，而是会自己拆任务、搜网页、读资料、整合报告。

听起来比普通聊天更可靠。

但问题也出在这里。

它越会搜索，越会整合，越可能把公开网页里那些“看起来相关”的内容吸进来。

而公开网页里，有很多内容是普通用户可以写的。

Reddit 评论、Wiki 编辑、YouTube 评论、论坛帖子、社区问答。

这些内容本来很有价值。我自己也经常用 Reddit 做产品验证，因为里面有很多没被包装过的用户原话。

但从安全角度看，它也有一个天然问题：

**任何人都可能往里面塞东西。**

论文到底发现了什么？
----------

先说结论。

作者提出了一种攻击方式，叫 WARP，Web Agent Retrieval Poisoning。

![图像](https://mmbiz.qpic.cn/mmbiz_jpg/DkXl1OHLLibxFhdPxoqNujJU3Riaqgb1RibAZDFqtMWiaBy1tGsWqUic1awwe1fZVVial6ppD5VdgMsPdZEogwkZycice4sa32jUC6nhfQ7Gzsvia4w/640?wx_fmt=jpeg&from=appmsg)

翻译成人话就是：

攻击者不需要控制模型，也不需要黑进搜索引擎，更不需要知道你的系统提示词。

他只要把一小段内容放到 Deep Research 可能搜到的网页里，就可能影响最终报告。

比如，一个 Reddit 帖子下面多了一条评论。

这条评论不长，可能就十几个词。

但如果 Deep Research 在研究某个问题时反复搜到这个页面，它就可能把这条评论当成一个可参考信号。

论文里测了 STORM、Co-STORM、OmniThink 三个研究型系统。

结果里有几个数字很值得看：

17%-23%

检索 URL 来自用户生成内容。

54%-71%

UGC 来源里，Reddit 占比最高。

也就是说，Deep Research 在做复杂研究时，经常会用到社区内容。

这不奇怪。

因为社区内容确实有很多一手经验、真实吐槽、产品反馈。

问题来了，如果攻击者也知道这一点呢？

一条短评论，怎么影响一份长报告？
----------------

这篇论文最有意思的地方，是它没有假设攻击者很强。

攻击者不需要写一篇完整文章。

也不需要把恶意内容做成 SEO 排名第一的网页。

在 SERP snippet 场景里，作者发现，单个被污染 URL，加上一段大约 13 个词的注入文本，只要这段内容被系统检索到，最终报告里出现攻击者指定内容的比例可以到 38% 到 51%。

如果攻击多个 URL，这个比例还能到 42% 到 62%。

full-content 场景也类似。

哪怕污染文本只占完整 Reddit 线程内容不到 4%，仍然可能在最终报告里出现。

13 个词

一次短注入就可能影响报告。

38%-51%

单个污染 URL 的条件提及率。

42%-62%

多个目标 URL 时的条件提及率。

<4%

污染文本在完整 Reddit 线程中的占比。

这里有个很生活化的比喻。

Deep Research 像一个特别勤奋的实习生。

你让它写一份行业报告，它会自己列提纲、搜资料、看评论区、整理观点、最后交一份带引用的文档。

但如果它没有分清“官方公告”“媒体报道”“匿名评论”“社区吐槽”的权重，它就可能把一张便利贴上的话，和一份审计报告放在同一个证据篮子里。

它不是懒。

它恰恰是太勤奋了。

搜得越多，接触到的污染点也越多。

带引用，不等于可信
---------

以前我们判断 AI 回答靠不靠谱，经常会问一句：

“有没有来源？”

有来源当然比没来源好。

但这篇论文提醒我们，下一步应该问：

**“这个来源是谁写的？它有多容易被改？”**

一条 Reddit 评论也是来源。

一个论坛回复也是来源。

一个 Wiki 页面也是来源。

它们不一定没价值，但它们的可信度不能和官方文档、论文、监管公告、公司财报放在同一层。

我现在会把联网 AI 的引用分成四类看：

1.  官方来源：产品文档、公司公告、论文原文、标准文件、政府或监管页面。
    
2.  专业二手来源：媒体报道、行业报告、机构分析。
    
3.  社区经验来源：Reddit、论坛、问答社区、个人博客。
    
4.  匿名碎片来源：评论区、短帖、未署名转载、聚合页面。
    

Deep Research 最容易让人放松警惕的地方，是它把这些来源揉成一份很顺滑的报告。

读起来像一篇完成度很高的研究。

但报告的可读性，不等于证据链的可靠性。

对普通用户，怎么用更稳一点？
--------------

如果你只是拿 Deep Research 做泛读，比如了解一个新概念、快速扫一个行业、整理某个工具的优缺点，问题不大。

社区内容反而有帮助。

它能告诉你真实用户怎么抱怨、怎么绕路、怎么踩坑。

但如果你用它做高风险判断，就要多走一步。

*   买不买某只股票。
    
*   要不要采购某个企业软件。
    
*   某个医疗建议是否可靠。
    
*   某个法律结论能不能直接采用。
    
*   某个竞品是否真的有某项能力。
    

这时候不要只看最终总结。

我会多做三件事。

第一，看引用来源。

如果关键结论主要来自 Reddit、论坛、评论区，就先把它当成线索，不要当成事实。

第二，让 AI 反向列证据等级。

请把这份报告里的证据按官方来源、媒体来源、社区来源、匿名来源分类，并标出哪些结论只依赖 UGC。

第三，要求它找反证。

请找能反驳这份结论的官方资料或高可信来源。

这一步很有用。

很多 AI 报告的问题不是没有资料，而是资料都朝一个方向堆。

你让它找反证，能更快看出结论是不是站得住。

对做 AI 产品的人，不能只做过滤
-----------------

论文里也测试了一些防御方式。

比如屏蔽 UGC、输入过滤、输出过滤。

听起来都合理，但效果并不稳定。

直接屏蔽 UGC，会损失很多真实用户经验。

因为 Reddit、论坛、问答社区本来就是很多问题的一手现场。

输入过滤和输出过滤，也很难覆盖所有变体。

攻击文本可以写得很短、很自然、很像普通评论。

所以我更认同一种做法：

**不要只问“这段内容能不能进来”，还要问“它进来以后应该占多少权重”。**

也就是给来源做风险分层。

官方文档和匿名评论，不应该在同一个权重里投票。

高风险任务和低风险任务，也不应该用同一套检索策略。

如果是做娱乐推荐，UGC 权重高一点没关系。

如果是做医疗、法律、金融、采购，UGC 应该默认降权，甚至只作为“用户反馈线索”，不能作为主要证据。

Agent 的风险不只在它会回答错。

更在于它的输出可能进入下一步流程。

普通聊天错了，你最多重新问。

Deep Research 错了，可能进入报告。

Agent 错了，可能触发采购、发邮件、改数据库、跑代码。

所以系统越自动，证据链越要清楚。

我会怎么改自己的使用习惯
------------

这篇论文看完后，我不会因此不用 Deep Research。

相反，我会继续用。

只是使用方式会分层。

如果是探索一个新话题，我会让它大胆搜，UGC 也可以进来。

因为这时候我需要的是广度。

如果是写公众号、做选题、看用户痛点，Reddit 这种社区内容很有用。

因为我想看的是“用户怎么说话”。

但如果是要形成判断，我会让它多走一轮证据审计。

尤其是这三个问题：

*   这个结论主要来自哪里？
    
*   有没有官方或原始来源支持？
    
*   有没有只靠社区评论支撑的部分？
    

Deep Research 不是不能信。

它更像一个研究助理。

研究助理可以帮你翻资料、整理线索、写初稿。

但最后决定哪些证据能上桌，还是要有一套审稿规则。

最后
--

AI 搜索和 Deep Research 正在把“查资料”这件事变得很轻。

以前我们懒得查。

现在 AI 太会查。

新的问题就变成了：

*   它查到的东西，谁写的？
    
*   谁能改？
    
*   为什么它被当成证据？
    

下次你看到一份带引用的 AI 报告，可以先别急着放心。

点开几条关键引用看看。

如果核心结论来自一条社区评论，那它更像一个线索。

不是结案陈词。

#### 素材来源

arXiv 论文：Deep-Research Agents Can Be Poisoned via User-Generated Content

https://arxiv.org/html/2605.24245v1

别客气，点个关注

咱们一起折腾 AI！(๑˃̵ᴗ˂̵)و

  

  

往期回顾：

[Reddit 数据型内容为什么更容易获得信任](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484838&idx=1&sn=1cbb0396c39753cae2b67e568879c258&scene=21#wechat_redirect)

[Reddit内容洞察飞书多维表自动化工作流分享](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484832&idx=1&sn=354fb2946e18ad95fc9b9cde2958f96d&scene=21#wechat_redirect)

[Reddit提问型内容为什么容易获得评论](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484811&idx=1&sn=feb87ead91c80a0570884f130d39efb5&scene=21#wechat_redirect)

[Reddit 故事型内容如何降低营销感？](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484806&idx=1&sn=83008b536e12c15555242eada35a9c3b&scene=21#wechat_redirect)

[Reddit 标题怎么写，才更容易被点开？](https://mp.weixin.qq.com/s?__biz=MzI0NDQyNDg0OA==&mid=2247484800&idx=1&sn=2246fb5074b7b248b09ce5e9e2962460&scene=21#wechat_redirect)

  

![](https://mmbiz.qpic.cn/sz_mmbiz_png/DkXl1OHLLibyxtmibvCvNDKGOgUrIdOL7eibvzoM6Mgg1cIwn4vZ5Kt4VyfJ3W5mPbsOJxe8e3gHibtAnDwFmgiaMvzGVzeyZaGHjbrR3bAW9IBg/640?wx_fmt=png&from=appmsg)

![](http://mmbiz.qpic.cn/mmbiz_png/hptuRIfkTlfzc43xusjZ2DSy1n6zsO3tgJI7PIqg671tfPhzllT8p2RmlH0nYY2ggiaP6y2o8NVAicia9PvQ9icg6g/0?wx_fmt=png) Lisa的AI生活流

 ![](<data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E%3C!-- Icon from Lucide by Lucide Contributors - https://github.com/lucide-icons/lucide/blob/main/LICENSE --%3E%3Cg fill='none' stroke='%23888888' stroke-linecap='round' stroke-linejoin='round' stroke-width='2'%3E%3Cpath d='M2.062 12.348a1 1 0 0 1 0-.696a10.75 10.75 0 0 1 19.876 0a1 1 0 0 1 0 .696a10.75 10.75 0 0 1-19.876 0'/%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3C/g%3E%3C/svg%3E>) 阅读![](<data:image/svg+xml,%3Csvg width='25' height='24' viewBox='0 0 25 24' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath fill-rule='evenodd' clip-rule='evenodd' d='M16.154 6.797l-.177 2.758h4.009c1.346 0 2.359 1.385 2.155 2.763l-.026.148-1.429 6.743c-.212.993-1.02 1.713-1.977 1.783l-.152.006-13.707-.006c-.553 0-1-.448-1-1v-8.58a1 1 0 0 1 1-1h2.44l1.263-.03.417-.018.168-.015.028-.005c1.355-.315 2.39-2.406 2.58-4.276l.01-.16.022-.572.022-.276c.074-.707.3-1.54 1.08-1.883 2.054-.9 3.387 1.835 3.274 3.62zm-2.791-2.52c-.16.07-.282.294-.345.713l-.022.167-.019.224-.023.604-.014.204c-.253 2.486-1.615 4.885-3.502 5.324l-.097.018-.204.023-.181.012-.256.01v8.218l9.813.004.11-.003c.381-.028.72-.304.855-.709l.034-.125 1.422-6.708.02-.11c.099-.668-.354-1.308-.87-1.381l-.098-.007h-5.289l.26-4.033c.09-1.449-.864-2.766-1.594-2.446zM7.5 11.606l-.21.005-2.241-.001v8.181l2.45.001v-8.186z' fill='%23000'/%3E%3C/svg%3E>) 赞 ![](<data:image/svg+xml;charset=utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E  %3Cg fill='none' fill-rule='evenodd'%3E    %3Cpath d='M0 0h24v24H0z'/%3E    %3Cpath fill='%23576B95' d='M13.707 3.288l7.171 7.103a1 1 0 0 1 .09 1.32l-.09.1-7.17 7.104a1 1 0 0 1-1.705-.71v-3.283c-2.338.188-5.752 1.57-7.527 5.9-.295.72-1.02.713-1.177-.22-1.246-7.38 2.952-12.387 8.704-13.294v-3.31a1 1 0 0 1 1.704-.71zm-.504 5.046l-1.013.16c-4.825.76-7.976 4.52-7.907 9.759l.007.287c1.594-2.613 4.268-4.45 7.332-4.787l1.581-.132v4.103l6.688-6.623-6.688-6.623v3.856z'/%3E  %3C/g%3E%3C/svg%3E>) 分享 ![](<data:image/svg+xml;charset=utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='24' height='24' viewBox='0 0 24 24'%3E  %3Cdefs%3E    %3Cpath id='a62bde5b-af55-42c8-87f2-e10e8a48baa0-a' d='M0 0h24v24H0z'/%3E  %3C/defs%3E  %3Cg fill='none' fill-rule='evenodd'%3E    %3Cmask id='a62bde5b-af55-42c8-87f2-e10e8a48baa0-b' fill='%23fff'%3E      %3Cuse xlink:href='%23a62bde5b-af55-42c8-87f2-e10e8a48baa0-a'/%3E    %3C/mask%3E    %3Cg mask='url\(%23a62bde5b-af55-42c8-87f2-e10e8a48baa0-b\)'%3E      %3Cg transform='translate\(0 -2.349\)'%3E        %3Cpath d='M0 2.349h24v24H0z'/%3E        %3Cpath fill='%23576B95' d='M16.45 7.68c-.954 0-1.94.362-2.77 1.113l-1.676 1.676-1.853-1.838a3.787 3.787 0 0 0-2.63-.971 3.785 3.785 0 0 0-2.596 1.112 3.786 3.786 0 0 0-1.113 2.687c0 .97.368 1.938 1.105 2.679l7.082 6.527 7.226-6.678a3.787 3.787 0 0 0 .962-2.618 3.785 3.785 0 0 0-1.112-2.597A3.687 3.687 0 0 0 16.45 7.68zm3.473.243a4.985 4.985 0 0 1 1.464 3.418 4.98 4.98 0 0 1-1.29 3.47l-.017.02-7.47 6.903a.9.9 0 0 1-1.22 0l-7.305-6.73-.008-.01a4.986 4.986 0 0 1-1.465-3.535c0-1.279.488-2.56 1.465-3.536A4.985 4.985 0 0 1 7.494 6.46c1.24-.029 2.49.4 3.472 1.29l.01.01L12 8.774l.851-.85.01-.01c1.046-.951 2.322-1.434 3.59-1.434 1.273 0 2.52.49 3.472 1.442z'/%3E      %3C/g%3E    %3C/g%3E  %3C/g%3E%3C/svg%3E>) 推荐 ![](<data:image/svg+xml,%3Csvg width='25' height='24' viewBox='0 0 25 24' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M22.242 7a2.5 2.5 0 0 0-2.5-2.5h-14a2.5 2.5 0 0 0-2.5 2.5v8.5a2.5 2.5 0 0 0 2.5 2.5h2.5v1.59a1 1 0 0 0 1.707.7l1-1a.569.569 0 0 0 .034-.03l1.273-1.273a.6.6 0 0 0-.8-.892v-.006L9.441 19.1l.001-2.3h-3.7l-.133-.007A1.3 1.3 0 0 1 4.442 15.5V7l.007-.133A1.3 1.3 0 0 1 5.742 5.7h14l.133.007A1.3 1.3 0 0 1 21.042 7v4.887a.6.6 0 1 0 1.2 0V7z' fill='%23000' fill-opacity='.9'/%3E%3Crect x='14.625' y='16.686' width='7' height='1.2' rx='.6' fill='%23000' fill-opacity='.9'/%3E%3Crect x='18.725' y='13.786' width='7' height='1.2' rx='.6' transform='rotate\(90 18.725 13.786\)' fill='%23000' fill-opacity='.9'/%3E%3C/svg%3E>) 留言