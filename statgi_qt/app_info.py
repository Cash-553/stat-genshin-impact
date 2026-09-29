# -*- coding: utf-8 -*-
"""应用的基本信息 —— 版本号、名字。

**这是个叶子模块：不 import 任何内部模块。**

为什么要单独拆出来：
    原来 VERSION 写在 qt_pages.py 里，而 qt_update.py 要读它 →
        qt_update  import qt_pages   （反向依赖）
    可是 qt_pages 又要用 qt_update 的 check() / CHANNELS →
        qt_pages   import qt_update
    两边互相 import，成了**循环依赖**，只能靠"在函数体里 import"绕开。
    绕开的代价：import 顺序一改就可能崩，而且报错信息会误导人。

    把版本号挪到这个谁都不依赖的叶子模块之后就没事了：
        qt_update  →  app_info      （单向）
        qt_pages   →  qt_update     （单向）
"""

VERSION = "0.9.3"
APP_NAME = "StatGI"
