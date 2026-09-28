"""统一的浏览器指纹（UA / sec-ch-ua）。

阿里风控网关会把 x5sec 通行 Cookie 与验证时浏览器的 User-Agent、
sec-ch-ua 指纹强绑定：不同模块各用各的 UA 版本会导致"验证通过但
请求被拒"（RRXVv_ERROR / FAIL_SYS_USER_VALIDATE）的指纹分裂问题
（见 issue #62）。所有出站请求与滑块浏览器必须从这里取值，保持一致。

升级版本时只需改这一处，并同步更新滑块浏览器的 UA。
"""

# 当前对齐的现代稳定版 Chrome 大版本
CHROME_MAJOR = "151"

# 标准 Windows Chrome UA
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_MAJOR}.0.0.0 Safari/537.36"
)

# Chrome 151 时代的 GREASE brand 格式
SEC_CH_UA = (
    f'"Not=A?Brand";v="99", "Google Chrome";v="{CHROME_MAJOR}", '
    f'"Chromium";v="{CHROME_MAJOR}"'
)
