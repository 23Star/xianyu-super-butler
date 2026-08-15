#!/bin/sh
set -eu

# 滑块验证必须以有头模式跑：无头 Chrome 的 WebGL 渲染器、字体列表、
# navigator.plugins 与屏幕参数和有头差异巨大，会被阿里 nc 直接识破
# （见 XianyuAutoAsync.py 里 SLIDER_HEADLESS 的说明）。
#
# 但容器里没有物理显示器，Linux 上有头 Chromium 缺少 X server 会直接
# 启动失败（Missing X server or $DISPLAY），滑块链路等于从未跑起来。
# 这里用 Xvfb 提供虚拟显示补上这一环。
DISPLAY_NUM="${XVFB_DISPLAY_NUM:-99}"
SCREEN_SPEC="${XVFB_SCREEN:-1920x1080x24}"

start_xvfb() {
    command -v Xvfb >/dev/null 2>&1 || {
        echo "[entrypoint] 未安装 Xvfb，滑块将退化为无头模式（通过率显著下降）"
        return 1
    }

    Xvfb ":${DISPLAY_NUM}" -screen 0 "${SCREEN_SPEC}" -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &
    xvfb_pid=$!

    # 等显示就绪再放行，否则先启动的浏览器仍会连不上
    i=0
    while [ "$i" -lt 30 ]; do
        if ! kill -0 "$xvfb_pid" 2>/dev/null; then
            echo "[entrypoint] Xvfb 启动失败，详见 /tmp/xvfb.log"
            return 1
        fi
        if command -v xdpyinfo >/dev/null 2>&1; then
            if DISPLAY=":${DISPLAY_NUM}" xdpyinfo >/dev/null 2>&1; then
                break
            fi
        elif [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
            break
        fi
        i=$((i + 1))
        sleep 0.2
    done

    export DISPLAY=":${DISPLAY_NUM}"
    echo "[entrypoint] Xvfb 已就绪 DISPLAY=${DISPLAY} (${SCREEN_SPEC})"
    return 0
}

# 显式给了 DISPLAY 就用现成的（例如外部挂了 X server）；
# Xvfb 起不来也要让主程序照常启动 —— 滑块降级好过整个服务不可用。
if [ -n "${DISPLAY:-}" ]; then
    echo "[entrypoint] 使用已有 DISPLAY=${DISPLAY}"
elif start_xvfb; then
    :
else
    export SLIDER_HEADLESS=true
    echo "[entrypoint] 已回退 SLIDER_HEADLESS=true"
fi

exec python Start.py
