"""Property checks for independent corrective falloff, runnable without bpy."""
import importlib.util
import math
from pathlib import Path
import random
import unittest

spec = importlib.util.spec_from_file_location("bs_math", Path(__file__).resolve().parents[1] / "Rbf/bs_math.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return bs.normalize_quaternion((w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
                                    w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z))


class IndependentCorrectiveMath(unittest.TestCase):
    def test_radius_profile_and_neutral(self):
        pose = bs.euler_xyz_quaternion((math.radians(45), 0, 0))
        for distance, expected in ((0, 1), (25, .84375), (50, .5), (75, .15625), (100, 0), (120, 0)):
            current = bs.euler_xyz_quaternion((math.radians(45+distance), 0, 0))
            self.assertAlmostEqual(bs.pose_weight(current, pose, math.radians(100)), expected, places=7)
        self.assertEqual(bs.pose_weight(bs.IDENTITY, pose, math.pi), 0)
        self.assertEqual(bs.pose_weight(bs.euler_xyz_quaternion((-.2, 0, 0)), pose, math.pi), 0)

    def test_geodesic_falloff_and_radius_growth(self):
        rng = random.Random(491)
        for _ in range(1000):
            pose = bs.normalize_quaternion([rng.gauss(0, 1) for _ in range(4)])
            axis = [rng.gauss(0, 1) for _ in range(3)]
            size = math.sqrt(sum(v*v for v in axis))
            axis = [v/size for v in axis]
            radius = math.radians(rng.choice((30, 50, 100, 180)))
            previous = 1.0
            for i in range(181):
                half = math.pi * i / 360
                current = multiply(pose, (*[v*math.sin(half) for v in axis], math.cos(half)))
                weight = bs.pose_weight(current, pose, radius)
                self.assertLessEqual(weight, previous + 1e-7)
                self.assertGreaterEqual(weight, 0)
                self.assertLessEqual(weight, 1)
                self.assertAlmostEqual(weight, bs.pose_weight(tuple(-v for v in current), pose, radius), places=12)
                previous = weight
            current = bs.normalize_quaternion([rng.gauss(0, 1) for _ in range(4)])
            weights = [bs.pose_weight(current, pose, math.radians(r)) for r in (30, 50, 100, 180)]
            self.assertTrue(all(a <= b for a, b in zip(weights, weights[1:])))

    def test_equivalent_euler_representations(self):
        for x, y, z in ((.3, .8, -.4), (1.6, 1.59, -1.7), (.4, -1.57, 2.1)):
            a = bs.euler_xyz_quaternion((x, y, z))
            b = bs.euler_xyz_quaternion((x + math.pi, math.pi - y, z + math.pi))
            self.assertLess(bs.quaternion_angle(a, b), 1e-7)
        a = bs.euler_xyz_quaternion((math.radians(179), 0, 0))
        b = bs.euler_xyz_quaternion((math.radians(-179), 0, 0))
        self.assertAlmostEqual(bs.quaternion_angle(a, b), math.radians(2), places=10)


if __name__ == "__main__":
    unittest.main()
