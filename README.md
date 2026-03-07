## IntelligenceIntegrationSystem

情报整合系统：通过抓取主流新闻网站的公开新闻，并使用AI进行分析和评分的情报系统。属于OSINT的一种。

项目地址：[https://github.com/SleepySoft/IntelligenceIntegrationSystem](https://github.com/SleepySoft/IntelligenceIntegrationSystem/tree/dev)

## v2版本的说明

从2026年2月15日开始，main分支将正式切换到v2版本。

同时v1版本归档到 [这个分支](https://github.com/SleepySoft/IntelligenceIntegrationSystem/tree/iis-v1)。

v2版本兼容v1版本的数据，数据库不需要额外的升级操作。
最新导出的数据在 [这里下载](https://pan.baidu.com/s/18PpJPCkIkB9EB2ea5zOA5Q?pwd=djts)

关于v2版本的设计理念，以及与v1版本的区别，请阅读 [这篇文章]((doc/iis_v2_concept.md)) 。

除了情报数据结构及评分机制改变外，v2版本还对爬虫框架进行了进一步的改进。
一方面通过界面“所见即所得”的方式生成爬虫配置，另一方面增加了监控及调度功能，今后接入网站会非常方便。

另外向量数据库也进行了调整，但由于时间问题并没有正式应用到本次的更新中。
导出数据也包括了所有情报对应的向量数据，使用该向量数据启动向量数据库后，是可以使用相关功能的，只不过新情报不会更新到向量数据库而已。

经过调整后的向量数据库对关联情报的查询表现优异，接下来我会重点研究情报的聚合。

## 更新与通知

## 起因

现在的新闻素质堪忧，特别是国内媒体。

+ 一方面现代社会每日产生的新闻数量巨大，并且参杂着毫无情报价值的水文。

+ 另一方面媒体看重点击量，所以标题成为了吸引点击的工具而非事件的概括。

我一直认为，公开信息中有四成只需要看标题，有两成看总结即可，而只有不到一成的信息有阅读全文的必要。而剩下的三成都是垃圾。

既然媒体们自己不体面，那么我来让新闻体面。

## 原理与实现

本程序核流程为：抓取 -> 提交到情报中心 -> 清洗、AI分析 -> 筛选并重发布 -> 归档

程序的结构如下：

### 抓取

> 本程序只通过RSS抓取公开新闻，原因在于这类新闻抓取难度小（本身就是给RSS阅读器的公开信息），且法律风险低。

程序中由[CrawlerServiceEngine.py](CrawlerServiceEngine.py)**启动**并驱动[CrawlTasks](CrawlTasks)目录下的抓取模块，
> 
> 该服务框架会监控该目录下的文件更新并重新加载更新后的模块。
> 

当前各个抓取模块主要通过[CommonFeedsCrawFlow.py](Workflow/RssFeedsBasedCrawlFlow.py)这个通用流程进行抓取并将抓取内容提交到IntelligenceHub。
> 
> 抓取模块通过partial构建偏函数供抓取流程调用。
>
> 实际上采集数据只需要按照 ```class CollectedData``` 定义格式将数据通过 POST 提交到 ```/collect``` 这个端点的网络服务即可。
> 唯一需要注意的是如果设置了安全Token，则提交数据时要将该凭据附上。至于数据的来源，IHub并不关心。
> 
> 使用通用流程的好处在于增加一个RSS源抓取非常方便，并且通用流程中实现了抓取记录和防重复抓取的功能。
> 
> 如果想抓取非RSS源，或者需要抓取的网页需要特殊技术，则需要自己实现抓取器。同时注意法律风险。
> 

当前实现的抓取方式有：

+ [RequestsScraper.py](Scraper/RequestsScraper.py)：用以抓取简单的内容。最快，但对于动态网页来说抓取不到。
+ [PlaywrightRawScraper.py](Scraper/PlaywrightRawScraper.py)：使用Playwright的无头浏览器抓取 ，速度一般，能抓取到一些requests抓取不到的网页。
+ [PlaywrightRenderedScraper.py](Scraper/PlaywrightRenderedScraper.py)：同是无头浏览器方案，但等待网页渲染完成，最慢，但成功率最高。
+ [Crawl4AI.py](Scraper/Crawl4AI.py)：未实现。

### IntelligenceHub

+ [IntelligenceHub.py](IntelligenceHub.py)（IHub）：程序的核心。所有的信息都会提交汇总至此，由该模块进行处理、分析、归档，并提供查询功能。
+ [IntelligenceHubWebService.py](IntelligenceHubWebService.py)：为IHub提供网络服务的模块，包括API、网页发布和鉴权。
+ 
+ [IntelligenceHubStartup.py](IntelligenceHubStartup.py)：初始化所有子组件、IntelligenceHub和IntelligenceHubWebService。
+ [IntelligenceHubLauncher.py](IntelligenceHubStartup.py)：IHub的**启动**器，选用合适的backend载入IntelligenceHubWebService的wsgi_app，
  > [20250910] 提供Flask原生、waitress、gunicorn三种WSGI服务器，默认服务器为waitress。
  > 
  > 注意gunicorn仅支持Linux。
  > 
  > 该文件不包含业务代码，几乎全部由AI生成，没有阅读的必要。如果对启动原理不理解，可以去搜索WSGI的机制。
  > 

> IHub的处理流程请参见：[IIS_Diagram.drawio](doc/IIS_Diagram.drawio)

### 分析

+ [prompts.py](prompts_v1x.py)

情报分析的所有prompt。程序中的dict校验和该prompt指示的输出格式紧密相关，如果prompt改变，那么校验规则同样需要改变。

已知的问题为：

1. 该prompt在小模型（甚至于65b）上表现不佳。
> 
> 在小模型上AI通常不按规定格式输出，有可能是prompt + 文章内容太长，使AI无法集中注意力的缘故。
> 
> 正式部署的环境使用的是满血云服务，这是一笔不小的开支。
> 

2. AI评分还是过于宽松，没有达到我的期望。
> 
> 对于一些非情报新闻，AI还是给出了6分的评价，尽管我在prompt中强调不含情报的数据应该抛弃，但效果不佳。
> 
> 对于情报的评分偏高，我理想中80%的新闻应当处于6分及以下的区间。
> 

+ [IntelligenceAnalyzerProxy.py](ServiceComponent/IntelligenceAnalyzerProxy.py)
>
> AI分析实现的主要文件。调用AI Client，组织数据、使用prompt进行分析，并解析和返回结果。
> 
> 值得一提的是，自从使用了json_repair后，python的解析率几乎100%。接下来我会尝试在小模型上使用constrained decoding，看是否能提升表现。
>

### 内容发布

如前所述，网络服务由[IntelligenceHubWebService.py](IntelligenceHubWebService.py)提供。包含以下内容：

+ 登录与鉴权
    > 由 WebServiceAccessManager 和 [UserManager.py](ServiceComponent/UserManager.py) 进行管理。其中：
    >  
    > + API Token位于配置文件中：[config_example.json](config_example.json)
    > + 登录与注销的页面分别为：'/login'，'/logout'
    > + 用户信息保存在Authentication.db，通过[UserManagerConsole.py](Scripts/UserManagerConsole.py)管理用户。

+ WebAPI
    > '/api'接口：采用 [ArbitraryRPC.py](MyPythonUtility/ArbitraryRPC.py) ，不用额外编码或配置即可调用Stub的所有函数，同时支持任意层次的转发调用。
    > 
    > '/collect'接口：收集采集情报。
    > 
    > 其它API接口：子功能，如Log、统计、监控等等，由对应模块注册路由。
    >

+ 网页
    > 不使用前后端的架构，所有内容由服务器生成。包括以下文件：
    > 
    > [PostManager.py](ServiceComponent/PostManager.py)：根据 [posts](posts) 目录下的markdown文件生成HTML。
    > 
    > [ArticleRender.py](recycled/ArticleRender.py)：文章页面。
    > 
    > [ArticleListRender.py](recycled/ArticleListRender.py)：文章列表页面。
    > 
    > [intelligence_search.html](templates/intelligence_search.html)：文章查询页面（20251029：重构为前后端分离）。
    > 
    > （旧）[ArticleTableRender.py](recycled/ArticleTableRender.py)：文章列表项。
    > （新）[intelligence_table.js](static/js/intelligence_table.js)：文章列表项。
    > 
    > 子功能页面，由对应模块提供，前后端分离。这里就不列出了，详见登录后的管理页面。
    > 

### 存储

程序会生成以下内容：

+ 情报存储（主要）
  > MongoDB，数据库名：IntelligenceIntegrationSystem。包含三个记录：
  > + intelligence_cached：Collector提交的采集到的原始新闻数据。
  > + intelligence_archived：经过处理并归档的数据。
  > + 

+ 向量数据库
  > 供向量查询，保留。
  > 
  > 如果开启，会存储于：[IntelligenceIndex](IntelligenceIndex)目录

+ 鉴权信息
  > 文件：[Authentication.db](Authentication.db)
  > 
  > 供 [UserManager.py](ServiceComponent/UserManager.py) 使用，可通过 [UserManagerConsole.py](Scripts/UserManagerConsole.py) 工具进行管理。

+ 抓取内容
  > 目录：[content_storage](content_storage)
  > 
  > 分网站和RSS子项二级目录，可以通过查看抓取内容对抓取脚本进行问题分析。

+ 对话内容
  > 目录：[conversion](conversion)
  > 
  > 和AI的沟通记录，可以通过查看记录对AI分析的效果进行评估。

+ 生成网页
  > 目录：[generated](templates/generated)
  > 
  > [PostManager.py](ServiceComponent/PostManager.py) 生成的网页

## 环境配置及部署运行

#### 依赖软件

+ MongoDB

程序使用MongoDB数据库存储情报文档，这是一个NoSql数据库，请在官网下载：
> 
> https://www.mongodb.com/products/self-managed/community-edition
> 

同时建议安装mongodb tools，用以导出及导出数据库（从某个版本开始命令行工具不再和MongoDB主程序打包）：
> 
> https://www.mongodb.com/try/download/database-tools
> 


#### 创建与激活虚拟环境（可选）

本项目建议使用python版本为3.10以上。当然，不创建虚拟环境，直接使用系统默认的python环境也不是不行。

所谓python虚拟环境，其实非常简单，它就是一个目录，当你切换到这个虚拟环境时，使用的解析器、安装的库、使用的库，都仅限于该目录下，从而和其它环境隔离。

知道这个原理后，大家应该能想到：使用pycharm时，选择已创建的虚拟环境其实就是选择这个目录下的python.exe。

创建虚拟环境主要有三种方法：
+ 原生的venv
+ Anaconda（及其兼容方法）
+ uv

##### venv

```
# 创建虚拟环境
# - 通常在项目目录下执行以下命令，虚拟环境的python版本跟你当前运行的python环境有关
# - 对我来说，通常是在anaconda下创建一个指定版本python的虚拟环境，再使用这个虚拟环境创建venv
# - （那为什么不直接用anaconda？好问题。）

python -m venv .venv

# 切换到该虚拟环境（接下来安装依赖前都需要先切换到该虚拟环境，下同）

# ---- Windows ----
.venv\Scripts\activate.bat

# ----- Linux -----
source .venv/Scripts/activate
```

##### Anaconda

Anaconda好处是方便，缺点是重

下载：https://www.anaconda.com/download

```
# 创建虚拟环境
conda create -n iis python=3.10

# 切换到该虚拟环境
conda activate iis
```

##### uv

这是现在流行的工具，非常轻量，而且快，不过我还不是很熟悉。以下内容来自AI。

```
# 安装uv
pip install uv

# 创建虚拟环境
uv venv

# 切换到该虚拟环境
.venv\Scripts\activate.bat

# 接下来可以使用pip install -r，也可以使用uv的方式安装依赖（自行查阅）。
```

#### 程序部署

```
# Clone this project to your local
git clone https://github.com/SleepySoft/IntelligenceIntegrationSystem.git

# Enter this project dir
cd IntelligenceIntegrationSystem

# Important: Fetch sub modules
git submodule update --init --recursive

# -------------------------------------------------------------------------------
# ! Reference to above: Create virtual environment and switch to this environment
# -------------------------------------------------------------------------------

# Old pip version will not support utf-8, so upgrade to newest pip first.
python.exe -m pip install --upgrade pip

# Install dependency
pip install -r requirements.txt

# If has dependency issue when using upper command
pip install -r requirements_freeze.txt

# ------------------------------------------------------------------------------------
# ! Before launching program, you should do some config first (read following section)
# ------------------------------------------------------------------------------------

# After pip install. Install playwright's headless browser
playwright install chromium

# Run the Vector DB (Optional)
python VectorDB/VectorDBBService.py \
    --db-path D:\Code\IntelligenceIntegrationSystem\_data\VectorDB 
    --model D:\Code\bge-m3

# Run main service
python IntelligenceHubLauncher.py

# Run collectors
python CrawlerServiceEngine.py
```

#### 程序以外的配置

+ 重要：运将 config_example.json 复制为 config.json，按照实际情况更改配置（默认能启动，但不能进行分析）。
> 
> 配置主要在 [IntelligenceHubStartup.py](IntelligenceHubStartup.py) 中载入，阅读该文件可以知道各配置项的用法。
> 
> 如果想使用AI进行情报分析，需要配置 ai_service 项，包括token。
> 
> 如果想使用咸鱼上购买的批量14元key，需要配置 ai_service_rotator 项，指定key文件。
> 
> 对于抓取外网新闻，需要配置 global_site_proxy。
> 

+ 重要：运行 [UserManagerConsole.py](Scripts/UserManagerConsole.py) ，按提示增加一个用户，设置密码。

#### 使用

+ 程序运行后，打开 [localhost:5000/login](localhost:5000/login) 输入刚才配置的账号密码进入后台页面。

+ 打开[localhost:5000](localhost:5000)则是无密码的公开页面。


## 其它工具

+ MongoDB工具
  > https://www.mongodb.com/try/download/database-tools
  > 
  > 用以导出/导出MongoDB记录，可以配合[mongodb_exporter.py](Scripts/mongodb_exporter.py)一系列脚本使用。


## 已接入的网站

```js
{ domain: "voanews.com", nameCN: "美国之音", country: "USA", flag: "🇺🇸", accessibleInChina: false },
{ domain: "bbc.com", nameCN: "英国广播公司", country: "UK", flag: "🇬🇧", accessibleInChina: false },
{ domain: "cbc.ca", nameCN: "加拿大广播公司", country: "Canada", flag: "🇨🇦", accessibleInChina: false },
{ domain: "rfi.fr", nameCN: "法国国际广播电台", country: "France", flag: "🇫🇷", accessibleInChina: false },
{ domain: "dw.com", nameCN: "德国之声", country: "Germany", flag: "🇩🇪", accessibleInChina: false },
{ domain: "abc.net.au", nameCN: "澳大利亚广播公司", country: "Australia", flag: "🇦🇺", accessibleInChina: false },
{ domain: "elpais.com", nameCN: "国家报", country: "Spain", flag: "🇪🇸", accessibleInChina: false },
{ domain: "investing.com", nameCN: "英为财情", country: "International", flag: "🌍", accessibleInChina: true },
{ domain: "aljazeera.com", nameCN: "半岛电视台", country: "Qatar", flag: "🇶🇦", accessibleInChina: true },
{ domain: "aa.com.tr", nameCN: "阿纳多卢通讯社", country: "Turkey", flag: "🇹🇷", accessibleInChina: true },
{ domain: "nhk.or.jp", nameCN: "日本广播协会", country: "Japan", flag: "🇯🇵", accessibleInChina: true },
{ domain: "xinhuanet.com", nameCN: "新华社", country: "China", flag: "🇨🇳", accessibleInChina: true },
```


## 意见和建议

如果有意见和建议，可以到这个讨论下留言：[https://zhuanlan.zhihu.com/p/1957783829684154704](https://zhuanlan.zhihu.com/p/1957783829684154704)

或者可以加入wx讨论组：

![img.png](doc/wx_group_qr.png)
