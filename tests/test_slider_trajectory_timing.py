"""拖动回放的时间轴控制。

回归的是这个故障：同一份代码，配置高的机器能过滑块，配置低的机器过不去。

根因是 ``page.mouse.move()`` 是一次同步 CDP 往返，原实现「move 完再 sleep(delay)」
只控制住了每步间隔的后一半 —— 机器越慢，整条轨迹被拉得越长，速度包络失真，
而落点始终精确。阿里滑块判的是采样点的时间序列，不是落点。
"""

import unittest

from utils.xianyu_slider_stealth import PROTECTED_TAIL_POINTS, replay_trajectory


def build_trajectory(steps=120, base_delay=0.025, distance=300.0, tail=8):
    """与 _generate_physics_trajectory 同构：最小急动度主行程 + 末段回弹/稳定。"""
    trajectory = []
    for i in range(steps):
        progress = (i + 1) / steps
        eased = 10 * progress ** 3 - 15 * progress ** 4 + 6 * progress ** 5
        trajectory.append((distance * eased, 0.0, base_delay))
    for _ in range(tail):
        trajectory.append((distance - 5.0, 0.0, base_delay))
    return trajectory


class FakeClock:
    """按固定成本推进的假时钟，让用例不受真实机器速度影响。"""

    def __init__(self, move_cost):
        self.move_cost = move_cost
        self.now = 0.0
        self.moves = []

    def move(self, x, y):
        self.now += self.move_cost      # 模拟一次 CDP 往返的开销
        self.moves.append((x, y))

    def sleep(self, seconds):
        self.now += max(0.0, seconds)

    def monotonic(self):
        return self.now


class ReplayTrajectoryTests(unittest.TestCase):
    def _replay(self, move_cost, trajectory=None):
        trajectory = trajectory or build_trajectory()
        clock = FakeClock(move_cost)
        design = sum(point[2] for point in trajectory)

        import utils.xianyu_slider_stealth as slider
        original = slider.time.monotonic
        slider.time.monotonic = clock.monotonic
        try:
            started = clock.now
            x, y, stats = replay_trajectory(
                trajectory, 100.0, 200.0, clock.move, sleep=clock.sleep
            )
            actual = clock.now - started
        finally:
            slider.time.monotonic = original

        return clock, stats, actual, design, x, y

    def test_fast_machine_matches_designed_duration_without_dropping_points(self):
        clock, stats, actual, design, _, _ = self._replay(move_cost=0.001)

        self.assertEqual(stats["skipped_points"], 0)
        self.assertEqual(len(clock.moves), stats["total_points"])
        # 抖动来自每步 ±10% 的随机化，与设计时长偏差应很小
        self.assertLess(abs(actual - design) / design, 0.15)

    def test_slow_machine_keeps_duration_instead_of_stretching_it(self):
        # 每步 60ms 往返，远超 25ms 的设计间隔：修复前会被拉成设计时长的近 4 倍
        clock, stats, actual, design, _, _ = self._replay(move_cost=0.060)

        self.assertGreater(stats["skipped_points"], 0, "低配机应通过丢点追赶时间轴")
        self.assertLess(len(clock.moves), stats["total_points"])
        # 时间轴被守住：不允许出现修复前那种成倍膨胀
        self.assertLess(actual, design * 1.5)

    def test_duration_stays_stable_across_machine_speeds(self):
        durations = [self._replay(move_cost=c)[2] for c in (0.001, 0.010, 0.025, 0.060)]

        # 快慢机之间的总时长差距不应超过 50%
        self.assertLess(max(durations) / min(durations), 1.5)

    def test_final_position_is_exact_on_slow_machine(self):
        trajectory = build_trajectory()
        expected_x = 100.0 + trajectory[-1][0]
        expected_y = 200.0 + trajectory[-1][1]

        for cost in (0.001, 0.060):
            _, _, _, _, x, y = self._replay(move_cost=cost, trajectory=trajectory)
            # 松手位置决定验证结果，任何配置下都必须精确落在轨迹终点
            self.assertAlmostEqual(x, expected_x, places=6)
            self.assertAlmostEqual(y, expected_y, places=6)

    def test_tail_points_are_never_dropped(self):
        trajectory = build_trajectory()
        clock, stats, _, _, _, _ = self._replay(move_cost=0.200, trajectory=trajectory)

        tail = trajectory[-PROTECTED_TAIL_POINTS:]
        emitted = clock.moves[-PROTECTED_TAIL_POINTS:]
        # 末段（回弹 + 稳定）刻画松手瞬间的手感，性能再差也要原样发出
        self.assertEqual(len(emitted), len(tail))
        for (x, y, _), (moved_x, moved_y) in zip(tail, emitted):
            self.assertAlmostEqual(moved_x, 100.0 + x, places=6)
            self.assertAlmostEqual(moved_y, 200.0 + y, places=6)

    def test_lag_is_reported_for_diagnosis(self):
        _, fast_stats, _, _, _, _ = self._replay(move_cost=0.001)
        _, slow_stats, _, _, _, _ = self._replay(move_cost=0.060)

        # 客户日志里要能一眼看出机器是否吃得消
        self.assertLessEqual(fast_stats["peak_lag"], 0.05)
        self.assertGreater(slow_stats["peak_lag"], 0.0)

    def test_short_trajectory_still_emits_every_point(self):
        trajectory = build_trajectory(steps=3, tail=2)
        clock, stats, _, _, _, _ = self._replay(move_cost=0.200, trajectory=trajectory)

        # 轨迹短于保护段时不能丢点，否则滑块根本走不到位
        self.assertEqual(stats["skipped_points"], 0)
        self.assertEqual(len(clock.moves), len(trajectory))


if __name__ == "__main__":
    unittest.main()
