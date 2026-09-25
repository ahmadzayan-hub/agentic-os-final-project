"""Does the always-valid range actually survive being looked at?

The formula in `server/sequential.py` is taken from the literature, and
a formula transcribed from a paper is a formula that might be
transcribed wrong. So the property it claims — that checking the result
as often as you like does not inflate the error rate — is measured here
rather than asserted: thousands of simulated experiments where nothing
is happening, checked at every step, counting how often each method
cries wolf.

The simulation is seeded, so the numbers below are the same on every
machine and in CI. They are deliberately loose bounds: the point is to
catch a broken implementation, not to pin a Monte Carlo estimate to
three decimals.
"""

import math
import random
import statistics
import unittest

from server import sequential

Z_FIXED = statistics.NormalDist().inv_cdf(0.975)


def alarm_rate(trials, max_n, seed, method, min_n=30, every=5, effect=0.0):
    """How often `method` ever says "this difference is real".

    Each trial runs two arms, checks the verdict every few observations,
    and stops at the first "real" — which is what a person does: look,
    look again, stop when it looks good.

    With `effect=0` the arms are identical, so every alarm is a false
    one and this is an error rate. With `effect` set, an alarm is a
    correct detection and this is the method's power. Same function,
    opposite meanings, which is why the name says what it counts rather
    than what that counts *as*.
    """
    random.seed(seed)
    errors = 0
    for _ in range(trials):
        a_sum = a_sq = b_sum = b_sq = 0.0
        for n in range(1, max_n + 1):
            x = random.gauss(0.0, 1.0)
            y = random.gauss(effect, 1.0)
            a_sum += x
            a_sq += x * x
            b_sum += y
            b_sq += y * y
            if n < min_n or n % every:
                continue
            mean_a, mean_b = a_sum / n, b_sum / n
            variance_a = (a_sq - n * mean_a ** 2) / (n - 1)
            variance_b = (b_sq - n * mean_b ** 2) / (n - 1)
            spread = math.sqrt(variance_a / n + variance_b / n)
            difference = mean_b - mean_a
            if method(difference, spread, n):
                errors += 1
                break
    return errors / trials


def fixed_horizon(difference, spread, n):
    return sequential.excludes_no_change(difference - Z_FIXED * spread,
                                         difference + Z_FIXED * spread)


def always_valid(difference, spread, n):
    return sequential.excludes_no_change(
        *sequential.always_valid_range(difference, spread, n))


class PeekingTestCase(unittest.TestCase):
    """The defect, and the fix, measured side by side."""

    TRIALS = 400
    MAX_N = 600
    SEED = 20260913

    def test_peeking_at_an_ordinary_range_cries_wolf_constantly(self):
        """This is the behaviour the wider range exists to replace. If
        this ever drops near 5%, the simulation has stopped simulating
        peeking and the test below means nothing."""
        rate = alarm_rate(self.TRIALS, self.MAX_N, self.SEED, fixed_horizon)
        self.assertGreater(rate, 0.20,
                           "peeking at a fixed-size range should be badly "
                           "wrong, and this one is not — check the harness")

    def test_the_always_valid_range_holds_up_under_the_same_peeking(self):
        """The claim in one line: same experiments, same peeking, error
        rate inside the 5% budget."""
        rate = alarm_rate(self.TRIALS, self.MAX_N, self.SEED, always_valid)
        self.assertLessEqual(rate, 0.05,
                             f"the always-valid range broke its own promise "
                             f"({rate:.1%} of null experiments called real)")

    def test_it_still_finds_a_difference_that_is_really_there(self):
        """A range wide enough never to be wrong would be a range that
        never says anything. With a full standard deviation of
        separation it should find the effect essentially every time."""
        found = alarm_rate(self.TRIALS, self.MAX_N, self.SEED, always_valid,
                           effect=1.0)
        self.assertGreater(found, 0.90,
                           f"a real effect was found in only {found:.0%} of "
                           "runs — the range is too wide to be useful")


class InflationTestCase(unittest.TestCase):
    """The factor that replaces 1.96, and the shape it has to have."""

    def test_it_is_always_wider_than_the_fixed_size_bound(self):
        """Being allowed to look costs width. A factor below 1.96 would
        mean the guarantee was free, which it is not."""
        for n in (2, 10, 100, 1_000, 10_000, 100_000):
            with self.subTest(n=n):
                self.assertGreater(sequential.inflation(n), Z_FIXED)

    def test_it_is_tightest_around_the_size_it_was_tuned_for(self):
        at_tuning = sequential.inflation(sequential.DEFAULT_TUNING_SIZE)
        self.assertLess(at_tuning, sequential.inflation(50))
        self.assertLess(at_tuning, sequential.inflation(100_000))
        # Roughly half again as wide as 1.96 at the tuning point: the
        # number quoted in the ADR and in the report.
        self.assertAlmostEqual(at_tuning / Z_FIXED, 1.55, places=1)

    def test_the_range_narrows_as_evidence_accumulates(self):
        """Width has to fall with n, or more data would never settle
        anything."""
        radii = [sequential.always_valid_range(10.0, 1.0 / math.sqrt(n), n)[1]
                 for n in (100, 400, 1600, 6400)]
        self.assertEqual(radii, sorted(radii, reverse=True))

    def test_a_stricter_risk_budget_widens_it(self):
        """Splitting 5% across several comparisons has to cost something."""
        self.assertGreater(sequential.inflation(1000, alpha=0.01),
                           sequential.inflation(1000, alpha=0.05))

    def test_an_empty_sample_cannot_bound_anything(self):
        self.assertEqual(sequential.inflation(0), float("inf"))


class RangeTestCase(unittest.TestCase):
    def test_the_range_is_centred_on_the_difference(self):
        low, high = sequential.always_valid_range(5.0, 1.0, 1000)
        self.assertAlmostEqual((low + high) / 2, 5.0, places=9)

    def test_a_range_spanning_zero_is_not_a_result(self):
        self.assertFalse(sequential.excludes_no_change(-1.0, 2.0))
        self.assertFalse(sequential.excludes_no_change(0.0, 2.0))
        self.assertTrue(sequential.excludes_no_change(0.5, 2.0))
        self.assertTrue(sequential.excludes_no_change(-2.0, -0.5))


if __name__ == "__main__":
    unittest.main()
