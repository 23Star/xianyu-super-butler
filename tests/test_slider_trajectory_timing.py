"""拖动回放的时间轴。

回归的是这个故障：一次本该 1.15 秒的拖动实际跑了 175 秒，滑块必然判失败。

原因是曾经的「deadline 补偿」——落后于设计时间轴时丢弃后续采样点来追赶。
它的追赶循环每次只把 planned_elapsed 加一个点的 delay（约 12ms），而落后量
常常是几秒，且 index 一到保护段就停，永远追不上，于是每一步都在做无效计算。
实测直接回放只需 1.1 秒。
"""

import time
import unittest

from utils.xianyu_slider_stealth import replay_trajectory


def build_trajectory(steps=100, delay=0.012, distance=260.0):
    """与 _generate_physics_trajectory 同构的最小急动度轨迹。"""
    points = []
    for i in range(steps):
        progress = (i + 1) / steps
        eased = 10 * progress ** 3 - 15 * progress ** 4 + 6 * progress ** 5
        points.append((distance * eased, 2.0, delay))
    return points


class ReplayTrajectoryTests(unittest.TestCase):
    def test_duration_matches_design(self):
        trajectory = build_trajectory()
        design = sum(p[2] for p in trajectory)

        started = time.monotonic()
        replay_trajectory(trajectory, 100.0, 200.0, lambda x, y: None)
        elapsed = time.monotonic() - started

        # 曾经这里会膨胀到设计时长的 150 倍
        self.assertLess(elapsed, design * 3)

    def test_every_point_is_emitted(self):
        trajectory = build_trajectory(steps=60)
        seen = []

        replay_trajectory(trajectory, 10.0, 20.0, lambda x, y: seen.append((x, y)))

        # 不再丢点：丢点既救不回时间，还会把轨迹打散
        self.assertEqual(len(seen), len(trajectory))

    def test_final_position_is_exact(self):
        trajectory = build_trajectory(steps=40)
        x, y, _ = replay_trajectory(trajectory, 100.0, 200.0, lambda *_: None)

        self.assertAlmostEqual(x, 100.0 + trajectory[-1][0], places=6)
        self.assertAlmostEqual(y, 200.0 + trajectory[-1][1], places=6)

    def test_slow_move_does_not_amplify_total_time(self):
        """单步偏慢时，总耗时应接近「慢的那部分」，而不是被放大。"""
        trajectory = build_trajectory(steps=20, delay=0.005)
        per_move = 0.01

        def slow_move(x, y):
            time.sleep(per_move)

        started = time.monotonic()
        replay_trajectory(trajectory, 0.0, 0.0, slow_move)
        elapsed = time.monotonic() - started

        # 20 步 × 10ms = 0.2 秒；留一倍余量，绝不该出现数量级膨胀
        self.assertLess(elapsed, 0.2 * 3)

    def test_reports_lag(self):
        trajectory = build_trajectory(steps=10, delay=0.001)

        def slow_move(x, y):
            time.sleep(0.02)

        _, _, stats = replay_trajectory(trajectory, 0.0, 0.0, slow_move)

        # 慢下来要能被观测到，便于提示用户机器吃力
        self.assertGreater(stats["peak_lag"], 0)
        self.assertEqual(stats["total_points"], 10)

    def test_single_point_trajectory(self):
        x, y, stats = replay_trajectory([(5.0, 1.0, 0.01)], 1.0, 2.0, lambda *_: None)

        self.assertEqual(stats["total_points"], 1)
        self.assertAlmostEqual(x, 6.0)
        self.assertAlmostEqual(y, 3.0)


if __name__ == "__main__":
    unittest.main()
